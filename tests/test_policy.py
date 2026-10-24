"""Policy self-consistency, checked against a brute-force solver that skips the state
compression and memoises on the exact cards seen."""

import random
from functools import cache

import pytest

from busride.engine.cards import Card, remaining
from busride.engine.policy import AdviceError, SolverStrategy, advise, cheatsheet
from busride.engine.rules import Rules
from busride.engine.solver import solve
from busride.engine.stages import STAGES, Result, judge, state_key, survival_problem

ODD_RULES = [
    Rules(returns=(1.9, 2.6, 3.9, 14.0)),
    Rules(deck_model="with_replacement", returns=(1.5, 3.0, 4.0, 20.0)),
    Rules(
        deck_model="shoe",
        decks=2,
        ace="either",
        tie_higher_lower="push",
        tie_range_edge="win",
        returns=(1.8, 2.4, 4.4, 16.0),
    ),
    Rules(ace="low", tie_higher_lower="win", tie_range_edge="push", returns=(2.0, 2.2, 3.0, 9.0)),
]


def brute_value(rules: Rules):  # type: ignore[no-untyped-def]
    @cache
    def value(seen: tuple[Card, ...]) -> float:
        k = len(seen)
        if k == 4:
            return rules.returns[3]
        pool = remaining(seen, rules.deck_model, rules.effective_decks)
        total = sum(w for _, w in pool)
        best = 0.0
        for guess in STAGES[k].guesses:
            ev = 0.0
            for card, w in pool:
                result = judge(k + 1, guess, seen, card, rules)[1]
                if result is Result.WIN:
                    ev += w * value((*seen, card))
                elif result is Result.PUSH:
                    ev += w * rules.cash_value(k)
            best = max(best, ev / total)
        return best if k == 0 else max(rules.cash_value(k), best)

    return value


def _random_live(rules: Rules, rng: random.Random, k: int) -> tuple[Card, ...]:
    seen: list[Card] = []
    while len(seen) < k:
        pool = remaining(seen, rules.deck_model, rules.effective_decks)
        card = rng.choice([c for c, _ in pool])
        if survival_problem([*seen, card], rules) is None:
            seen.append(card)
    return tuple(seen)


@pytest.mark.parametrize("rules", ODD_RULES)
def test_compressed_solver_matches_brute_force(rules: Rules) -> None:
    sol = solve(rules)
    brute = brute_value(rules)
    rng = random.Random(7)
    for k, count in ((3, 20), (2, 25), (1, 2)):
        for _ in range(count):
            seen = _random_live(rules, rng, k)
            assert sol.value(seen) == pytest.approx(brute(seen), abs=1e-12)


@pytest.mark.parametrize("rules", ODD_RULES)
def test_policy_never_continues_below_cash_out(rules: Rules) -> None:
    sol = solve(rules)
    rng = random.Random(11)
    for _ in range(300):
        seen = _random_live(rules, rng, rng.randint(1, 3))
        d = advise(sol, seen)
        assert d.should_continue == (d.continue_value > d.cash_out)
        assert sol.value(seen) == pytest.approx(max(d.cash_out, d.continue_value))
        strategy = SolverStrategy(sol)
        choice = strategy.choose(len(seen) + 1, [str(c) for c in seen])
        assert (choice is not None) == d.should_continue
        if choice is not None:
            # the strategy's guess is worth as much as the best one
            ev = {o.guess: o.ev for o in d.options}
            assert ev[choice] == pytest.approx(d.continue_value)
        assert state_key(rules, seen) in sol.values[len(seen)]


def test_advise_rejects_impossible_rounds() -> None:
    sol = solve(Rules(returns=(2, 3, 4, 15)))
    with pytest.raises(AdviceError, match="tie"):
        advise(sol, [Card(9, "h"), Card(9, "s")])
    with pytest.raises(AdviceError, match="already on the table"):
        advise(sol, [Card(9, "h"), Card(9, "h")])
    with pytest.raises(AdviceError, match="over"):
        advise(sol, [Card(2, "h"), Card(9, "s"), Card(5, "d"), Card(7, "c")])


def test_cheat_sheet_covers_every_situation(fair_rules: Rules) -> None:
    sheet = cheatsheet(solve(fair_rules))
    assert [s.layout for s in sheet] == ["first", "strip", "grid", "pattern"]
    assert [s.index for s in sheet] == [1, 2, 3, 4]
    s2 = sheet[1].cells
    assert set(s2) == set(range(2, 15))
    assert s2[2].guess == "higher" and s2[14].guess == "lower"
    assert s2[2].should_continue and s2[2].unanimous
    s3 = sheet[2].cells
    assert len(s3) == 13 * 12  # equal ranks tie on stage 2, which ends the round
    assert all((r, r) not in s3 for r in range(2, 15))
    patterns = sheet[3].cells
    assert set(patterns) == {(1, 1, 1, 0), (2, 1, 0, 0), (3, 0, 0, 0)}
    assert {c.guess for c in patterns.values()} == {"least"}
    assert sheet[0].cash_value is None  # the first bet can't be refused once placed
