"""Card glyphs: small framed cards for the table, and inline cards for text."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

from busride.engine.cards import Card
from busride.ui.theme import Ui


def card_style(card: Card) -> str:
    return "card.red" if card.colour == "red" else "card.black"


def card_text(card: Card, ui: Ui) -> Text:
    """'9♥' (or '9H' in ASCII mode) in the suit's colour."""
    return Text(f"{card.label}{ui.g.suits[card.suit]}", style=card_style(card))


def cards_inline(cards: Sequence[Card], ui: Ui, sep: str = " ") -> Text:
    out = Text()
    for i, card in enumerate(cards):
        if i:
            out.append(sep)
        out.append_text(card_text(card, ui))
    return out


def card_row(cards: Sequence[Card], ui: Ui, indent: int = 1) -> Text:
    """Framed cards side by side:

    ╭────╮ ╭────╮
    │ 9  │ │ K  │
    │ ♥  │ │ ♠  │
    ╰────╯ ╰────╯
    """
    tl, h, tr, v, bl, br = tuple(ui.g.card)
    pad = " " * indent
    lines = [Text(pad), Text(pad), Text(pad), Text(pad)]
    for i, card in enumerate(cards):
        gap = " " if i else ""
        style = card_style(card)
        lines[0].append(f"{gap}{tl}{h * 4}{tr}", style="card.frame")
        for row, glyph in ((1, card.label), (2, ui.g.suits[card.suit])):
            lines[row].append(f"{gap}{v}", style="card.frame")
            lines[row].append(f" {glyph:<2} ", style=style)
            lines[row].append(v, style="card.frame")
        lines[3].append(f"{gap}{bl}{h * 4}{br}", style="card.frame")
    return Text("\n").join(lines)
