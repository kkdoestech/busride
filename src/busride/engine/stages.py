"""Stage logic: whether a guess wins, loses or ties on a card, and the solver's state key."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from busride.engine.cards import RED_SUITS, SUITS, Card, deal_conflict
from busride.engine.game import RANK_STAGES, RIDE_THE_BUS, GameSpec, Stage

# The stages of the default game, for screens that only describe Ride the Bus.
STAGES = RIDE_THE_BUS
SUIT_OF_GUESS = {"hearts": "h", "diamonds": "d", "clubs": "c", "spades": "s"}


class Outcome(StrEnum):
    """What the card did to the guess, before the tie rule is applied."""

    WIN = "win"
    LOSE = "lose"
    TIE = "tie"


class Result(StrEnum):
    """What happens to the round."""

    WIN = "win"
    LOSE = "lose"
    PUSH = "push"  # the round ends and pays the current cash-out value


_PLAYER_PREFERS = {Result.LOSE: 0, Result.PUSH: 1, Result.WIN: 2}


def ace_values(ace: str) -> tuple[int, ...]:
    """The values an ace can take. With "either", the player gets whichever helps."""
    return {"high": (14,), "low": (1,), "either": (14, 1)}[ace]


def _value(rank: int, ace_value: int) -> int:
    return ace_value if rank == 14 else rank


def raw_outcome(
    stage: Stage, guess: str, seen: Sequence[Card], card: Card, ace_value: int
) -> Outcome:
    """Win, lose or tie for one guess on one card, with aces worth `ace_value`."""
    if stage.kind == "colour":
        return Outcome.WIN if card.colour == guess else Outcome.LOSE
    if stage.kind == "suit":
        return Outcome.WIN if card.suit == SUIT_OF_GUESS[guess] else Outcome.LOSE
    v = _value(card.rank, ace_value)
    if stage.kind == "higher_lower":
        ref = _value(seen[stage.refs[0]].rank, ace_value)
        if v == ref:
            return Outcome.TIE
        return Outcome.WIN if (v > ref) == (guess == "higher") else Outcome.LOSE
    if stage.kind == "inside_outside":
        lo, hi = sorted(_value(seen[i].rank, ace_value) for i in stage.refs)
        if v in (lo, hi):
            return Outcome.TIE
        return Outcome.WIN if (lo < v < hi) == (guess == "inside") else Outcome.LOSE
    raise ValueError(f"no guess is made at a {stage.kind} stage")


def tie_result(stage: Stage, rules: GameSpec) -> Result:
    return Result(rules.tie_higher_lower if stage.kind == "higher_lower" else rules.tie_range_edge)


def judge(
    stage_number: int, guess: str, seen: Sequence[Card], card: Card, rules: GameSpec
) -> tuple[Outcome, Result]:
    """The raw outcome and its effect on the round, under the game's ace and tie settings."""
    stage = rules.stages[stage_number - 1]
    if stage.kind not in RANK_STAGES:
        raw = raw_outcome(stage, guess, seen, card, 14)
        return raw, Result.WIN if raw is Outcome.WIN else Result.LOSE
    best: tuple[Outcome, Result] | None = None
    for ace_value in ace_values(rules.ace):
        raw = raw_outcome(stage, guess, seen, card, ace_value)
        if raw is Outcome.TIE:
            res = tie_result(stage, rules)
        else:
            res = Result.WIN if raw is Outcome.WIN else Result.LOSE
        if best is None or _PLAYER_PREFERS[res] > _PLAYER_PREFERS[best[1]]:
            best = (raw, res)
    assert best is not None
    return best


# ── the state key ────────────────────────────────────────────────────────────────────────


def projection(rules: GameSpec, k: int) -> tuple[bool, str, tuple[int, ...]]:
    """What the stages from k on can still use from the cards already seen (see
    GameSpec.projections)."""
    return rules.projections[k]


def cell(card: Card, needs_rank: bool, mode: str) -> tuple[int, str]:
    """The part of a card the remaining stages can tell apart."""
    rank = card.rank if needs_rank else 0
    if mode in ("suit", "suit+colour"):
        return rank, card.suit
    if mode == "colour":
        return rank, card.colour
    return rank, ""


def _profile(cards: list[Card], needs_rank: bool) -> tuple[int, ...]:
    return tuple(sorted(c.rank for c in cards)) if needs_rank else (len(cards),)


def _composition(seen: Sequence[Card], needs_rank: bool, mode: str) -> tuple[object, ...]:
    """The cards seen, as a multiset of what still matters, up to the allowed suit symmetries.

    Suits that no remaining stage tells apart are interchangeable, so each group's cards are
    summarised by a profile and the profiles are sorted:
      "suit":        all 4 suits interchangeable
      "suit+colour": hearts<->diamonds, clubs<->spades, and red<->black
      "colour":      red<->black
    """
    if mode == "":
        return tuple(sorted(c.rank for c in seen)) if needs_rank else ()
    if mode == "colour":
        red = _profile([c for c in seen if c.suit in RED_SUITS], needs_rank)
        black = _profile([c for c in seen if c.suit not in RED_SUITS], needs_rank)
        return tuple(sorted((red, black)))
    by_suit = {s: _profile([c for c in seen if c.suit == s], needs_rank) for s in SUITS}
    if mode == "suit":
        return tuple(sorted(by_suit.values()))
    red_pair = tuple(sorted((by_suit["h"], by_suit["d"])))
    black_pair = tuple(sorted((by_suit["c"], by_suit["s"])))
    return tuple(sorted((red_pair, black_pair)))


def state_key(rules: GameSpec, seen: Sequence[Card]) -> tuple[object, ...]:
    """The part of the cards seen that the rest of the round can depend on.

    (cards seen, ranks of the cards later stages compare with, what is left in the deck). Two
    sequences with the same key have the same value and the same best play, so the solver only
    visits a few hundred states in Ride the Bus.
    """
    k = len(seen)
    needs_rank, mode, refs = projection(rules, k)
    ranks = tuple(seen[i].rank for i in refs)
    if not seen or rules.deck_model == "with_replacement":
        return (k, ranks, ())
    return (k, ranks, _composition(seen, needs_rank, mode))


def survival_problem(seen: Sequence[Card], rules: GameSpec) -> str | None:
    """Why these cards could not all have been survived, or None if they could."""
    if len(seen) > len(rules.stages):
        return f"a round has at most {len(rules.stages)} cards"
    clash = deal_conflict(seen, rules.deck_model, rules.effective_decks)
    if clash is not None:
        return (
            f"{clash} is already on the table this round, and your deck model does not repeat cards"
        )
    for k, card in enumerate(seen):
        stage = rules.stages[k]
        if not stage.is_guess:
            continue
        results = {judge(stage.number, g, seen[:k], card, rules)[1] for g in stage.guesses}
        if Result.WIN in results:
            continue
        ends = "pushes, which ends the round" if Result.PUSH in results else "loses"
        if stage.kind == "higher_lower":
            ref = stage.refs[0]
            which = "the first card" if ref == 0 else "the previous card"
            return f"{card} ties {which} {seen[ref]}; under your rules a tie {ends}"
        if stage.kind == "inside_outside":
            a, b = (seen[i] for i in stage.refs)
            return f"{card} sits on the edge of the {a}-{b} range; an edge tie {ends}"
        return f"no guess survives {card} at stage {stage.number}"
    return None
