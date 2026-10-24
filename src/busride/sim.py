"""Monte Carlo simulator.

It deals and judges cards with its own code and never calls the solver or the engine's stage
logic, so agreement between the two is evidence that both are right. From the game it reads only
data: each stage's type and which earlier cards it compares with, the deck, ace and tie rules,
and the ladder.

Cards are integers 0..51 here: rank index id // 4 (0 is a 2, 12 is an ace) and suit id % 4
(hearts, diamonds, clubs, spades). A strategy is anything with
`choose(stage, seen_names) -> guess or None`, where stage is the 1-based position in the game,
names are strings like "9h" and None means cash out (or, before the first guess, walk away).
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

_LABELS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
_SUIT_LETTERS = "hdcs"
CARD_NAMES = tuple(f"{_LABELS[i // 4]}{_SUIT_LETTERS[i % 4]}" for i in range(52))
_NAME_TO_ID = {name: i for i, name in enumerate(CARD_NAMES)}
GUESSES = {
    "colour": ("red", "black"),
    "higher_lower": ("higher", "lower"),
    "inside_outside": ("inside", "outside"),
    "suit": ("hearts", "diamonds", "clubs", "spades"),
}


class Strategy(Protocol):
    def choose(self, stage: int, seen: Sequence[str]) -> str | None: ...


class Table:
    """The simulator's own reading of the rules: how cards are dealt and judged."""

    def __init__(self, rules: Any) -> None:
        self.model: str = rules.deck_model
        self.decks: int = rules.decks if rules.deck_model == "shoe" else 1
        self.returns: tuple[float, ...] = tuple(rules.returns)
        self.ace_options: tuple[int, ...] = {"high": (14,), "low": (1,), "either": (14, 1)}[
            rules.ace
        ]
        self.tie_rule = {
            "higher_lower": rules.tie_higher_lower,
            "inside_outside": rules.tie_range_edge,
        }
        self.kinds: tuple[str, ...] = tuple(s.kind for s in rules.stages)
        self.refs: tuple[tuple[int, ...], ...] = tuple(tuple(s.refs) for s in rules.stages)
        self.forced: bool = bool(getattr(rules, "forced_first_bet", True))
        ranks = set(getattr(rules, "ranks", range(2, 15)))
        self.ranks = sorted(ranks)
        self.deck_ids = [i for i in range(52) if i // 4 + 2 in ranks]
        self.guesses_before: list[int] = []
        n = 0
        for kind in self.kinds:
            self.guesses_before.append(n)
            n += kind != "reveal"
        self.guess_count = n
        self._rank_memo: dict[tuple[object, ...], str] = {}

    def deal(self, rng: random.Random) -> list[int]:
        """The whole round's cards, drawn up front; a round that stops early sees a prefix."""
        n, m = len(self.kinds), len(self.deck_ids)
        if self.model == "with_replacement":
            return [self.deck_ids[rng.randrange(m)] for _ in range(n)]
        if self.model == "shoe":
            return [self.deck_ids[j % m] for j in rng.sample(range(m * self.decks), n)]
        return [self.deck_ids[j] for j in rng.sample(range(m), n)]

    def cash(self, survived: int) -> float:
        return 1.0 if survived == 0 else self.returns[survived - 1]

    @staticmethod
    def _worth(card: int, ace: int) -> int:
        rank = card // 4 + 2
        return ace if rank == 14 else rank

    def outcome(self, k: int, guess: str, before: Sequence[int], card: int) -> str:
        """'win', 'lose' or 'push' for one guess on the card dealt at position k."""
        kind = self.kinds[k]
        if kind == "colour":
            return "win" if (card % 4 < 2) == (guess == "red") else "lose"
        if kind == "suit":
            return "win" if _SUIT_LETTERS[card % 4] == guess[0] else "lose"
        result = "lose"
        for ace in self.ace_options:  # with "either" the player gets the better reading
            v = self._worth(card, ace)
            refs = [self._worth(before[i], ace) for i in self.refs[k]]
            if kind == "higher_lower":
                diff = v - refs[0]
                r = "tie" if diff == 0 else ("win" if (diff > 0) == (guess == "higher") else "lose")
            else:
                lo, hi = min(refs), max(refs)
                if v in (lo, hi):
                    r = "tie"
                else:
                    r = "win" if (lo < v < hi) == (guess == "inside") else "lose"
            if r == "tie":
                r = self.tie_rule[kind]
            if r == "win":
                return "win"
            if r == "push":
                result = "push"
        return result

    def win_count(self, k: int, guess: str, seen: Sequence[int]) -> int:
        """Copies left in the deck that make this guess win, counted per suit or per rank."""
        kind = self.kinds[k]
        replace = self.model == "with_replacement"
        if kind in ("colour", "suit"):
            suits = (
                (0, 1)
                if guess == "red"
                else (2, 3)
                if guess == "black"
                else ((_SUIT_LETTERS.index(guess[0]),))
            )
            per_suit = len(self.ranks) * self.decks
            return sum(
                per_suit - (0 if replace else sum(1 for c in seen if c % 4 == s)) for s in suits
            )
        refs = tuple(seen[i] // 4 for i in self.refs[k])
        count = 0
        for rank in self.ranks:
            memo = (k, guess, refs, rank)
            result = self._rank_memo.get(memo)
            if result is None:
                # the suit doesn't matter here, so judge the heart of this rank
                result = self._rank_memo[memo] = self.outcome(k, guess, seen, (rank - 2) * 4)
            if result == "win":
                gone = 0 if replace else sum(1 for c in seen if c // 4 == rank - 2)
                count += 4 * self.decks - gone
        return count


class Greedy:
    """Always takes the guess most likely to survive the stage; cashes out after `stop_after`
    guessing stages (by default it rides to the end)."""

    def __init__(self, rules: Any, stop_after: int | None = None) -> None:
        self.table = Table(rules)
        self.stop_after = self.table.guess_count if stop_after is None else stop_after

    def choose(self, stage: int, seen: Sequence[str]) -> str | None:
        k = stage - 1
        if self.table.guesses_before[k] >= self.stop_after:
            return None
        ids = [_NAME_TO_ID[s] for s in seen]
        options = GUESSES[self.table.kinds[k]]
        best, best_count = options[0], -1
        for guess in options:
            count = self.table.win_count(k, guess, ids)
            if count > best_count:
                best, best_count = guess, count
        return best


def _zeros() -> list[int]:
    return [0] * 5


@dataclass
class SimResult:
    """Counts are indexed by guessing stage (1 = the first question)."""

    rounds: int = 0
    stake: float = 1.0
    total: float = 0.0  # sum of payouts per 1 staked
    total_sq: float = 0.0
    reached: list[int] = field(default_factory=_zeros)  # survived at least k guesses
    lost_at: list[int] = field(default_factory=_zeros)  # index = guessing stage lost
    cashed_after: list[int] = field(default_factory=_zeros)  # index = guesses survived
    pushed_at: list[int] = field(default_factory=_zeros)
    declined: int = 0  # walked away before the first guess (when the game allows it)
    bankroll: list[float] = field(default_factory=lambda: [0.0])  # cumulative net, sampled
    seconds: float = 0.0

    @property
    def mean(self) -> float:
        return self.total / self.rounds if self.rounds else 0.0

    @property
    def se(self) -> float:
        n = self.rounds
        if n < 2:
            return 0.0
        var = (self.total_sq - n * self.mean**2) / (n - 1)
        return math.sqrt(max(var, 0.0) / n)

    @property
    def ci95(self) -> tuple[float, float]:
        return self.mean - 1.96 * self.se, self.mean + 1.96 * self.se

    @property
    def net(self) -> float:
        return (self.total - self.rounds) * self.stake

    def reach_rate(self, k: int) -> tuple[float, float]:
        """Share of rounds that survived at least k guesses, with its standard error."""
        p = self.reached[k] / self.rounds if self.rounds else 0.0
        return p, math.sqrt(p * (1 - p) / self.rounds) if self.rounds else 0.0


def play_round(
    table: Table, strategy: Strategy, rng: random.Random
) -> tuple[str, int, float, list[int]]:
    """One round: (how it ended, guessing stage, payout per 1 staked, cards revealed).

    How it ended is 'lost' (stage = the guess lost), 'cash' or 'push' (stage = guesses
    survived), 'declined' (walked away before the first guess) or 'full' (every guess won).
    """
    deck = table.deal(rng)
    seen: list[int] = []
    survived = 0
    for k, kind in enumerate(table.kinds):
        card = deck[k]
        if kind == "reveal":
            seen.append(card)
            continue
        guess = strategy.choose(k + 1, [CARD_NAMES[c] for c in seen])
        if guess is None:
            if survived:
                return "cash", survived, table.cash(survived), seen
            if not table.forced:
                return "declined", 0, 1.0, seen
            guess = GUESSES[kind][0]  # the bet is placed: the first guess can't be skipped
        result = table.outcome(k, guess, seen, card)
        seen.append(card)
        if result == "lose":
            return "lost", survived + 1, 0.0, seen
        if result == "push":
            return "push", survived, table.cash(survived), seen
        survived += 1
    return "full", survived, table.returns[-1], seen


def simulate(
    rules: Any,
    strategy: Strategy,
    rounds: int,
    seed: int | None = None,
    stake: float = 1.0,
    on_progress: Callable[[SimResult], None] | None = None,
    progress_every: int = 5000,
    samples: int = 120,
    record: Callable[[list[str], float | None], None] | None = None,
) -> SimResult:
    """Play `rounds` rounds. `record` receives each round's revealed cards and payout per 1."""
    started = time.perf_counter()
    rng = random.Random(seed)
    table = Table(rules)
    g = table.guess_count
    res = SimResult(
        stake=stake,
        reached=[0] * (g + 1),
        lost_at=[0] * (g + 1),
        cashed_after=[0] * (g + 1),
        pushed_at=[0] * (g + 1),
    )
    sample_every = max(1, rounds // samples)
    net = 0.0
    for i in range(1, rounds + 1):
        end, stage, payout, seen = play_round(table, strategy, rng)
        res.total += payout
        res.total_sq += payout * payout
        survived = stage - 1 if end == "lost" else stage
        for k in range(survived + 1):
            res.reached[k] += 1
        if end == "lost":
            res.lost_at[stage] += 1
        elif end == "push":
            res.pushed_at[stage + 1] += 1
        elif end == "declined":
            res.declined += 1
        else:
            res.cashed_after[stage] += 1
        net += (payout - 1.0) * stake
        res.rounds = i
        if i % sample_every == 0:
            res.bankroll.append(net)
        if record is not None:
            record([CARD_NAMES[c] for c in seen], payout if end != "lost" else None)
        if on_progress is not None and i % progress_every == 0:
            res.seconds = time.perf_counter() - started
            on_progress(res)
    res.seconds = time.perf_counter() - started
    return res


def generate_rounds(
    rules: Any, strategy: Strategy, rounds: int, seed: int | None = None
) -> list[tuple[list[str], float | None]]:
    """Synthetic round logs: the cards revealed and the payout per 1 staked (None if lost)."""
    out: list[tuple[list[str], float | None]] = []
    simulate(rules, strategy, rounds, seed, record=lambda cards, paid: out.append((cards, paid)))
    return out
