"""Playing with fake chips: dealing, judging, and grading every decision exactly.

No input or output here: the CLI asks the questions, this keeps the score. A decision's grade is
its regret, the value of the best move minus the value of the move made (per 1 staked), straight
from the solver, so it measures the decision and not the luck of the next card.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from busride.engine.cards import Card, remaining
from busride.engine.game import GameSpec, Stage
from busride.engine.solver import Decision, Solution, decide, solve
from busride.engine.stages import Result, judge

_EPS = 1e-9
CASH = "cash"
CLOSE = 0.02  # within 2% of the best move's value counts as close


@dataclass(frozen=True)
class Graded:
    """One decision, scored against perfect play."""

    round: int
    stage: int  # guessing stage, 1-based
    seen: tuple[Card, ...]
    action: str  # the guess made, or "cash"
    best: str  # the best move ("cash" when stopping was best)
    q: float  # what the move made was worth, per 1 staked
    value: float  # what the best move was worth
    worst: float  # what the worst legal move was worth
    forced: bool  # the bet could not be refused here

    @property
    def regret(self) -> float:
        return max(0.0, self.value - self.q)

    @property
    def optimal(self) -> bool:
        return self.regret <= _EPS

    @property
    def trivial(self) -> bool:
        """Every legal move was worth the same: nothing to get right or wrong."""
        return self.value - self.worst <= _EPS


def grade(solution: Solution, seen: Sequence[Card], action: str, round_no: int = 0) -> Graded:
    """Score `action` (a guess or "cash") with `seen` on the table."""
    return grade_decision(decide(solution, seen), solution.rules, action, round_no)


def grade_decision(d: Decision, rules: GameSpec, action: str, round_no: int = 0) -> Graded:
    """Score `action` against a decision the solver has already scored."""
    seen = d.seen
    survived = rules.guesses_before(len(seen))
    forced = survived == 0 and rules.forced_first_bet
    values = {o.guess: o.ev for o in d.options}
    if not forced:
        values[CASH] = d.cash_out
    if action not in values:
        raise ValueError(f"{action!r} is not a move here: choose one of {', '.join(values)}")
    best = CASH if (not forced and not d.should_continue) else d.best.guess
    return Graded(
        round=round_no,
        stage=survived + 1,
        seen=tuple(seen),
        action=action,
        best=best,
        q=values[action],
        value=values[best],
        worst=min(values.values()),
        forced=forced,
    )


@dataclass(frozen=True)
class Step:
    """What happened after one move."""

    card: Card | None  # the card dealt (None when you cashed out)
    result: str  # "win", "lose", "push", "cash", "walk" (left before betting) or "shown"
    graded: Graded | None
    payout: float | None  # chips paid when the round ended here


class Round:
    """One round at the table. The stake is taken when the round starts."""

    def __init__(self, session: Session, number: int) -> None:
        self.session = session
        self.number = number
        self.seen: list[Card] = []
        self.survived = 0
        self.over: str | None = None  # how it ended: lost, cash, walk, push, full
        self.payout = 0.0
        self.graded: list[Graded] = []

    @property
    def rules(self) -> GameSpec:
        return self.session.rules

    @property
    def next_stage(self) -> Stage | None:
        return None if self.over else self.rules.stages[len(self.seen)]

    @property
    def can_stop(self) -> bool:
        return self.survived > 0 or not self.rules.forced_first_bet

    @property
    def pot(self) -> float:
        """What stopping now pays, in chips (before the first guess: your stake back)."""
        return self.session.stake * self.rules.cash_value(self.survived)

    def decision(self) -> Decision:
        return decide(self.session.solution, self.seen)

    def reveal(self) -> Step:
        stage = self._stage()
        if stage.is_guess:
            raise ValueError(f"stage {stage.number} needs a guess")
        card = self.session.deal(self.seen)
        self.seen.append(card)
        self._maybe_full()
        return Step(card, "shown", None, self.payout if self.over else None)

    def act(self, action: str) -> Step:
        stage = self._stage()
        if not stage.is_guess:
            raise ValueError(f"stage {stage.number} only shows a card")
        graded = grade(self.session.solution, self.seen, action, self.number)
        self.graded.append(graded)
        self.session.graded.append(graded)
        if action == CASH:
            self._end("cash" if self.survived else "walk", self.pot)
            return Step(None, self.over or "cash", graded, self.payout)
        card = self.session.deal(self.seen)
        result = judge(stage.number, action, self.seen, card, self.rules)[1]
        self.seen.append(card)
        if result is Result.LOSE:
            self._end("lost", 0.0)
            return Step(card, "lose", graded, 0.0)
        if result is Result.PUSH:
            self._end("push", self.pot)
            return Step(card, "push", graded, self.payout)
        self.survived += 1
        self._maybe_full()
        return Step(card, "win", graded, self.payout if self.over else None)

    def _stage(self) -> Stage:
        stage = self.next_stage
        if stage is None:
            raise ValueError("this round is over")
        return stage

    def _maybe_full(self) -> None:
        if len(self.seen) == len(self.rules.stages) and not self.over:
            self._end("full", self.session.stake * self.rules.returns[-1])

    def _end(self, how: str, payout: float) -> None:
        self.over = how
        self.payout = payout
        self.session.chips += payout


@dataclass(frozen=True)
class Summary:
    rounds: int
    start_chips: float
    chips: float
    net: float
    decisions: int  # decisions with a real choice to make
    best_moves: int
    close_moves: int  # not the best, but within 2% of it
    given_up: float  # chips lost to imperfect play, on average
    biggest: Graded | None
    expected_net: float  # what the play was worth, on average
    luck: float  # the rest of the result
    endings: dict[str, int] = field(default_factory=dict)


class Session:
    """A sitting at the table with fake chips.

    `cards` deals a fixed sequence first (for tests and replays), then random cards follow.
    """

    def __init__(
        self,
        rules: GameSpec,
        chips: float = 1000.0,
        stake: float = 10.0,
        seed: int | None = None,
        cards: Iterable[Card] | None = None,
        solution: Solution | None = None,
    ) -> None:
        self.rules = rules
        self.solution = solution or solve(rules)
        self.start_chips = float(chips)
        self.chips = float(chips)
        self.stake = float(stake)
        self.rng = random.Random(seed)
        self._fixed: Iterator[Card] | None = iter(cards) if cards is not None else None
        self.rounds: list[Round] = []
        self.graded: list[Graded] = []

    def can_play(self) -> bool:
        return self.chips + _EPS >= self.stake

    def new_round(self) -> Round:
        if not self.can_play():
            raise ValueError(f"not enough chips for a stake of {self.stake:g}")
        self.chips -= self.stake
        rnd = Round(self, len(self.rounds) + 1)
        self.rounds.append(rnd)
        return rnd

    def deal(self, seen: Sequence[Card]) -> Card:
        if self._fixed is not None:
            card = next(self._fixed, None)
            if card is not None:
                return card
            self._fixed = None
        pool = remaining(seen, self.rules.deck_model, self.rules.effective_decks, self.rules.ranks)
        return self.rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0]

    def summary(self) -> Summary:
        real = [g for g in self.graded if not g.trivial]
        given_up = math.fsum(g.regret for g in self.graded) * self.stake
        # on average a round returns the perfect-play value, less the regrets along the way
        expected = len(self.rounds) * self.stake * (self.solution.rtp - 1.0) - given_up
        net = self.chips - self.start_chips
        endings: dict[str, int] = {}
        for rnd in self.rounds:
            how = rnd.over or "unfinished"
            endings[how] = endings.get(how, 0) + 1
        biggest = max(real, key=lambda g: g.regret, default=None)
        return Summary(
            rounds=len(self.rounds),
            start_chips=self.start_chips,
            chips=self.chips,
            net=net,
            decisions=len(real),
            best_moves=sum(1 for g in real if g.optimal),
            close_moves=sum(1 for g in real if not g.optimal and g.regret <= CLOSE * g.value),
            given_up=given_up,
            biggest=biggest if biggest is not None and biggest.regret > _EPS else None,
            expected_net=expected,
            luck=net - expected,
            endings=endings,
        )


_LETTERS = {
    "colour": {"r": "red", "b": "black"},
    "higher_lower": {"h": "higher", "l": "lower", "+": "higher", "-": "lower"},
    "inside_outside": {"i": "inside", "o": "outside"},
    "suit": {"h": "hearts", "d": "diamonds", "c": "clubs", "s": "spades"},
}


def parse_choice(text: str, stage: Stage, can_stop: bool) -> str | None:
    """A typed choice: a number, a letter, a word, "$" to cash out or "q" to quit.

    None means it wasn't understood (or isn't allowed here, like cashing out before betting).
    """
    word = text.strip().lower()
    if word in ("q", "quit", "exit"):
        return "quit"
    if word in ("$", "cash", "stop", "cash out", "walk", "walk away"):
        return CASH if can_stop else None
    guesses = stage.guesses
    if word.isdigit() and 1 <= int(word) <= len(guesses):
        return guesses[int(word) - 1]
    if word in guesses:
        return word
    return _LETTERS.get(stage.kind, {}).get(word)
