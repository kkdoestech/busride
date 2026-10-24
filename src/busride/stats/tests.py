"""The individual tests behind `busride verify`.

Every expected count is computed card by card under the deck model, given the cards already
shown in that round. That keeps the tests exact even though which cards get revealed depends
on how the round went.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from scipy import stats as sps

from busride.engine.cards import RANK_LABELS, RANKS, SUITS, Card

Round = Sequence[Card]

CANDIDATE_MODELS: tuple[tuple[str, int], ...] = (
    ("fresh_52", 1),
    ("shoe", 2),
    ("shoe", 6),
    ("with_replacement", 1),
)


def model_label(model: str, decks: int = 1) -> str:
    if model == "fresh_52":
        return "Fresh 52-card deck"
    if model == "shoe":
        return f"{decks}-deck shoe"
    return "Cards can repeat"


def _copies(model: str, decks: int) -> int | None:
    return {"fresh_52": 1, "shoe": decks, "with_replacement": None}[model]


@dataclass(frozen=True)
class Interval:
    label: str
    observed: float
    low: float
    high: float
    expected: float


@dataclass(frozen=True)
class TestResult:
    key: str
    name: str
    stat_name: str
    observed: float
    expected: float | None
    p_value: float | None  # None when there is not enough data to run it
    n: int
    note: str = ""
    interval: Interval | None = None
    statistic: float | None = None  # chi-square value, where there is one
    p_adjusted: float | None = None
    flagged: bool = False


@dataclass(frozen=True)
class ModelFit:
    model: str
    decks: int
    label: str
    p_value: float
    consistent: bool
    loglik: float
    duplicate_rounds: int
    expected_duplicates: float


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def poisson_binomial_cdf(ps: Sequence[float], x: int) -> float:
    """P(X <= x) for a sum of independent Bernoulli(p). Equal p's are grouped as binomials and
    every array is cut at x, since nothing above x can flow back below it."""
    if x < 0:
        return 0.0
    dist = np.zeros(x + 1)
    dist[0] = 1.0
    support = np.arange(x + 1)
    for p, m in Counter(round(p, 12) for p in ps if p > 0).items():
        dist = np.convolve(dist, sps.binom.pmf(support, m, min(p, 1.0)))[: x + 1]
    return float(min(1.0, dist.sum()))


def no_duplicate_chance(n: int, model: str, decks: int) -> float:
    """Chance that n cards dealt in one round are all different."""
    copies = _copies(model, decks)
    if copies is None:
        return math.prod((52 - i) / 52 for i in range(n))
    return math.prod((52 * copies - i * copies) / (52 * copies - i) for i in range(n))


def _has_duplicate(r: Round) -> bool:
    return len(set(r)) < len(r)


def model_fit(rounds: Sequence[Round], model: str, decks: int, alpha: float) -> ModelFit:
    """Is the number of rounds with a repeated card plausible under this deck model?

    A repeat inside one round is impossible from a single fresh deck, so one is enough to
    reject it. Models that allow repeats are tested two-sided: too few repeats or too many.
    """
    dup_rounds = sum(1 for r in rounds if _has_duplicate(r))
    probs = [1 - no_duplicate_chance(len(r), model, decks) for r in rounds]
    expected = sum(probs)
    loglik = 0.0
    for r, q in zip(rounds, probs, strict=True):
        hit = _has_duplicate(r)
        chance = q if hit else 1 - q
        loglik += math.log(chance) if chance > 0 else -math.inf
    if _copies(model, decks) == 1:
        p = 0.0 if dup_rounds else 1.0
    else:
        low = poisson_binomial_cdf(probs, dup_rounds)
        high = 1.0 - poisson_binomial_cdf(probs, dup_rounds - 1)
        p = min(1.0, 2 * min(low, high))
    return ModelFit(
        model, decks, model_label(model, decks), p, p >= alpha, loglik, dup_rounds, expected
    )


def _next_card_weights(prior: Sequence[Card], model: str, decks: int) -> tuple[Counter[Card], int]:
    """Copies already used up by `prior`, and how many cards are left to draw from."""
    copies = _copies(model, decks)
    if copies is None:
        return Counter(), 52
    return Counter(prior), 52 * copies - len(prior)


def _cell(card: Card, cell_of: str) -> str:
    return RANK_LABELS[card.rank] if cell_of == "rank" else card.suit


def _expected_shares(
    rounds: Sequence[Round], model: str, decks: int, cell_of: str
) -> tuple[dict[str, float], dict[str, int], int]:
    """Observed and expected counts per rank or per suit, card by card."""
    copies = _copies(model, decks) or 1
    cells = [RANK_LABELS[r] for r in RANKS] if cell_of == "rank" else list(SUITS)
    per_cell = (52 // len(cells)) * copies
    expected = dict.fromkeys(cells, 0.0)
    observed = dict.fromkeys(cells, 0)
    n = 0
    for r in rounds:
        for j, card in enumerate(r):
            used, left = _next_card_weights(r[:j], model, decks)
            gone = Counter({cell: 0 for cell in cells})
            for c, m in used.items():
                gone[_cell(c, cell_of)] += m
            for cell in cells:
                expected[cell] += (per_cell - gone[cell]) / left
            observed[_cell(card, cell_of)] += 1
            n += 1
    return expected, observed, n


def chi_square_test(rounds: Sequence[Round], model: str, decks: int, cell_of: str) -> TestResult:
    expected, observed, n = _expected_shares(rounds, model, decks, cell_of)
    key = f"{cell_of}s"
    name = "Rank counts (13 cells)" if cell_of == "rank" else "Suit counts (4 cells)"
    if n == 0 or min(expected.values()) < 5:
        need = 65 if cell_of == "rank" else 20
        return TestResult(
            key,
            name,
            "chi-square",
            0.0,
            None,
            None,
            n,
            note=f"needs at least {need} cards; several hundred for a moderate skew",
        )
    stat = sum((observed[c] - e) ** 2 / e for c, e in expected.items())
    df = len(expected) - 1
    p = float(sps.chi2.sf(stat, df))
    worst = max(expected, key=lambda c: abs(observed[c] - expected[c]) / math.sqrt(expected[c]))
    lo, hi = wilson(observed[worst], n)
    interval = Interval(worst, observed[worst] / n, lo, hi, expected[worst] / n)
    return TestResult(
        key,
        name,
        f"chi2({df})",
        stat,
        float(df),
        p,
        n,
        interval=interval,
        statistic=stat,
        note="several hundred rounds for a moderate skew",
    )


def colour_test(rounds: Sequence[Round]) -> TestResult:
    firsts = [r[0] for r in rounds if r]
    n = len(firsts)
    red = sum(1 for c in firsts if c.colour == "red")
    if n == 0:
        return TestResult("colour", "First card colour", "red", 0, None, None, 0, note="no rounds")
    res = sps.binomtest(red, n, 0.5)
    ci = res.proportion_ci(confidence_level=0.95)
    interval = Interval("red", red / n, float(ci.low), float(ci.high), 0.5)
    return TestResult(
        "colour",
        "First card colour",
        "red",
        red,
        n / 2,
        float(res.pvalue),
        n,
        interval=interval,
        note="about 800 rounds to see a 5-point bias with 80% power",
    )


def duplicate_test(rounds: Sequence[Round], model: str, decks: int, alpha: float) -> TestResult:
    fit = model_fit(rounds, model, decks, alpha)
    usable = sum(1 for r in rounds if len(r) >= 2)
    return TestResult(
        "duplicates",
        "Repeated card inside a round",
        "rounds",
        fit.duplicate_rounds,
        fit.expected_duplicates,
        fit.p_value if usable else None,
        usable,
        note="about 30 four-card rounds to expect one if cards repeat",
    )


def repeat_test(rounds: Sequence[Round], model: str, decks: int) -> TestResult:
    """Cards shared between consecutive rounds. A shoe that is not reshuffled between rounds
    shows fewer than a fresh shuffle would."""
    ps: list[float] = []
    hits = 0
    for prev, cur in pairwise(rounds):
        before = set(prev)
        for j, card in enumerate(cur):
            used, left = _next_card_weights(cur[:j], model, decks)
            copies = _copies(model, decks) or 1
            ps.append(sum(copies - used[c] for c in before) / left)
            hits += card in before
    expected = sum(ps)
    if len(rounds) < 2:
        return TestResult(
            "repeats",
            "Repeats between consecutive rounds",
            "cards",
            0,
            None,
            None,
            len(rounds),
            note="needs at least 2 rounds",
        )
    return TestResult(
        "repeats",
        "Repeats between consecutive rounds",
        "cards",
        hits,
        expected,
        poisson_binomial_cdf(ps, hits),
        len(rounds) - 1,
        note="several hundred rounds",
    )


def holm(ps: Sequence[float | None]) -> list[float | None]:
    """Holm step-down adjustment; tests that did not run stay None."""
    present = sorted((p, i) for i, p in enumerate(ps) if p is not None)
    m = len(present)
    out: list[float | None] = [None] * len(ps)
    running = 0.0
    for rank, (p, i) in enumerate(present):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out
