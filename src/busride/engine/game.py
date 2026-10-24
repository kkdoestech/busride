"""What a game is: its stages, deck, ace and tie rules, and payout ladder.

A game is a sequence of stages, one card each. A guessing stage asks a question about its card;
a reveal stage just shows a card. The ladder has one return per guessing stage: the total paid
per 1 staked, stake included, for cashing out after surviving that many guessing stages.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cached_property

from busride.engine.cards import RANKS

STAGE_KINDS = ("colour", "higher_lower", "inside_outside", "suit", "reveal")
GUESSES = {
    "colour": ("red", "black"),
    "higher_lower": ("higher", "lower"),
    "inside_outside": ("inside", "outside"),
    "suit": ("hearts", "diamonds", "clubs", "spades"),
    "reveal": (),
}
QUESTIONS = {
    "colour": "Red or black",
    "higher_lower": "Higher or lower",
    "inside_outside": "Inside or outside",
    "suit": "Suit",
    "reveal": "Card shown",
}
RANK_STAGES = frozenset({"higher_lower", "inside_outside"})
_CARDS_COMPARED = {"higher_lower": 1, "inside_outside": 2}
_SUIT_MODE = {
    (True, True): "suit+colour",
    (True, False): "suit",
    (False, True): "colour",
    (False, False): "",
}


class RulesError(ValueError):
    """A game definition or rules file the engine cannot use. The message names what to fix."""


@dataclass(frozen=True)
class Stage:
    kind: str
    number: int  # position in the game, from 1
    refs: tuple[int, ...] = ()  # 0-based positions of the earlier cards it compares with

    @property
    def question(self) -> str:
        return QUESTIONS[self.kind]

    @property
    def guesses(self) -> tuple[str, ...]:
        return GUESSES[self.kind]

    @property
    def is_guess(self) -> bool:
        return self.kind != "reveal"


def make_stages(kinds: Sequence[str | tuple[str, Sequence[int]]]) -> tuple[Stage, ...]:
    """Stages from their types. higher_lower compares with the previous card and inside_outside
    with the two previous cards, unless given as (type, [1-based stage numbers])."""
    stages = []
    for i, item in enumerate(kinds):
        kind, numbers = (item, None) if isinstance(item, str) else (item[0], item[1])
        if kind not in STAGE_KINDS:
            raise RulesError(
                f"stage {i + 1}: unknown stage type {kind!r}; use one of {', '.join(STAGE_KINDS)}"
            )
        need = _CARDS_COMPARED.get(kind, 0)
        refs = tuple(range(i - need, i)) if numbers is None else tuple(int(n) - 1 for n in numbers)
        if len(refs) != need or any(r < 0 or r >= i for r in refs):
            cards = "card" if need == 1 else "cards"
            raise RulesError(f"stage {i + 1} ({kind}) needs {need} earlier {cards} to compare with")
        stages.append(Stage(kind, i + 1, refs))
    if not any(s.is_guess for s in stages):
        raise RulesError("a game needs at least one guessing stage")
    return tuple(stages)


RIDE_THE_BUS = make_stages(["colour", "higher_lower", "inside_outside", "suit"])
PLACEHOLDER_VERSION = "fill in"


@dataclass(frozen=True)
class GameSpec:
    """Everything the solver and simulator need to know about a game.

    A tie that "pushes" ends the round and pays the current cash-out value.
    """

    name: str = "Ride the Bus"
    game_version: str = PLACEHOLDER_VERSION
    captured_on: str = ""
    deck_model: str = "fresh_52"
    decks: int = 1
    ace: str = "high"
    tie_higher_lower: str = "lose"
    tie_range_edge: str = "lose"
    returns: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    min_stake: float | None = None
    max_stake: float | None = None
    timeout: str = "unknown"
    source: str = "built-in defaults"
    unknown_keys: tuple[str, ...] = ()
    stages: tuple[Stage, ...] = RIDE_THE_BUS
    forced_first_bet: bool = True  # the first guess must be played: no walking away
    ranks: tuple[int, ...] = RANKS  # ranks in the deck (a short deck drops some)
    description: str = ""

    def __post_init__(self) -> None:
        if len(self.returns) != self.guess_count:
            raise RulesError(
                f"the ladder has {len(self.returns)} returns but the game has "
                f"{self.guess_count} guessing stages: give one return per guessing stage"
            )
        if not self.ranks or any(r not in RANKS for r in self.ranks):
            raise RulesError("the deck's ranks must be a non-empty set of 2..14 (14 = ace)")
        if len(self.stages) > len(self.ranks) * 4 * self.effective_decks and (
            self.deck_model != "with_replacement"
        ):
            raise RulesError("the game deals more cards than the deck holds")

    @cached_property
    def projections(self) -> tuple[tuple[bool, str, tuple[int, ...]], ...]:
        """For k = 0..len(stages): what the stages from k on can still use from cards seen.

        (ranks needed, suit mode, positions of cards compared with later). The suit mode is
        "suit+colour", "suit", "colour" or "" and fixes which relabellings of suits change
        nothing for the rest of the round.
        """
        out = []
        for k in range(len(self.stages) + 1):
            rest = self.stages[k:]
            needs_rank = any(s.kind in RANK_STAGES for s in rest)
            has_suit = any(s.kind == "suit" for s in rest)
            has_colour = any(s.kind == "colour" for s in rest)
            refs = tuple(sorted({r for s in rest for r in s.refs if r < k}))
            out.append((needs_rank, _SUIT_MODE[has_suit, has_colour], refs))
        return tuple(out)

    @property
    def guess_stages(self) -> tuple[Stage, ...]:
        return tuple(s for s in self.stages if s.is_guess)

    @property
    def guess_count(self) -> int:
        return sum(1 for s in self.stages if s.is_guess)

    @cached_property
    def _guesses_before(self) -> tuple[int, ...]:
        out, n = [], 0
        for s in self.stages:
            out.append(n)
            n += s.is_guess
        out.append(n)
        return tuple(out)

    def guesses_before(self, k: int) -> int:
        """Guessing stages among the first k stages: how far up the ladder you are."""
        return self._guesses_before[k]

    @property
    def effective_decks(self) -> int:
        return self.decks if self.deck_model == "shoe" else 1

    @property
    def structure(self) -> tuple[object, ...]:
        """The payout-free part of the rules: everything that shapes the game tree."""
        return (
            self.deck_model,
            self.effective_decks,
            self.ace,
            self.tie_higher_lower,
            self.tie_range_edge,
            self.stages,
            self.ranks,
        )

    @property
    def ladder_captured(self) -> bool:
        return any(r > 0 for r in self.returns)

    def cash_value(self, survived: int) -> float:
        """What you are paid for stopping after `survived` guessing stages (0: the stake back)."""
        return 1.0 if survived == 0 else self.returns[survived - 1]

    def with_returns(self, returns: Sequence[float]) -> GameSpec:
        return replace(self, returns=tuple(float(r) for r in returns))

    def with_deck(self, model: str, decks: int = 1) -> GameSpec:
        return replace(self, deck_model=model, decks=decks)
