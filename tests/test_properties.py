"""Properties that must hold for any rule set (Hypothesis, 1,000 random rule sets each)."""

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from busride.engine.cards import Card, remaining
from busride.engine.rules import ACE_RULES, TIE_RULES, Rules
from busride.engine.solver import decide, solve
from busride.engine.stages import survival_problem

ladders = st.tuples(*[st.floats(0, 40, allow_nan=False) for _ in range(4)])
decks = st.sampled_from([("fresh_52", 1), ("with_replacement", 1), ("shoe", 2), ("shoe", 6)])


@st.composite
def rule_sets(draw: st.DrawFn) -> Rules:
    model, n = draw(decks)
    return Rules(
        deck_model=model,
        decks=n,
        ace=draw(st.sampled_from(ACE_RULES)),
        tie_higher_lower=draw(st.sampled_from(TIE_RULES)),
        tie_range_edge=draw(st.sampled_from(TIE_RULES)),
        returns=draw(ladders),
    )


def _live_state(rules: Rules, seed: int, length: int) -> list[Card]:
    """A random sequence of cards the player could have survived."""
    rng = random.Random(seed)
    seen: list[Card] = []
    while len(seen) < length:
        pool = remaining(seen, rules.deck_model, rules.effective_decks)
        card = rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0]
        if survival_problem([*seen, card], rules) is None:
            seen.append(card)
    return seen


@settings(max_examples=1000, deadline=None)
@given(rule_sets(), st.integers(0, 10**6), st.integers(0, 3))
def test_win_lose_tie_partition_the_remaining_deck(rules: Rules, seed: int, k: int) -> None:
    seen = _live_state(rules, seed, k)
    total = sum(w for _, w in remaining(seen, rules.deck_model, rules.effective_decks))
    for opt in decide(solve(rules), seen).options:
        assert opt.wins + opt.losses + opt.ties == opt.total == total
        assert 0 <= opt.pushes <= opt.ties


@settings(max_examples=1000, deadline=None)
@given(rule_sets())
def test_value_never_below_cashing_out(rules: Rules) -> None:
    sol = solve(rules)
    for k in (1, 2, 3):
        cash = rules.returns[k - 1]
        assert all(v >= cash for v in sol.values[k].values())


@settings(max_examples=1000, deadline=None)
@given(rule_sets(), st.integers(0, 3), st.floats(0.001, 10))
def test_raising_a_payout_never_lowers_rtp(rules: Rules, stage: int, bump: float) -> None:
    higher = list(rules.returns)
    higher[stage] += bump
    assert solve(rules.with_returns(tuple(higher))).rtp >= solve(rules).rtp - 1e-12  # type: ignore[arg-type]


@settings(max_examples=200, deadline=None)
@given(rule_sets(), st.floats(0.1, 5))
def test_scaling_the_ladder_scales_the_rtp(rules: Rules, factor: float) -> None:
    scaled = tuple(r * factor for r in rules.returns)
    assert abs(solve(rules.with_returns(scaled)).rtp - factor * solve(rules).rtp) < 1e-9 * (
        1 + factor
    )  # type: ignore[arg-type]
