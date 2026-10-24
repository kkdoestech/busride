"""Runs the verification tests as one family and sums them up. Rendering lives in bus.ui."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from busride.engine.cards import Card
from busride.engine.rules import Rules
from busride.stats.tests import (
    CANDIDATE_MODELS,
    ModelFit,
    TestResult,
    chi_square_test,
    colour_test,
    duplicate_test,
    holm,
    model_fit,
    model_label,
    repeat_test,
)


@dataclass(frozen=True)
class VerifyReport:
    rounds: int
    cards: int
    rules_model: str
    alpha: float
    tests: tuple[TestResult, ...]  # Holm-adjusted as one family
    models: tuple[ModelFit, ...]
    best: ModelFit | None  # None when no round shows two cards yet

    @property
    def flagged(self) -> tuple[TestResult, ...]:
        return tuple(t for t in self.tests if t.flagged)


def verify(rounds: Sequence[Sequence[Card]], rules: Rules, alpha: float = 0.05) -> VerifyReport:
    """Test logged rounds (cards in the order shown, oldest round first) against the rules."""
    model, decks = rules.deck_model, rules.effective_decks
    rounds = [list(r) for r in rounds if r]
    tests = [
        duplicate_test(rounds, model, decks, alpha),
        chi_square_test(rounds, model, decks, "rank"),
        chi_square_test(rounds, model, decks, "suit"),
        colour_test(rounds),
        repeat_test(rounds, model, decks),
    ]
    adjusted = holm([t.p_value for t in tests])
    tests = [
        replace(t, p_adjusted=a, flagged=a is not None and a < alpha)
        for t, a in zip(tests, adjusted, strict=True)
    ]
    fits = tuple(model_fit(rounds, m, d, alpha) for m, d in CANDIDATE_MODELS)
    informative = any(len(r) >= 2 for r in rounds)
    consistent = [f for f in fits if f.consistent]
    best = max(consistent, key=lambda f: f.loglik) if informative and consistent else None
    return VerifyReport(
        rounds=len(rounds),
        cards=sum(len(r) for r in rounds),
        rules_model=model_label(model, decks),
        alpha=alpha,
        tests=tuple(tests),
        models=fits,
        best=best,
    )


@dataclass(frozen=True)
class PayoutGroup:
    cards: int  # cards revealed in those rounds
    multiple: float  # paid / stake
    rounds: int
    expected: float  # the ladder's return after surviving `cards` stages
    matches_stage: int | None  # the ladder stage this multiple matches, if any

    @property
    def ok(self) -> bool:
        return self.matches_stage is not None


@dataclass(frozen=True)
class PayoutCheck:
    paid_rounds: int
    groups: tuple[PayoutGroup, ...]

    @property
    def mismatches(self) -> tuple[PayoutGroup, ...]:
        return tuple(g for g in self.groups if not g.ok)


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.005 * abs(b))


def check_payouts(
    paid: Sequence[tuple[int, float, float]], returns: Sequence[float]
) -> PayoutCheck:
    """Compare what the game actually paid with the ladder in rules.toml.

    `paid` holds (cards revealed, stake, amount paid) for each round that paid out. A round
    that matches a different stage than its card count is still fine: the game may show
    extra cards after a cash-out, or a push pays the stage before.
    """
    groups: dict[tuple[int, float], int] = {}
    for n, stake, amount in paid:
        if stake <= 0:
            continue
        key = (n, round(amount / stake, 2))
        groups[key] = groups.get(key, 0) + 1
    out = []
    for (n, multiple), count in sorted(groups.items()):
        expected = returns[n - 1] if 1 <= n <= 4 else 0.0
        match = None
        if 1 <= n <= 4 and _close(multiple, expected):
            match = n
        else:
            match = next(
                (i + 1 for i, r in enumerate(returns) if r > 0 and _close(multiple, r)), None
            )
        out.append(PayoutGroup(n, multiple, count, expected, match))
    return PayoutCheck(sum(groups.values()), tuple(out))
