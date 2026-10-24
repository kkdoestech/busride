"""M2: the built-in games, checked three independent ways each.

1. Brute force over a short deck (every card sequence, with the obvious memo key: which cards
   are gone plus the cards later stages compare with), against the solver's compressed key.
2. Deep states on the full 52-card deck, against the same brute force.
3. The simulator, which deals and judges with its own code, within 4 standard errors.
"""

import random
from collections.abc import Callable
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from busride.engine.builtins import BUILTIN_GAMES, load_game, resolve_ladder
from busride.engine.cards import Card, remaining
from busride.engine.game import STAGE_KINDS, GameSpec, RulesError, make_stages
from busride.engine.policy import SolverStrategy
from busride.engine.rules import ACE_RULES, TIE_RULES
from busride.engine.solver import build_tree, solve, survival
from busride.engine.stages import Result, judge, state_key, survival_problem
from busride.sim import simulate

STATES = {"ride-the-bus": 329, "hi-lo-5": 28_237, "in-between": 183, "colour-run-5": 9}
DEFAULT_RTP = {
    "ride-the-bus": 0.9630,
    "hi-lo-5": 0.9618,
    "in-between": 0.9751,
    "colour-run-5": 0.9754,
}
SHORT_DECK = (2, 5, 9, 13)  # 16 cards: small enough to brute-force every sequence


def obvious_key(spec: GameSpec, seen: tuple[Card, ...]) -> tuple[object, ...]:
    """Which cards are gone, and the cards later stages compare with, by position."""
    later = sorted({r for s in spec.stages[len(seen) :] for r in s.refs if r < len(seen)})
    return (len(seen), tuple(sorted(seen)), tuple(seen[i] for i in later))


def brute(spec: GameSpec) -> tuple[Callable[[tuple[Card, ...]], float], Callable[..., list[float]]]:
    """Exact value and per-action values (every guess, then cash) by brute force."""
    memo: dict[tuple[object, ...], float] = {}

    def q_values(seen: tuple[Card, ...]) -> list[float]:
        k = len(seen)
        stage = spec.stages[k]
        pool = remaining(seen, spec.deck_model, spec.effective_decks, spec.ranks)
        total = sum(w for _, w in pool)
        survived = spec.guesses_before(k)
        cash = spec.cash_value(survived)
        out = []
        for guess in stage.guesses:
            ev = 0.0
            for card, w in pool:
                result = judge(stage.number, guess, seen, card, spec)[1]
                if result is Result.WIN:
                    ev += w * value((*seen, card))
                elif result is Result.PUSH:
                    ev += w * cash
            out.append(ev / total)
        return out

    def value(seen: tuple[Card, ...]) -> float:
        key = obvious_key(spec, seen)
        if key in memo:
            return memo[key]
        k = len(seen)
        if k == len(spec.stages):
            v = spec.cash_value(spec.guess_count)
        elif not spec.stages[k].is_guess:
            pool = remaining(seen, spec.deck_model, spec.effective_decks, spec.ranks)
            v = sum(w * value((*seen, c)) for c, w in pool) / sum(w for _, w in pool)
        else:
            best = max(q_values(seen))
            survived = spec.guesses_before(k)
            forced = survived == 0 and spec.forced_first_bet
            v = best if forced else max(spec.cash_value(survived), best)
        memo[key] = v
        return v

    return value, q_values


def random_live_state(spec: GameSpec, rng: random.Random, k: int) -> tuple[Card, ...]:
    while True:
        seen: list[Card] = []
        for _ in range(k):
            pool = remaining(seen, spec.deck_model, spec.effective_decks, spec.ranks)
            seen.append(rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0])
        if survival_problem(seen, spec) is None:
            return tuple(seen)


# ── the games themselves ─────────────────────────────────────────────────────────────────


def test_the_four_built_ins() -> None:
    assert list(BUILTIN_GAMES) == ["ride-the-bus", "hi-lo-5", "in-between", "colour-run-5"]
    for name, spec in BUILTIN_GAMES.items():
        assert spec.description, name
        assert load_game(name) is spec


@pytest.mark.parametrize("name", list(STATES))
def test_state_counts_stay_small(name: str) -> None:
    assert build_tree(BUILTIN_GAMES[name]).size == STATES[name]


@pytest.mark.parametrize("name", list(DEFAULT_RTP))
def test_default_ladders_have_a_small_house_edge(name: str) -> None:
    assert solve(BUILTIN_GAMES[name]).rtp == pytest.approx(DEFAULT_RTP[name], abs=1e-4)


# ── check 1: brute force on a short deck ─────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_short_deck_matches_brute_force(name: str) -> None:
    spec = replace(BUILTIN_GAMES[name], ranks=SHORT_DECK)
    sol = solve(spec)
    value, _ = brute(spec)
    assert sol.rtp == pytest.approx(value(()), abs=1e-12)
    rng = random.Random(1)
    for _ in range(60):
        seen = random_live_state(spec, rng, rng.randrange(len(spec.stages) + 1))
        assert sol.value(seen) == pytest.approx(value(seen), abs=1e-12), seen


# ── check 2: deep states on the full deck ────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_deep_states_on_the_full_deck(name: str) -> None:
    spec = BUILTIN_GAMES[name]
    sol = solve(spec)
    value, _ = brute(spec)
    rng = random.Random(2)
    n = len(spec.stages)
    for _ in range(30):
        seen = random_live_state(spec, rng, rng.randrange(max(0, n - 2), n + 1))
        assert sol.value(seen) == pytest.approx(value(seen), abs=1e-12), seen


# ── check 3: the independent simulator ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "rounds"),
    [
        ("ride-the-bus", 80_000),
        ("hi-lo-5", 60_000),
        ("in-between", 80_000),
        ("colour-run-5", 80_000),
    ],
)
def test_simulated_rtp_matches_exact(name: str, rounds: int) -> None:
    spec = BUILTIN_GAMES[name]
    sol = solve(spec)
    res = simulate(spec, SolverStrategy(sol), rounds, seed=11)
    assert abs(res.mean - sol.rtp) < 4 * res.se, (res.mean, sol.rtp, res.se)


def test_simulator_handles_an_optional_first_bet() -> None:
    spec = replace(BUILTIN_GAMES["in-between"], forced_first_bet=False)
    sol = solve(spec)
    res = simulate(spec, SolverStrategy(sol), 60_000, seed=5)
    assert res.declined > 0  # some spreads are not worth betting on
    assert abs(res.mean - sol.rtp) < 4 * res.se


# ── same key, same game: soundness of the compressed key ─────────────────────────────────


@st.composite
def small_specs(draw: st.DrawFn) -> GameSpec:
    n = draw(st.integers(1, 4))
    kinds: list[str] = []
    for i in range(n):
        allowed = [k for k in STAGE_KINDS if (k != "higher_lower" or i >= 1)]
        allowed = [k for k in allowed if (k != "inside_outside" or i >= 2)]
        kinds.append(draw(st.sampled_from(allowed)))
    if all(k == "reveal" for k in kinds):
        kinds[-1] = "colour"
    model, decks = draw(st.sampled_from([("fresh_52", 1), ("with_replacement", 1), ("shoe", 2)]))
    stages = make_stages(kinds)
    guesses = sum(1 for k in kinds if k != "reveal")
    return GameSpec(
        stages=stages,
        deck_model=model,
        decks=decks,
        ace=draw(st.sampled_from(ACE_RULES)),
        tie_higher_lower=draw(st.sampled_from(TIE_RULES)),
        tie_range_edge=draw(st.sampled_from(TIE_RULES)),
        returns=tuple(draw(st.floats(0.5, 30)) for _ in range(guesses)),
        forced_first_bet=draw(st.booleans()),
        ranks=tuple(sorted(draw(st.sets(st.sampled_from(range(2, 15)), min_size=3, max_size=5)))),
    )


@settings(max_examples=150, deadline=None)
@given(small_specs(), st.integers(0, 10**6))
def test_states_with_the_same_key_play_the_same(spec: GameSpec, seed: int) -> None:
    value, q_values = brute(spec)
    rng = random.Random(seed)
    groups: dict[tuple[object, ...], list[tuple[Card, ...]]] = {}
    for _ in range(25):
        seen = random_live_state(spec, rng, rng.randrange(len(spec.stages) + 1))
        groups.setdefault(state_key(spec, seen), []).append(seen)
    for members in groups.values():
        first = members[0]
        for other in members[1:]:
            assert value(other) == pytest.approx(value(first), abs=1e-9)
            k = len(first)
            if k < len(spec.stages) and spec.stages[k].is_guess:
                # the same values, possibly under different suit or colour names
                assert sorted(q_values(other)) == pytest.approx(sorted(q_values(first)), abs=1e-9)


# ── loading games and ladders ────────────────────────────────────────────────────────────


def test_unknown_game_lists_the_built_ins() -> None:
    with pytest.raises(RulesError, match="hi-lo-5"):
        load_game("poker")


def test_ladder_presets() -> None:
    rtb = BUILTIN_GAMES["ride-the-bus"]
    assert resolve_ladder("classic", rtb) == (2.0, 3.0, 4.0, 20.0)
    assert resolve_ladder("house", rtb) == rtb.returns
    fair = resolve_ladder("fair", rtb)
    assert fair == pytest.approx(tuple(1 / s for s in survival(rtb)))
    assert resolve_ladder("1.2 1.6 2.2 3 4.2", BUILTIN_GAMES["hi-lo-5"]) == (
        1.2,
        1.6,
        2.2,
        3.0,
        4.2,
    )
    with pytest.raises(RulesError, match="5 returns"):
        resolve_ladder("2,3,4,20", BUILTIN_GAMES["hi-lo-5"])
    with pytest.raises(RulesError, match="classic"):
        resolve_ladder("classic", BUILTIN_GAMES["hi-lo-5"])
