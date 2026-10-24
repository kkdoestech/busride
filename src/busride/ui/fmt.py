"""The one place numbers become text. Percentages to one decimal, returns to two decimals
with an x, counts as 32/50 so the odds can be checked by eye."""

from __future__ import annotations


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def signed_pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def mult(x: float) -> str:
    return f"{x:.2f}x"


def ret(x: float, digits: int = 2) -> str:
    """A return per 1 staked, without the x (as in 'cash out 1.00')."""
    return f"{x:.{digits}f}"


def prob(x: float) -> str:
    """An exact probability, to five places."""
    return f"{x:.5f}"


def frac(a: int, b: int) -> str:
    return f"{a}/{b}"


def count(n: float) -> str:
    return f"{n:,.0f}"


def money(x: float) -> str:
    return f"{x:,.2f}"


def signed_money(x: float) -> str:
    return f"{x:+,.2f}"


def pnum(p: float) -> str:
    """A p-value for a table column."""
    if p < 0.001:
        return "<0.001"
    if p < 0.01:
        return f"{p:.3f}"
    return f"{p:.2f}"


def pval(p: float) -> str:
    """A p-value for a sentence."""
    return "p < 0.001" if p < 0.001 else f"p = {pnum(p)}"


def stat(x: float) -> str:
    return f"{x:.2f}"


def duration(seconds: float) -> str:
    if seconds < 0.01:
        return f"{seconds * 1000:.1f} ms"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def hundred(x: float) -> str:
    """An amount per 1 bet, shown per 100 bet: 0.2062 -> '20.6'."""
    return f"{x * 100:.1f}"


def signed_hundred(x: float) -> str:
    return f"{x * 100:+.1f}"


def points(x: float) -> str:
    """A gap between two probabilities, in percentage points: 0.031 -> '3.1 pts'."""
    return f"{x * 100:.1f} pts"


def dollars(x: float) -> str:
    """Money spent on AI calls: '$1.84', '<$0.01', '$0'."""
    if x <= 0:
        return "$0"
    if x < 0.01:
        return "<$0.01"
    return f"${x:,.2f}"
