"""Exact solver: backward induction over every state a game can reach.

The work splits in two. `build_tree` enumerates states and, for each guess, where the winning
cards lead; it depends only on the stages, deck, ace and tie rules, and is cached. `solve` then
runs backward induction for one payout ladder in a few milliseconds:

    V(s) = max(cash value of s, max_g sum_c P(c | s) * [g wins on c] * V(s + c))

Reveal stages are chance nodes (no choice, no cash-out). With `forced_first_bet` the first
guess cannot be declined; otherwise declining keeps the stake, worth 1.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from busride.engine.cards import FULL_DECK, Card, copies_per_card, deck_of, remaining
from busride.engine.game import GameSpec, Stage
from busride.engine.stages import (
    Outcome,
    Result,
    cell,
    judge,
    projection,
    state_key,
    tie_result,
)

Key = tuple[object, ...]
DEFAULT_BUDGET = 250_000
_EPS = 1e-12


class GameTooBig(ValueError):
    """The game has more distinct situations than the exact solver will visit."""


@dataclass(frozen=True)
class Branch:
    """One guess at one state: the weight of cards that win (grouped by where they lead).

    A reveal stage has a single branch with guess "" in which every card "wins".
    """

    guess: str
    total: int
    wins: tuple[tuple[Key, int], ...]
    push: int

    @property
    def win_weight(self) -> int:
        return sum(w for _, w in self.wins)


@dataclass(frozen=True)
class GameTree:
    """Every reachable state, level by level (k = cards seen), with the branches of each, and
    one card sequence that leads to each state."""

    levels: tuple[dict[Key, tuple[Branch, ...]], ...]
    terminal: Key
    reps: tuple[dict[Key, tuple[Card, ...]], ...] = ()

    @property
    def size(self) -> int:
        return sum(len(level) for level in self.levels)


@lru_cache(maxsize=256)
def _deck_cells(
    ranks: tuple[int, ...], needs_rank: bool, mode: str
) -> tuple[tuple[tuple[int, str], tuple[Card, ...]], ...]:
    """The deck split into cells the remaining stages can't tell apart, cards in deck order."""
    groups: dict[tuple[int, str], list[Card]] = {}
    for card in deck_of(ranks):
        groups.setdefault(cell(card, needs_rank, mode), []).append(card)
    return tuple((c, tuple(cards)) for c, cards in groups.items())


def _next_cards(rules: GameSpec, seen: tuple[Card, ...], k: int) -> list[tuple[Card, int]]:
    """What can come next: one representative card per cell, weighted by copies left.

    Counting per cell (deck totals minus the few cards seen) keeps a 28,000-state tree fast.
    """
    needs_rank, mode, _ = projection(rules, k)
    cells = _deck_cells(rules.ranks, needs_rank, mode)
    copies = copies_per_card(rules.deck_model, rules.effective_decks)
    if copies is None:
        return [(cards[0], len(cards)) for _, cards in cells]
    used = Counter(cell(c, needs_rank, mode) for c in seen)
    gone = set(seen)
    out = []
    for c, cards in cells:
        left = len(cards) * copies - used[c]
        if left > 0:
            rep = next((x for x in cards if x not in gone), cards[0])
            out.append((rep, left))
    return out


def build_tree(
    rules: GameSpec, budget: int = DEFAULT_BUDGET, start: Sequence[Card] = ()
) -> GameTree:
    """Every state reachable from `start` (the deal so far; empty for the whole game)."""
    n = len(rules.stages)
    start = tuple(start)
    reps: list[dict[Key, tuple[Card, ...]]] = [{} for _ in range(n + 1)]
    reps[len(start)][state_key(rules, start)] = start
    levels: list[dict[Key, tuple[Branch, ...]]] = []
    count = 1
    for k, stage in enumerate(rules.stages):
        level: dict[Key, tuple[Branch, ...]] = {}
        # a guess's result depends only on the compared cards' ranks and the new card
        judged: dict[tuple[str, tuple[int, ...], Card], Result] = {}
        for key, seen in reps[k].items():
            cells = _next_cards(rules, seen, k)
            total = sum(w for _, w in cells)
            compared = tuple(seen[i].rank for i in stage.refs)
            branches = []
            for guess in stage.guesses if stage.is_guess else ("",):
                to: dict[Key, int] = {}
                push = 0
                for card, w in cells:
                    if stage.is_guess:
                        jk = (guess, compared, card)
                        result = judged.get(jk)
                        if result is None:
                            result = judged[jk] = judge(stage.number, guess, seen, card, rules)[1]
                    else:
                        result = Result.WIN
                    if result is Result.WIN:
                        nxt = (*seen, card)
                        nk = state_key(rules, nxt)
                        to[nk] = to.get(nk, 0) + w
                        if k + 1 < n and nk not in reps[k + 1]:
                            reps[k + 1][nk] = nxt
                            count += 1
                            if count > budget:
                                raise GameTooBig(
                                    f"{rules.name} has too many distinct situations (over "
                                    f"{budget:,}) to solve exactly"
                                )
                    elif result is Result.PUSH:
                        push += w
                branches.append(Branch(guess, total, tuple(to.items()), push))
            level[key] = tuple(branches)
        levels.append(level)
    # at the end of a round nothing is left to depend on, so every full round shares one key
    return GameTree(tuple(levels), state_key(rules, FULL_DECK[:n]), tuple(reps[:n]))


_TREES: dict[tuple[object, ...], GameTree] = {}


def game_tree(rules: GameSpec) -> GameTree:
    """The tree for these rules, built once: it doesn't depend on the ladder."""
    key = rules.structure
    tree = _TREES.get(key)
    if tree is None:
        if len(_TREES) >= 256:
            _TREES.clear()
        tree = _TREES[key] = build_tree(rules)
    return tree


def clear_cache() -> None:
    _TREES.clear()


@dataclass(frozen=True)
class Solution:
    """Optimal values and guesses for one game and ladder.

    values[k][key] is the value with k cards seen; values[0] holds the value of starting a round
    (the RTP: average return per 1 staked under perfect play).
    """

    rules: GameSpec
    values: tuple[dict[Key, float], ...]
    continue_values: tuple[dict[Key, float], ...]
    best_guess: tuple[dict[Key, str], ...]

    @property
    def rtp(self) -> float:
        return next(iter(self.values[0].values()))

    def key(self, seen: Sequence[Card]) -> Key:
        return state_key(self.rules, seen)

    def value(self, seen: Sequence[Card]) -> float:
        return self.values[len(seen)][self.key(seen)]

    def continues(self, k: int, key: Key) -> bool:
        """True when the policy plays on with k cards seen. On an exact tie it takes the money."""
        rules = self.rules
        if not rules.stages[k].is_guess:
            return True
        survived = rules.guesses_before(k)
        if survived == 0 and rules.forced_first_bet:
            return True
        return self.continue_values[k][key] > rules.cash_value(survived) + _EPS


def _solve(rules: GameSpec, stake_back: float, tree: GameTree | None = None) -> Solution:
    if tree is None:
        tree = game_tree(rules)
    n = len(rules.stages)
    values: list[dict[Key, float]] = [{} for _ in range(n + 1)]
    conts: list[dict[Key, float]] = [{} for _ in range(n)]
    guesses: list[dict[Key, str]] = [{} for _ in range(n)]
    values[n][tree.terminal] = rules.cash_value(rules.guess_count)
    for k in range(n - 1, -1, -1):
        stage = rules.stages[k]
        survived = rules.guesses_before(k)
        cash = rules.cash_value(survived) if survived else stake_back
        can_stop = stage.is_guess and (survived > 0 or not rules.forced_first_bet)
        nxt = values[k + 1]
        for key, branches in tree.levels[k].items():
            best_ev, best = -1.0, branches[0]
            for b in branches:
                ev = (sum(w * nxt[nk] for nk, w in b.wins) + b.push * cash) / b.total
                # equal value: prefer the guess more likely to win, as the advisor shows it
                if ev > best_ev + _EPS or (ev > best_ev - _EPS and b.win_weight > best.win_weight):
                    best_ev, best = ev, b
            best_guess = best.guess
            conts[k][key] = best_ev
            guesses[k][key] = best_guess
            values[k][key] = max(cash, best_ev) if can_stop else best_ev
    return Solution(rules, tuple(values), tuple(conts), tuple(guesses))


def solve(rules: GameSpec) -> Solution:
    return _solve(rules, stake_back=1.0)


def solve_from(
    rules: GameSpec, seen: Sequence[Card] = (), budget: int = DEFAULT_BUDGET
) -> Solution:
    """Solve only what can follow `seen`, for games too big to solve whole.

    The values cover that part of the game, so `decide` works at `seen` and every state after
    it (but `rtp` needs an empty `seen`). Raises GameTooBig past `budget` states.
    """
    return _solve(rules, 1.0, build_tree(rules, budget, start=seen))


def survival(rules: GameSpec) -> tuple[float, ...]:
    """S_k: the best possible chance of surviving k guessing stages (k = 1..G).

    Each is the RTP of a ladder that pays 1 at stage k and nothing elsewhere, with the first bet
    forced and a push worth nothing.
    """
    forced = replace(rules, forced_first_bet=True)
    g = rules.guess_count
    out = []
    for k in range(g):
        ladder = [0.0] * g
        ladder[k] = 1.0
        out.append(_solve(forced.with_returns(ladder), stake_back=0.0).rtp)
    return tuple(out)


def branch_of(rules: GameSpec, seen: Sequence[Card], guess: str) -> Branch:
    """Where `guess` leads from these exact cards: the same Branch build_tree makes for the
    state's representative. Two guesses with equal branches are the same move up to a relabelling
    of suits, which is how a policy learned on the tree is played with real cards."""
    seen = tuple(seen)
    k = len(seen)
    stage = rules.stages[k]
    cells = _next_cards(rules, seen, k)
    to: dict[Key, int] = {}
    push = 0
    for card, w in cells:
        result = judge(stage.number, guess, seen, card, rules)[1]
        if result is Result.WIN:
            nk = state_key(rules, (*seen, card))
            to[nk] = to.get(nk, 0) + w
        elif result is Result.PUSH:
            push += w
    return Branch(guess, sum(w for _, w in cells), tuple(to.items()), push)


def same_move(a: Branch, b: Branch) -> bool:
    return a.total == b.total and a.push == b.push and dict(a.wins) == dict(b.wins)


def policy_value(
    rules: GameSpec, choose: Callable[[int, Key], str | None], tree: GameTree | None = None
) -> float:
    """The exact return per 1 bet of a policy over the tree's states.

    `choose(k, key)` names a guess (by the label of the state's representative, as in the tree's
    branches) or None to cash out. Where cashing out isn't allowed, None plays the first guess.
    """
    if tree is None:
        tree = game_tree(rules)
    n = len(rules.stages)
    values: list[dict[Key, float]] = [{} for _ in range(n + 1)]
    values[n][tree.terminal] = rules.cash_value(rules.guess_count)
    for k in range(n - 1, -1, -1):
        stage = rules.stages[k]
        survived = rules.guesses_before(k)
        cash = rules.cash_value(survived)
        can_stop = stage.is_guess and (survived > 0 or not rules.forced_first_bet)
        nxt = values[k + 1]
        for key, branches in tree.levels[k].items():
            branch = branches[0]
            if stage.is_guess:
                pick = choose(k, key)
                if pick is None and can_stop:
                    values[k][key] = cash
                    continue
                branch = next((b for b in branches if b.guess == pick), branches[0])
            values[k][key] = (
                sum(w * nxt[nk] for nk, w in branch.wins) + branch.push * cash
            ) / branch.total
    return next(iter(values[0].values()))


@dataclass(frozen=True)
class FixedPlan:
    """Greedy guessing (best chance to survive each stage), cashing out after `stop_after`."""

    stop_after: int
    value: float
    reach: tuple[float, ...]  # P(survive k guessing stages), k = 1..stop_after


def fixed_plan(rules: GameSpec, stop_after: int | None = None) -> FixedPlan:
    """Exact value of the greedy fixed plan. Ties between guesses go to the first listed."""
    stop = rules.guess_count if stop_after is None else stop_after
    tree = game_tree(rules)
    mass: dict[Key, float] = {state_key(rules, ()): 1.0}
    paid = 0.0
    reach = []
    for k, stage in enumerate(rules.stages):
        survived = rules.guesses_before(k)
        if stage.is_guess and survived == stop:
            break
        cash = rules.cash_value(survived)
        nxt: dict[Key, float] = {}
        for key, m in mass.items():
            branches = tree.levels[k][key]
            branch = max(branches, key=lambda b: b.win_weight)  # first max wins ties
            paid += m * branch.push / branch.total * cash
            for nk, w in branch.wins:
                nxt[nk] = nxt.get(nk, 0.0) + m * w / branch.total
        mass = nxt
        if stage.is_guess:
            reach.append(sum(mass.values()))
    paid += sum(mass.values()) * rules.cash_value(stop)
    return FixedPlan(stop, paid, tuple(reach))


@dataclass(frozen=True)
class GuessOption:
    """One guess at the current state, with card counts you can check by eye."""

    guess: str
    wins: int
    losses: int
    ties: int
    pushes: int
    total: int
    tie_result: Result
    ev: float  # expected return per 1 staked: make this guess, then play on optimally

    @property
    def win_chance(self) -> float:
        return self.wins / self.total

    @property
    def survive_chance(self) -> float:
        """Chance this guess keeps the round alive (ties count when they win)."""
        alive = self.wins + (self.ties if self.tie_result is Result.WIN else 0)
        return alive / self.total


@dataclass(frozen=True)
class Decision:
    """What to do with the cards seen so far."""

    stage: Stage  # the stage about to be played
    seen: tuple[Card, ...]
    cash_out: float  # stopping now; before the first guess this is keeping your stake
    options: tuple[GuessOption, ...]  # best first

    @property
    def best(self) -> GuessOption:
        return self.options[0]

    @property
    def continue_value(self) -> float:
        return self.best.ev

    @property
    def should_continue(self) -> bool:
        return self.continue_value > self.cash_out + _EPS


def decide(solution: Solution, seen: Sequence[Card]) -> Decision:
    """Score every guess at this exact state (seen must be survivable; see survival_problem)."""
    rules = solution.rules
    seen = tuple(seen)
    k = len(seen)
    stage = rules.stages[k]
    if not stage.is_guess:
        raise ValueError(f"stage {stage.number} only shows a card; there is nothing to decide")
    pool = remaining(seen, rules.deck_model, rules.effective_decks, rules.ranks)
    total = sum(w for _, w in pool)
    nxt = solution.values[k + 1]
    cash = rules.cash_value(rules.guesses_before(k))
    tie_res = tie_result(stage, rules)
    options = []
    for guess in stage.guesses:
        counts = {Outcome.WIN: 0, Outcome.LOSE: 0, Outcome.TIE: 0}
        pushes = 0
        ev = 0.0
        for card, w in pool:
            raw, result = judge(stage.number, guess, seen, card, rules)
            counts[raw] += w
            if result is Result.WIN:
                ev += w * nxt[state_key(rules, (*seen, card))]
            elif result is Result.PUSH:
                ev += w * cash
                pushes += w
        options.append(
            GuessOption(
                guess,
                counts[Outcome.WIN],
                counts[Outcome.LOSE],
                counts[Outcome.TIE],
                pushes,
                total,
                tie_res,
                ev / total,
            )
        )
    options.sort(key=lambda o: (-round(o.ev, 12), -o.survive_chance))
    return Decision(stage, seen, cash, tuple(options))


@dataclass(frozen=True)
class StageLine:
    stage: Stage
    win_chance: float  # given you survived the stages before
    survive: float  # S_k
    fair: float  # 1 / S_k
    offered: float  # R_k
    break_even: float  # what this stage would need to pay for perfect play to break even
    plan_edge: float | None  # 1 - R_k S_k: always play to stage k and cash out there
    step_edge: float | None  # 1 - p_k R_k / R_{k-1}: what letting the pot ride one stage costs


@dataclass(frozen=True)
class Analysis:
    rules: GameSpec
    rtp: float | None  # None until the ladder is captured
    stages: tuple[StageLine, ...]  # one per guessing stage
    fair_ladder_rtp: float  # optimal RTP if the game paid the fair fixed-plan ladder
    worst_step: int | None  # guessing stage (1-based) with the largest step edge
    alt_model: str
    alt_rtp: float | None
    alt_survive_all: float
    states: int
    seconds: float


def analyze(rules: GameSpec) -> Analysis:
    started = time.perf_counter()
    surv = survival(rules)
    fair = tuple(1.0 / s for s in surv)
    fair_rtp = solve(rules.with_returns(fair)).rtp
    rtp = solve(rules).rtp if rules.ladder_captured else None

    lines = []
    for i, stage in enumerate(rules.guess_stages):
        r = rules.returns[i]
        prev_s = surv[i - 1] if i else 1.0
        prev_r = rules.cash_value(i)
        p = surv[i] / prev_s
        # your ladder scaled to break even; before it is captured, the fair shape scaled
        break_even = r / rtp if rtp else fair[i] / fair_rtp
        lines.append(
            StageLine(
                stage=stage,
                win_chance=p,
                survive=surv[i],
                fair=fair[i],
                offered=r,
                break_even=break_even,
                plan_edge=1.0 - r * surv[i] if rules.ladder_captured else None,
                step_edge=1.0 - p * r / prev_r if rules.ladder_captured and prev_r > 0 else None,
            )
        )
    steps = [(ln.step_edge, i + 1) for i, ln in enumerate(lines) if ln.step_edge is not None]
    worst = max(steps)[1] if steps else None

    alt_model = "with_replacement" if rules.deck_model != "with_replacement" else "fresh_52"
    alt = rules.with_deck(alt_model, 1)
    elapsed = time.perf_counter() - started
    return Analysis(
        rules=rules,
        rtp=rtp,
        stages=tuple(lines),
        fair_ladder_rtp=fair_rtp,
        worst_step=worst,
        alt_model=alt_model,
        alt_rtp=solve(alt).rtp if rules.ladder_captured else None,
        alt_survive_all=survival(alt)[-1],
        states=game_tree(rules).size,
        seconds=elapsed,
    )
