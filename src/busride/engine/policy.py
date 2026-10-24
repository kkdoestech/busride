"""The optimal policy in forms people can use: one decision, a cheat sheet covering every
situation, or a strategy the simulator can play."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from busride.engine.cards import FULL_DECK, SUITS, Card
from busride.engine.game import Stage
from busride.engine.solver import Decision, GameTree, Key, Solution, decide, game_tree
from busride.engine.stages import SUIT_OF_GUESS, survival_problem

MARGINAL = 0.02  # within 2% counts as a coin flip


class AdviceError(ValueError):
    """The cards cannot describe a live round. The message says why, in one line."""


def advise(solution: Solution, seen: Sequence[Card]) -> Decision:
    rules = solution.rules
    if len(seen) >= len(rules.stages):
        raise AdviceError(f"the round is over after {len(rules.stages)} cards")
    problem = survival_problem(seen, rules)
    if problem:
        raise AdviceError(problem)
    if not rules.stages[len(seen)].is_guess:
        raise AdviceError("the next card is only shown, with no guess: type it when it appears")
    return decide(solution, seen)


def grade(play: float, alternative: float) -> str:
    """'good' if `play` beats `alternative` by more than 2%, 'warn' within 2%, else 'bad'."""
    base = max(abs(alternative), 1e-9)
    margin = (play - alternative) / base
    if margin > MARGINAL:
        return "good"
    if margin >= -MARGINAL:
        return "warn"
    return "bad"


# ── the cheat sheet ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SheetCell:
    """The best play in one situation of the cheat sheet."""

    guess: str  # the guess if you play on; for colour and suit: "fewer", "least", "either"...
    should_continue: bool
    unanimous: bool  # False: it depends on earlier cards; the most likely case is shown
    survive: float  # chance the suggested guess wins
    continue_value: float  # going on, per 1 staked
    cash_value: float | None  # stopping; None when the bet can't be refused

    @property
    def grade(self) -> str:
        return grade(self.continue_value, 1.0 if self.cash_value is None else self.cash_value)


@dataclass(frozen=True)
class SheetStage:
    stage: Stage
    index: int  # 1-based guessing stage
    layout: str  # "first" (nothing seen yet), "strip", "grid" or "pattern"
    cash_value: float | None  # None when the bet can't be refused
    # keyed by what you can see: a rank (strip), two ranks (grid), counts per colour or suit
    # (pattern), or () (first)
    cells: dict[Any, SheetCell]


def _reach_weights(solution: Solution, tree: GameTree) -> list[dict[Key, float]]:
    """How likely each state is when you keep playing the best guess and never stop."""
    stages = solution.rules.stages
    weights: list[dict[Key, float]] = [{key: 1.0 for key in tree.levels[0]}]
    for k, level in enumerate(tree.levels[:-1]):
        nxt: dict[Key, float] = {}
        for key, m in weights[k].items():
            branches = level[key]
            if stages[k].is_guess:
                best = solution.best_guess[k][key]
                branches = tuple(b for b in branches if b.guess == best)
            b = branches[0]
            for nk, w in b.wins:
                nxt[nk] = nxt.get(nk, 0.0) + m * w / b.total
        weights.append(nxt)
    return weights


def _layout(stage: Stage, k: int) -> str:
    if stage.kind == "higher_lower":
        return "strip"
    if stage.kind == "inside_outside":
        return "grid"
    return "first" if k == 0 else "pattern"


def _pattern(stage: Stage, seen: tuple[Card, ...], guess: str) -> tuple[tuple[int, ...], str]:
    """(feature, relative guess) for a colour or suit question after some cards.

    The feature is how many cards of each colour (or suit) have appeared, most first.
    """
    if stage.kind == "colour":
        counts = Counter(c.colour for c in seen)
        red, black = counts["red"], counts["black"]
        fewer = "fewer" if counts[guess] == min(red, black) else "more"
        return (max(red, black), min(red, black)), "either" if red == black else fewer
    counts = Counter(c.suit for c in seen)
    by_suit = sorted((counts[s] for s in SUITS), reverse=True)
    rel = "least" if counts[SUIT_OF_GUESS[guess]] == by_suit[-1] else "other"
    return tuple(by_suit), rel


def cheatsheet(solution: Solution) -> tuple[SheetStage, ...]:
    """The best play for every situation, one table per guessing stage.

    Situations are grouped by what you can see at the table (the card being compared against,
    or how many of each colour or suit have appeared). Where the best play also depends on
    earlier cards, the cell shows the most likely case and is marked as not unanimous.
    """
    rules = solution.rules
    tree = game_tree(rules)
    weights = _reach_weights(solution, tree)
    out = []
    for k, stage in enumerate(rules.stages):
        if not stage.is_guess:
            continue
        survived = rules.guesses_before(k)
        cash = None if survived == 0 and rules.forced_first_bet else rules.cash_value(survived)
        layout = _layout(stage, k)
        groups: dict[object, list[_Seen]] = {}
        for key, branches in tree.levels[k].items():
            seen = tree.reps[k][key]
            best = solution.best_guess[k][key]
            branch = next(b for b in branches if b.guess == best)
            guess: str = best
            feature: object
            if layout == "strip":
                feature = seen[stage.refs[0]].rank
            elif layout == "grid":
                feature = (seen[stage.refs[0]].rank, seen[stage.refs[1]].rank)
            elif layout == "pattern":
                feature, guess = _pattern(stage, seen, best)
            else:
                feature = ()
            groups.setdefault(feature, []).append(
                _Seen(
                    weights[k].get(key, 0.0),
                    guess,
                    solution.continues(k, key),
                    branch.win_weight / branch.total,
                    solution.continue_values[k][key],
                )
            )
        cells = {f: _merge(items, cash) for f, items in groups.items()}
        out.append(SheetStage(stage, survived + 1, layout, cash, cells))
    return tuple(out)


@dataclass(frozen=True)
class _Seen:
    """One solver state, as a cheat-sheet cell sees it."""

    weight: float
    guess: str
    goes_on: bool
    survive: float
    continue_value: float


def _merge(items: list[_Seen], cash: float | None) -> SheetCell:
    weights = [s.weight for s in items]
    if not any(weights):  # none of these states is reached when you never stop: weigh them equally
        weights = [1.0] * len(items)
    total = math.fsum(weights)  # fsum: the same answer on every Python version
    by_play: dict[tuple[str, bool], float] = {}
    for w, s in zip(weights, items, strict=True):
        by_play[s.guess, s.goes_on] = by_play.get((s.guess, s.goes_on), 0.0) + w
    guess, goes_on = max(by_play, key=lambda p: by_play[p])
    return SheetCell(
        guess=guess,
        should_continue=goes_on,
        unanimous=len(by_play) == 1,
        survive=math.fsum(w * s.survive for w, s in zip(weights, items, strict=True)) / total,
        continue_value=math.fsum(w * s.continue_value for w, s in zip(weights, items, strict=True))
        / total,
        cash_value=cash,
    )


class SolverStrategy:
    """Plays the solver's policy. The simulator calls it with card names like '9h'."""

    def __init__(self, solution: Solution) -> None:
        self._solution = solution
        self._cards = {str(c): c for c in FULL_DECK}

    def choose(self, stage: int, seen: Sequence[str]) -> str | None:
        k = stage - 1
        key = self._solution.key([self._cards[s] for s in seen])
        if not self._solution.continues(k, key):
            return None
        return self._solution.best_guess[k][key]
