"""Verify power: synthetic logs with known properties go through `busride verify`'s tests."""

import random
import time

import pytest
from scipy import stats as sps

from busride.engine.cards import FULL_DECK, Card, parse_card
from busride.engine.rules import Rules
from busride.sim import Greedy, generate_rounds
from busride.stats.report import check_payouts, verify
from busride.stats.tests import holm, no_duplicate_chance, poisson_binomial_cdf

FRESH = Rules(returns=(2.0, 2.7, 4.2, 15.0))


def logs(model: str, n: int, seed: int) -> list[list[Card]]:
    rules = FRESH.with_deck(model)
    return [
        [parse_card(c) for c in cards]
        for cards, _ in generate_rounds(rules, Greedy(rules), n, seed)
    ]


def skewed_colour_logs(n: int, red_share: float, seed: int) -> list[list[Card]]:
    rng = random.Random(seed)
    red = [c for c in FULL_DECK if c.colour == "red"]
    black = [c for c in FULL_DECK if c.colour == "black"]
    out = []
    for _ in range(n):
        first = rng.choice(red if rng.random() < red_share else black)
        rest = rng.sample([c for c in FULL_DECK if c != first], 3)
        out.append([first, *rest[: rng.randint(0, 3)]])
    return out


def test_fresh_deck_logs_are_not_rejected() -> None:
    rep = verify(logs("fresh_52", 1000, seed=1), FRESH)
    assert rep.best is not None and rep.best.model == "fresh_52"
    assert not rep.flagged


def test_cards_repeat_logs_are_rejected_by_the_duplicate_test() -> None:
    rep = verify(logs("with_replacement", 300, seed=2), FRESH)
    flagged = {t.key for t in rep.flagged}
    assert "duplicates" in flagged
    assert rep.best is not None and rep.best.model != "fresh_52"
    fresh_fit = next(f for f in rep.models if f.model == "fresh_52")
    assert not fresh_fit.consistent


def test_colour_skew_is_flagged() -> None:
    rep = verify(skewed_colour_logs(1000, 0.6, seed=3), FRESH)
    assert "colour" in {t.key for t in rep.flagged}


def test_false_alarm_rate_on_fair_logs() -> None:
    alarms = 0
    for seed in range(200):
        rep = verify(logs("fresh_52", 250, seed=1000 + seed), FRESH)
        fresh_fit = next(f for f in rep.models if f.model == "fresh_52")
        alarms += bool(rep.flagged) or not fresh_fit.consistent
    assert alarms / 200 <= 0.08


def test_thirty_rounds_show_a_repeat_97_percent_of_the_time() -> None:
    assert 1 - no_duplicate_chance(4, "with_replacement", 1) ** 30 == pytest.approx(0.97, abs=0.005)
    assert 1 - no_duplicate_chance(4, "with_replacement", 1) == pytest.approx(0.111, abs=0.001)


def test_poisson_binomial_matches_binomial() -> None:
    assert poisson_binomial_cdf([0.1] * 40, 3) == pytest.approx(sps.binom.cdf(3, 40, 0.1))
    mixed = [0.1] * 20 + [0.3] * 10
    brute = 0.0
    for x in range(4):
        brute += sum(
            sps.binom.pmf(i, 20, 0.1) * sps.binom.pmf(x - i, 10, 0.3) for i in range(x + 1)
        )
    assert poisson_binomial_cdf(mixed, 3) == pytest.approx(brute)


def test_holm() -> None:
    assert holm([0.01, 0.04, None, 0.03]) == pytest.approx([0.03, 0.06, None, 0.06])  # type: ignore[arg-type]


def test_payout_check() -> None:
    ladder = (2.0, 2.7, 4.2, 15.0)
    ok = check_payouts([(1, 10.0, 20.0), (3, 10.0, 42.0), (3, 10.0, 27.0)], ladder)
    assert not ok.mismatches  # the last one matches stage 2 (a push, or extra cards shown)
    bad = check_payouts([(2, 10.0, 25.0)], ladder)
    assert len(bad.mismatches) == 1 and bad.mismatches[0].multiple == 2.5


def test_verify_handles_5000_rounds_in_under_two_seconds() -> None:
    rounds = logs("fresh_52", 5000, seed=9)
    started = time.perf_counter()
    verify(rounds, FRESH)
    assert time.perf_counter() - started < 2.0
