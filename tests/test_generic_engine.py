"""M1: the generic engine reproduces the original Ride the Bus solver exactly, and handles custom
stage lists, reveal stages, the optional first bet and the state budget."""

import random
from collections.abc import Callable
from dataclasses import replace
from functools import cache

import pytest

from busride.engine.cards import Card, remaining
from busride.engine.game import GameSpec, RulesError, make_stages
from busride.engine.rules import Rules
from busride.engine.solver import GameTooBig, build_tree, fixed_plan, solve, survival
from busride.engine.stages import Result, judge, state_key

from .legacy_rtb import legacy_solve

HOUSE = Rules(returns=(1.8, 2.3, 3.2, 12.0))
VARIANTS = [
    HOUSE,
    Rules(returns=(2.0, 3.0, 4.0, 20.0)),
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
    Rules(deck_model="shoe", decks=6, tie_range_edge="push", returns=(1.9, 2.6, 3.9, 14.0)),
]


# ── the original solver as an oracle ─────────────────────────────────────────────────────


@pytest.mark.parametrize("rules", VARIANTS)
def test_reproduces_the_original_solver_state_by_state(rules: Rules) -> None:
    values, reps = legacy_solve(rules)
    sol = solve(rules)
    for k, level in enumerate(reps):
        for key, seen in level.items():
            assert sol.value(seen) == pytest.approx(values[k][key], abs=1e-12), (k, seen)
    assert sol.rtp == pytest.approx(values[0][()], abs=1e-12)


def test_state_counts_match_the_hand_written_key() -> None:
    tree = build_tree(Rules())
    assert [len(level) for level in tree.levels] == [1, 13, 312, 3]
    assert tree.size == 329
    assert build_tree(Rules(deck_model="with_replacement")).size == 171


def test_house_ladder_has_a_small_house_edge() -> None:
    assert solve(HOUSE).rtp == pytest.approx(0.963, abs=0.0005)


# ── the canonical key ────────────────────────────────────────────────────────────────────


def cards(text: str) -> tuple[Card, ...]:
    from busride.engine.cards import parse_cards

    return tuple(parse_cards(text))


def test_key_ignores_which_suit_is_which() -> None:
    rules = Rules()
    assert state_key(rules, cards("9h Ks")) == state_key(rules, cards("9d Kc"))
    assert state_key(rules, cards("9h Kh")) == state_key(rules, cards("9s Ks"))
    assert state_key(rules, cards("9h Ks")) != state_key(rules, cards("9h Kh"))
    assert state_key(rules, cards("9h Ks")) != state_key(rules, cards("Kh 9s"))  # order matters
    # only the suits matter before the suit question
    assert state_key(rules, cards("2h 9s 5d")) == state_key(rules, cards("Ac 3h Qs"))


def test_key_keeps_colour_when_a_colour_question_is_still_to_come() -> None:
    spec = GameSpec(stages=make_stages(["suit", "colour"]), returns=(3.5, 6.5))
    # after the suit question only colour matters, and red and black are interchangeable
    assert state_key(spec, cards("9h")) == state_key(spec, cards("2s"))
    spec2 = GameSpec(
        stages=make_stages(["colour", "colour", "suit", "colour"]), returns=(1.9, 3.6, 13.0, 25.0)
    )
    # a suit question and a colour question both lie ahead: two different red suits look like
    # two different black suits, but not like one red and one black
    assert state_key(spec2, cards("9h 2d")) == state_key(spec2, cards("Kc 4s"))
    assert state_key(spec2, cards("9h 2d")) != state_key(spec2, cards("9h 2s"))


def test_key_stores_ranks_not_ace_values() -> None:
    either = Rules(ace="either")
    assert state_key(either, cards("Ah")) != state_key(either, cards("2h"))


# ── any list of stages, checked against brute force ──────────────────────────────────────


def brute_value(spec: GameSpec) -> Callable[[tuple[Card, ...]], float]:
    """Exact values by brute force over whole card sequences: no keys, no grouping."""

    @cache
    def value(seen: tuple[Card, ...]) -> float:
        k = len(seen)
        if k == len(spec.stages):
            return spec.cash_value(spec.guess_count)
        stage = spec.stages[k]
        pool = remaining(seen, spec.deck_model, spec.effective_decks)
        total = sum(w for _, w in pool)
        if not stage.is_guess:
            return sum(w * value((*seen, c)) for c, w in pool) / total
        survived = spec.guesses_before(k)
        cash = spec.cash_value(survived)
        best = 0.0
        for guess in stage.guesses:
            ev = 0.0
            for card, w in pool:
                result = judge(stage.number, guess, seen, card, spec)[1]
                if result is Result.WIN:
                    ev += w * value((*seen, card))
                elif result is Result.PUSH:
                    ev += w * cash
            best = max(best, ev / total)
        if survived == 0 and spec.forced_first_bet:
            return best
        return max(cash, best)

    return value


SMALL_GAMES = [
    GameSpec(stages=make_stages(["colour", "colour"]), returns=(1.9, 3.7)),
    GameSpec(stages=make_stages(["colour", "higher_lower"]), returns=(1.9, 2.6)),
    GameSpec(stages=make_stages(["suit", "colour"]), returns=(3.8, 7.0), forced_first_bet=False),
    GameSpec(
        stages=make_stages(["reveal", "higher_lower", "higher_lower"]),
        returns=(1.3, 1.8),
        forced_first_bet=False,
    ),
    GameSpec(
        stages=make_stages(["reveal", "reveal", "inside_outside"]),
        returns=(2.1,),
        forced_first_bet=False,
        tie_range_edge="push",
    ),
    GameSpec(
        stages=make_stages(["reveal", "higher_lower", "suit"]),
        returns=(1.4, 5.0),
        deck_model="with_replacement",
        ace="either",
        tie_higher_lower="push",
    ),
    GameSpec(
        stages=make_stages(["colour", "suit", "colour"]),
        returns=(1.9, 7.0, 13.0),
        deck_model="shoe",
        decks=2,
    ),
]


@pytest.mark.parametrize("spec", SMALL_GAMES, ids=lambda s: "+".join(st.kind for st in s.stages))
def test_custom_games_match_brute_force(spec: GameSpec) -> None:
    sol = solve(spec)
    brute = brute_value(spec)
    assert sol.rtp == pytest.approx(brute(()), abs=1e-12)
    rng = random.Random(3)
    for _ in range(40):
        k = rng.randrange(len(spec.stages) + 1)
        seen: list[Card] = []
        while len(seen) < k:
            pool = remaining(seen, spec.deck_model, spec.effective_decks)
            seen.append(rng.choices([c for c, _ in pool], weights=[w for _, w in pool])[0])
        key = state_key(spec, seen)
        if key in sol.values[k]:  # states the player can't reach (e.g. after a tie) have no value
            assert sol.value(seen) == pytest.approx(brute(tuple(seen)), abs=1e-12), seen


def test_reveal_stages_do_not_move_the_ladder() -> None:
    spec = SMALL_GAMES[3]  # reveal, higher/lower, higher/lower
    assert spec.guess_count == 2
    assert [spec.guesses_before(k) for k in range(4)] == [0, 0, 1, 2]
    best, greedy = survival(spec), fixed_plan(spec).reach
    assert len(best) == len(greedy) == 2
    assert greedy[0] == pytest.approx(best[0], abs=1e-12)
    assert greedy[1] <= best[1] + 1e-12  # guessing greedily can't beat the best plan


# ── the first bet ────────────────────────────────────────────────────────────────────────


def test_an_optional_first_bet_can_be_declined() -> None:
    free = replace(HOUSE, forced_first_bet=False)
    assert solve(free).rtp == 1.0  # with a house edge, keeping the stake is best
    rich = Rules(returns=(2.0, 3.0, 4.0, 20.0))
    assert solve(replace(rich, forced_first_bet=False)).rtp == pytest.approx(solve(rich).rtp)
    assert survival(free) == pytest.approx(survival(HOUSE))


# ── validation and the state budget ─────────────────────────────────────────────────────


def test_ladder_must_fit_the_stages() -> None:
    with pytest.raises(RulesError, match="2 guessing stages"):
        GameSpec(stages=make_stages(["colour", "suit"]), returns=(1.9, 7.0, 13.0))
    with pytest.raises(RulesError, match="earlier card"):
        make_stages(["higher_lower", "colour"])
    with pytest.raises(RulesError, match="stage type"):
        make_stages(["colour", "pair"])


def test_games_too_big_to_solve_say_so() -> None:
    with pytest.raises(GameTooBig, match="too many"):
        build_tree(Rules(), budget=100)


def test_rules_is_the_game_spec() -> None:
    assert Rules is GameSpec
    assert Rules().guess_count == 4
    assert [s.kind for s in Rules().stages] == ["colour", "higher_lower", "inside_outside", "suit"]
