"""Cards, parsing and the deck models (what is left to draw, with integer weights)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache
from typing import NamedTuple

SUITS = ("h", "d", "c", "s")
SUIT_NAMES = {"h": "hearts", "d": "diamonds", "c": "clubs", "s": "spades"}
RED_SUITS = frozenset({"h", "d"})
RANKS = tuple(range(2, 15))  # 11 = J, 12 = Q, 13 = K, 14 = A
RANK_LABELS = {**{r: str(r) for r in range(2, 11)}, 11: "J", 12: "Q", 13: "K", 14: "A"}

DECK_MODELS = ("fresh_52", "with_replacement", "shoe")

_RANK_INPUT = {
    **{str(r): r for r in range(2, 11)},
    "t": 10,
    "j": 11,
    "q": 12,
    "k": 13,
    "a": 14,
}
_SUIT_INPUT = {
    "h": "h",
    "d": "d",
    "c": "c",
    "s": "s",
    "♥": "h",
    "♡": "h",
    "♦": "d",
    "♢": "d",
    "♣": "c",
    "♧": "c",
    "♠": "s",
    "♤": "s",
}


class CardError(ValueError):
    """A card that could not be read. The message is a one-line explanation for the player."""


class Card(NamedTuple):
    """A card. A named tuple rather than a dataclass: the solver hashes millions of them."""

    rank: int  # 2..14, ace stored as 14
    suit: str  # h d c s

    @property
    def label(self) -> str:
        return RANK_LABELS[self.rank]

    @property
    def colour(self) -> str:
        return "red" if self.suit in RED_SUITS else "black"

    def __str__(self) -> str:
        return f"{self.label}{self.suit}"


FULL_DECK: tuple[Card, ...] = tuple(Card(r, s) for r in RANKS for s in SUITS)


def parse_card(text: str) -> Card:
    """Read one card typed as rank plus suit: 9h, Ks, 10d, Td, Ad, or with a glyph like 9♥."""
    raw = text.strip().strip("\ufeff\u200b")  # a byte-order mark sneaks in from some pipes
    t = raw.lower()
    if not t:
        raise CardError("empty card")
    suit_ch, rank_txt = t[-1], t[:-1]
    if suit_ch not in _SUIT_INPUT:
        raise CardError(f"'{raw}' has no suit: end it with h, d, c or s (9h, Ks, 10d)")
    if rank_txt not in _RANK_INPUT:
        raise CardError(f"'{raw}' has no valid rank: use 2-10, J, Q, K or A (9h, Ks, 10d)")
    return Card(_RANK_INPUT[rank_txt], _SUIT_INPUT[suit_ch])


def parse_cards(text: str) -> list[Card]:
    """Read cards separated by spaces or commas."""
    return [parse_card(tok) for tok in re.split(r"[\s,]+", text.strip()) if tok]


def copies_per_card(model: str, decks: int) -> int | None:
    """Copies of each card in a fresh pack, or None when every draw comes from a full deck."""
    if model == "fresh_52":
        return 1
    if model == "shoe":
        return max(1, decks)
    if model == "with_replacement":
        return None
    raise ValueError(f"unknown deck model {model!r}")


@lru_cache(maxsize=32)
def deck_of(ranks: tuple[int, ...] = RANKS) -> tuple[Card, ...]:
    """One copy of every card of these ranks (all 13 ranks: the full 52-card deck)."""
    return tuple(Card(r, s) for r in ranks for s in SUITS)


def remaining(
    seen: Sequence[Card], model: str, decks: int = 1, ranks: tuple[int, ...] = RANKS
) -> list[tuple[Card, int]]:
    """Cards that can come next, each with an integer weight (copies left).

    Weights rather than probabilities keep the odds checkable by eye: 32/50, not 0.64.
    """
    deck = deck_of(ranks)
    copies = copies_per_card(model, decks)
    if copies is None:
        return [(c, 1) for c in deck]
    used = Counter(seen)
    return [(c, copies - used[c]) for c in deck if copies - used[c] > 0]


def deal_conflict(seen: Sequence[Card], model: str, decks: int = 1) -> Card | None:
    """The first card that appears more often than the deck model allows, if any."""
    copies = copies_per_card(model, decks)
    if copies is None:
        return None
    used: Counter[Card] = Counter()
    for card in seen:
        used[card] += 1
        if used[card] > copies:
            return card
    return None
