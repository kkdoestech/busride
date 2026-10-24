"""Block-character probability bars and sparklines."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

from busride.ui.theme import Ui


def bar(fraction: float, width: int, style: str, ui: Ui) -> Text:
    fraction = min(max(fraction, 0.0), 1.0)
    filled = round(fraction * width)
    out = Text(ui.g.full * filled, style=style)
    out.append(ui.g.empty * (width - filled), style="bar.empty")
    return out


def sparkline(values: Sequence[float], width: int, ui: Ui, style: str = "accent") -> Text:
    """The series squeezed (or stretched) to `width` columns, lowest value at the floor."""
    if not values:
        return Text("")
    if len(values) > width:
        step = len(values) / width
        values = [values[min(len(values) - 1, int((i + 1) * step) - 1)] for i in range(width)]
    lo, hi = min(values), max(values)
    levels = ui.g.spark
    span = hi - lo
    chars = [
        levels[0] if span == 0 else levels[round((v - lo) / span * (len(levels) - 1))]
        for v in values
    ]
    return Text("".join(chars), style=style)
