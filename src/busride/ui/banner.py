"""The verdict banner (one per report), section headings and the rules footer."""

from __future__ import annotations

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from busride.engine.rules import BUILT_IN_VERSION, PLACEHOLDER_VERSION, Rules
from busride.ui.theme import Ui

APP = "RIDE THE BUS"


def title(screen: str, ui: Ui) -> str:
    return f"{APP} {ui.g.dot} {screen}"


def verdict(kind: str, headline: str, detail: str | Text, ui: Ui) -> Panel:
    """kind is 'good', 'warn' or 'bad'."""
    body = Text(headline, style=kind)
    if detail:
        body.append("\n")
        body.append_text(detail if isinstance(detail, Text) else Text(detail))
    return Panel(body, box=ui.g.panel, border_style=f"{kind}.soft", padding=(0, 2), width=ui.width)


def heading(text: str, ui: Ui, right: str = "") -> Text:
    out = Text(text, style="heading")
    if right:
        out.append(f"   {right}", style="muted")
    return out


def warnings(lines: list[str], ui: Ui) -> RenderableType:
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        out.append("! ", style="warn")
        out.append(line, style="warn.soft")
    return out


def footer(rules: Rules, ui: Ui, extra: str = "") -> Text:
    """The rules file and game version behind every number on the screen."""
    d = ui.g.dot
    model = {"fresh_52": "fresh 52", "with_replacement": "cards repeat"}.get(
        rules.deck_model, f"{rules.decks}-deck shoe"
    )
    if rules.game_version == BUILT_IN_VERSION:
        where = [rules.source]  # "built-in hi-lo-5": no version or capture date to report
    else:
        version = "?" if rules.game_version in ("", PLACEHOLDER_VERSION) else rules.game_version
        where = [rules.source, f"game {version}", rules.captured_on or "capture date ?"]
    line = f" {d} ".join(
        [*where, model, f"ace {rules.ace}", f"ties {rules.tie_higher_lower}/{rules.tie_range_edge}"]
    )
    if extra:
        joined = f"{line} {d} {extra}"
        line = joined if len(joined) <= ui.width else f"{line}\n{extra}"
    return Text(line, style="muted")
