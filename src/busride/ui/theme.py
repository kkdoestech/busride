"""Colours, glyphs and the console. Colour carries meaning, never decoration:
green = a play with positive expected value, amber = marginal (within 2%), red = a losing play."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import IO

from rich import box
from rich.console import Console
from rich.theme import Theme

THEME = Theme(
    {
        "good": "bold #4ade80",
        "warn": "bold #fbbf24",
        "bad": "bold #f87171",
        "good.soft": "#4ade80",
        "warn.soft": "#fbbf24",
        "bad.soft": "#f87171",
        "muted": "#8b949e",
        "accent": "bold #7dd3fc",
        "heading": "bold",
        "card.red": "bold #ff5f5f",
        "card.black": "bold bright_white",
        "card.frame": "#6e7681",
        "bar.empty": "#3a3f47",
    }
)

ASCII_SIMPLE_HEAD = box.Box(
    "    \n    \n -- \n    \n    \n    \n    \n    \n",
    ascii=True,
)


@dataclass(frozen=True)
class Glyphs:
    suits: dict[str, str]
    full: str
    empty: str
    dot: str
    arrow: str
    dash: str
    check: str
    cross: str
    spark: str
    card: str  # top-left, horizontal, top-right, vertical, bottom-left, bottom-right
    panel: box.Box
    table: box.Box


UNICODE = Glyphs(
    suits={"h": "♥", "d": "♦", "c": "♣", "s": "♠"},
    full="█",
    empty="░",
    dot="·",
    arrow="→",
    dash="—",
    check="✓",
    cross="✗",
    spark="▁▂▃▄▅▆▇█",
    card="╭─╮│╰╯",
    panel=box.ROUNDED,
    table=box.SIMPLE_HEAD,
)

ASCII = Glyphs(
    suits={"h": "H", "d": "D", "c": "C", "s": "S"},
    full="#",
    empty="-",
    dot="-",
    arrow="->",
    dash="-",
    check="ok",
    cross="x",
    spark="_.,:-=+*#",
    card="+-+|++",
    panel=box.ASCII,
    table=ASCII_SIMPLE_HEAD,
)

MAX_WIDTH = 100


@dataclass(frozen=True)
class Ui:
    console: Console
    g: Glyphs
    plain: bool = False
    ascii: bool = False

    @property
    def width(self) -> int:
        """Layout width: the terminal's, capped so wide screens stay readable."""
        return min(self.console.width, MAX_WIDTH)


def make_ui(
    plain: bool = False,
    ascii: bool = False,
    width: int | None = None,
    file: IO[str] | None = None,
    force_terminal: bool | None = None,
    record: bool = False,
) -> Ui:
    """`plain` (or NO_COLOR) drops colour; `ascii` swaps glyphs for H D S C, # and -."""
    no_color = plain or bool(os.environ.get("NO_COLOR"))
    console = Console(
        theme=THEME,
        color_system=None if plain else "auto",
        no_color=no_color,
        width=width,
        file=file,
        force_terminal=force_terminal,
        highlight=False,
        emoji=False,
        record=record,
        safe_box=False,
    )
    return Ui(console, ASCII if ascii else UNICODE, plain=no_color, ascii=ascii)
