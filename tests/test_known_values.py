"""The four exact values from the spec, plus the cards-repeat and fair-ladder regressions."""

import time

import pytest

from busride.engine.cards import parse_cards
from busride.engine.rules import Rules
from busride.engine.solver import clear_cache, decide, fixed_plan, solve, survival

FRESH = (0.50000, 0.36199, 0.23771, 0.06307)
REPEAT = (0.50000, 0.35503, 0.22417, 0.05604)


def test_survival_fresh_deck(base_rules: Rules) -> None:
    assert survival(base_rules) == pytest.approx(FRESH, abs=1e-5)


def test_survival_cards_repeat(base_rules: Rules) -> None:
    assert survival(base_rules.with_deck("with_replacement")) == pytest.approx(REPEAT, abs=1e-5)


def test_fair_ladder_rtp(fair_rules: Rules) -> None:
    assert solve(fair_rules).rtp == pytest.approx(1.146, abs=0.002)


def test_greedy_guessing_reaches_the_same_odds(base_rules: Rules) -> None:
    assert fixed_plan(base_rules).reach == pytest.approx(survival(base_rules), abs=1e-12)


def test_stage_four_is_least_seen_suit(fair_rules: Rules) -> None:
    best = decide(solve(fair_rules), parse_cards("2h 5s 9d")).best
    assert (best.wins, best.total) == (13, 49)
    assert best.guess == "clubs"


def test_advisor_counts_for_nine_then_king(fair_rules: Rules) -> None:
    d = decide(solve(fair_rules), parse_cards("9h Ks"))
    by_guess = {o.guess: o for o in d.options}
    assert (by_guess["outside"].wins, by_guess["outside"].total) == (32, 50)
    assert (by_guess["inside"].wins, by_guess["inside"].ties) == (12, 6)
    assert d.best.guess == "outside"


def test_first_card_two_says_higher(fair_rules: Rules) -> None:
    d = decide(solve(fair_rules), parse_cards("2c"))
    assert (d.best.guess, d.best.wins, d.best.total) == ("higher", 48, 51)


def test_full_solve_under_one_second(fair_rules: Rules) -> None:
    clear_cache()
    started = time.perf_counter()
    solve(fair_rules)
    survival(fair_rules)
    assert time.perf_counter() - started < 1.0
