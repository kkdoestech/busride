"""The simulator shares no code with the solver; agreement inside 4 standard errors, with fixed
seeds, is the cross-check."""

import math

import pytest

from busride.engine.policy import SolverStrategy
from busride.engine.rules import Rules
from busride.engine.solver import fixed_plan, solve
from busride.sim import CARD_NAMES, Greedy, Table, generate_rounds, simulate

ROUNDS = 150_000


@pytest.mark.parametrize("model", ["fresh_52", "with_replacement"])
def test_greedy_survival_matches_exact(base_rules: Rules, model: str) -> None:
    rules = base_rules.with_deck(model)
    exact = fixed_plan(rules).reach
    res = simulate(rules, Greedy(rules), ROUNDS, seed=2026)
    for k in range(1, 5):
        p, se = res.reach_rate(k)
        assert abs(p - exact[k - 1]) < 4 * se, (k, p, exact[k - 1])


@pytest.mark.parametrize(
    "rules",
    [
        Rules(returns=(2.0, 2.7625, 4.2068, 15.855)),
        Rules(
            deck_model="shoe",
            decks=2,
            ace="either",
            tie_higher_lower="push",
            tie_range_edge="win",
            returns=(1.8, 2.4, 4.4, 16.0),
        ),
        Rules(
            ace="low", tie_higher_lower="win", tie_range_edge="push", returns=(1.9, 2.2, 3.0, 9.0)
        ),
    ],
)
def test_optimal_rtp_matches_exact(rules: Rules) -> None:
    sol = solve(rules)
    res = simulate(rules, SolverStrategy(sol), ROUNDS, seed=42)
    assert abs(res.mean - sol.rtp) < 4 * res.se, (res.mean, sol.rtp, res.se)


def test_fixed_plan_value_matches(base_rules: Rules) -> None:
    rules = base_rules.with_returns((1.9, 2.5, 3.8, 14.0))
    plan = fixed_plan(rules, 2)
    res = simulate(rules, Greedy(rules, 2), ROUNDS, seed=7)
    assert abs(res.mean - plan.value) < 4 * res.se


def test_simulator_reads_cards_its_own_way() -> None:
    assert CARD_NAMES[0] == "2h" and CARD_NAMES[51] == "As" and len(set(CARD_NAMES)) == 52
    table = Table(Rules(ace="either"))
    ace, nine = CARD_NAMES.index("Ah"), CARD_NAMES.index("9s")
    # position 1 (0-based) is Ride the Bus's higher-or-lower stage
    assert table.outcome(1, "higher", [nine], ace) == "win"
    assert table.outcome(1, "lower", [nine], ace) == "win"


def test_same_seed_same_result(base_rules: Rules) -> None:
    a = simulate(base_rules, Greedy(base_rules), 2000, seed=5)
    b = simulate(base_rules, Greedy(base_rules), 2000, seed=5)
    assert (a.total, a.reached) == (b.total, b.reached)
    assert math.isclose(a.mean, b.mean)


def test_generated_logs_show_cards_in_order(base_rules: Rules) -> None:
    logs = generate_rounds(base_rules.with_returns((2, 3, 4, 15)), Greedy(base_rules), 300, seed=1)
    assert len(logs) == 300
    assert all(1 <= len(cards) <= 4 for cards, _ in logs)
    assert all(len(set(cards)) == len(cards) for cards, _ in logs)  # a fresh deck never repeats
