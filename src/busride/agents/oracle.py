"""Exact answers for any situation, shared by the grader and the agents that count cards.

Every agent in an arena run plays the same deals, so the same situations come up again and
again: each one is solved once. A game too big to solve whole is solved part by part, from the
situation actually reached; a part still too big has no exact answer (None).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from busride.engine.cards import Card, remaining
from busride.engine.game import GameSpec
from busride.engine.solver import (
    DEFAULT_BUDGET,
    Decision,
    GameTooBig,
    Key,
    Solution,
    decide,
    solve,
    solve_from,
)
from busride.engine.stages import Result, judge, state_key, tie_result

_MAX_CACHED = 200_000
_PARTS = 8  # solved parts of a too-big game kept at once


@dataclass(frozen=True)
class Odds:
    """One guess: how many of the cards left make it win."""

    guess: str
    wins: int  # ties that win count here; ties that lose or push don't
    total: int

    @property
    def chance(self) -> float:
        return self.wins / self.total


class Oracle:
    def __init__(self, rules: GameSpec, budget: int = DEFAULT_BUDGET) -> None:
        self.rules = rules
        self.budget = budget
        try:
            self.solution: Solution | None = (
                solve(rules) if budget == DEFAULT_BUDGET else solve_from(rules, (), budget)
            )
        except GameTooBig:
            self.solution = None
        self._decisions: dict[tuple[Card, ...], Decision | None] = {}
        self._odds: dict[tuple[Card, ...], tuple[Odds, ...]] = {}
        self._parts: list[Solution] = []
        self._too_big: set[Key] = set()

    @property
    def rtp(self) -> float | None:
        """Perfect play's return per 1 bet, when the whole game could be solved."""
        return self.solution.rtp if self.solution is not None else None

    def decision(self, seen: Sequence[Card]) -> Decision | None:
        """Every guess scored at this state, or None when it's too big to solve exactly."""
        seen = tuple(seen)
        if seen not in self._decisions:
            if len(self._decisions) >= _MAX_CACHED:
                self._decisions.clear()
            part = self._solution_at(seen)
            self._decisions[seen] = decide(part, seen) if part is not None else None
        return self._decisions[seen]

    def odds(self, seen: Sequence[Card]) -> tuple[Odds, ...]:
        """Each guess's chance to win, in the game's order. Needs no solving."""
        seen = tuple(seen)
        if seen not in self._odds:
            if len(self._odds) >= _MAX_CACHED:
                self._odds.clear()
            self._odds[seen] = self._count(seen)
        return self._odds[seen]

    def _solution_at(self, seen: tuple[Card, ...]) -> Solution | None:
        if self.solution is not None:
            return self.solution
        k = len(seen)
        key = state_key(self.rules, seen)
        for part in reversed(self._parts):
            if key in part.values[k]:
                return part
        if key in self._too_big:
            return None
        try:
            part = solve_from(self.rules, seen, self.budget)
        except GameTooBig:
            self._too_big.add(key)
            return None
        self._parts = [*self._parts[-(_PARTS - 1) :], part]
        return part

    def _count(self, seen: tuple[Card, ...]) -> tuple[Odds, ...]:
        rules = self.rules
        stage = rules.stages[len(seen)]
        known = self._decisions.get(seen)
        if known is not None:
            by_guess = {o.guess: o for o in known.options}
            ties_win = tie_result(stage, rules) is Result.WIN
            return tuple(
                Odds(g, o.wins + (o.ties if ties_win else 0), o.total)
                for g in stage.guesses
                for o in (by_guess[g],)
            )
        pool = remaining(seen, rules.deck_model, rules.effective_decks, rules.ranks)
        total = sum(w for _, w in pool)
        out = []
        for guess in stage.guesses:
            # judge turns a tie into the game's tie result, so a winning tie counts as a win
            wins = sum(
                w
                for card, w in pool
                if judge(stage.number, guess, seen, card, rules)[1] is Result.WIN
            )
            out.append(Odds(guess, wins, total))
        return tuple(out)


_ORACLES: dict[tuple[object, ...], Oracle] = {}


def oracle_for(rules: GameSpec, budget: int = DEFAULT_BUDGET) -> Oracle:
    """The shared oracle for this game and ladder."""
    key = (rules.structure, rules.returns, rules.forced_first_bet, budget)
    oracle = _ORACLES.get(key)
    if oracle is None:
        if len(_ORACLES) >= 8:
            _ORACLES.clear()
        oracle = _ORACLES[key] = Oracle(rules, budget)
    return oracle
