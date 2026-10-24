"""The leaderboard numbers. Everything is per 1 bet, and exact unless it says otherwise.

The headline is the chips an agent gives up per deal: the sum of its regrets, where a decision's
regret is the value of the best move minus the value of the move made. Its expectation is exactly
perfect play's return minus the agent's, and luck doesn't enter it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from busride.agents.base import CASH
from busride.arena.runs import RunFile
from busride.play import CLOSE

_EPS = 1e-9
Z95 = 1.959964


def _mean_se(xs: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean = math.fsum(xs) / n  # fsum: the same on every Python version
    if n < 2:
        return mean, 0.0
    var = math.fsum((x - mean) ** 2 for x in xs) / (n - 1)
    return mean, math.sqrt(var / n)


@dataclass(frozen=True)
class Board:
    """One agent's line on the leaderboard."""

    agent: str
    deals: int
    decisions: int
    graded: int  # decisions with an exact answer (all of them unless the game is huge)
    real: int  # graded decisions where the moves weren't all worth the same
    best_moves: int  # real decisions where it made the best move
    given_up_per_deal: float  # mean over deals of the summed regret
    given_up_se: float
    mean_return: float  # what it actually got back per 1 bet, luck included
    return_se: float
    vs_optimal: tuple[float, float] | None  # (mean gap to optimal on the same deals, 95% ±)
    calibration: float | None  # mean |stated - exact| win chance; None if it never said one
    brier: float | None  # mean (stated - won)^2, a push counting as not won
    stated: int  # guesses that came with a win chance
    too_bold: int  # kept going when stopping was better by more than 2%
    too_timid: int  # stopped when going on was better by more than 2%
    retries: int
    forfeits: int
    seconds: float  # mean time per decision
    meta: dict[str, Any]

    @property
    def best_rate(self) -> float | None:
        return self.best_moves / self.real if self.real else None

    @property
    def coverage(self) -> float:
        return self.graded / self.decisions if self.decisions else 1.0


def score(run: RunFile) -> dict[str, Board]:
    """Every agent's board, best first (least given up)."""
    decisions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in run.decisions():
        decisions[d["agent"]].append(d)
    payouts: dict[str, dict[int, float]] = defaultdict(dict)
    for r in run.finished():
        payouts[r["agent"]][r["deal"]] = r["payout"]
    boards = [
        _board(agent, decisions[agent], payouts[agent], payouts.get("optimal"))
        for agent in run.agents()
    ]
    boards.sort(key=lambda b: (b.given_up_per_deal, b.agent != "optimal", b.agent))
    return {b.agent: b for b in boards}


def _board(
    agent: str,
    decisions: list[dict[str, Any]],
    payouts: dict[int, float],
    optimal: dict[int, float] | None,
) -> Board:
    regret_by_deal = dict.fromkeys(payouts, 0.0)
    graded = real = best = bold = timid = 0
    gaps: list[float] = []
    briers: list[float] = []
    for d in decisions:
        if d.get("regret") is None:
            continue
        graded += 1
        regret = d["regret"]
        regret_by_deal[d["deal"]] = regret_by_deal.get(d["deal"], 0.0) + regret
        if not d["trivial"]:
            real += 1
            best += regret <= _EPS
        clearly = regret > CLOSE * max(d["value"], _EPS)
        if clearly and d["move"] == CASH:
            timid += 1
        elif clearly and d["best"] == CASH and d["valid"]:
            bold += 1
    for d in decisions:
        if d.get("stated") is not None and d.get("exact") is not None:
            gaps.append(abs(d["stated"] - d["exact"]))
            briers.append((d["stated"] - (d["result"] == "win")) ** 2)
    given_up, given_up_se = _mean_se(list(regret_by_deal.values()))
    mean_return, return_se = _mean_se(list(payouts.values()))
    vs = None
    if optimal is not None and agent != "optimal":
        common = [n for n in payouts if n in optimal]
        if common:
            gap, se = _mean_se([payouts[n] - optimal[n] for n in common])
            vs = (gap, Z95 * se)
    meta: dict[str, Any] = {}
    for d in decisions:
        for key, value in d.get("meta", {}).items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                meta[key] = meta.get(key, 0) + value
    return Board(
        agent=agent,
        deals=len(payouts),
        decisions=len(decisions),
        graded=graded,
        real=real,
        best_moves=best,
        given_up_per_deal=given_up,
        given_up_se=given_up_se,
        mean_return=mean_return,
        return_se=return_se,
        vs_optimal=vs,
        calibration=sum(gaps) / len(gaps) if gaps else None,
        brier=sum(briers) / len(briers) if briers else None,
        stated=len(gaps),
        too_bold=bold,
        too_timid=timid,
        retries=sum(d.get("retries", 0) for d in decisions),
        forfeits=sum(1 for d in decisions if not d["valid"]),
        seconds=sum(d.get("seconds", 0.0) for d in decisions) / len(decisions)
        if decisions
        else 0.0,
        meta=meta,
    )
