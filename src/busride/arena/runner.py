"""Duplicate deals: every agent plays the same cards, and every decision is graded exactly.

Each deal's cards are drawn up front from its own seed, hash(run seed, game, deal number), so an
agent that stops early just sees fewer of them. The deals are saved in the run file, so the run
reproduces on any Python version. Agents that use randomness get a separate stream per deal.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from busride import __version__
from busride.agents.base import CASH, Action, Agent, AgentError, Observation, describe
from busride.agents.oracle import Oracle, oracle_for
from busride.arena.runs import FORMAT, RunFile, fingerprint
from busride.engine.builtins import slug
from busride.engine.cards import Card, copies_per_card, deck_of, parse_card
from busride.engine.game import GameSpec
from busride.engine.rules import dump_rules
from busride.engine.solver import DEFAULT_BUDGET
from busride.engine.stages import Result, judge
from busride.play import grade_decision

DEFAULT_SEED = 7
DEFAULT_DEALS = 2000  # offline agents; AI models default to 20 (they cost money and time)


def deal_seed(seed: int, game: str, number: int) -> int:
    digest = hashlib.sha256(f"{seed}:{game}:{number}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def make_deals(rules: GameSpec, deals: int, seed: int) -> list[list[str]]:
    """Every deal's full card sequence, as card names ('10d')."""
    deck = deck_of(rules.ranks)
    copies = copies_per_card(rules.deck_model, rules.effective_decks)
    size = len(rules.stages)
    game = slug(rules.name)
    out = []
    for number in range(1, deals + 1):
        rng = random.Random(deal_seed(seed, game, number))
        cards = rng.choices(deck, k=size) if copies is None else rng.sample(deck * copies, size)
        out.append([str(c) for c in cards])
    return out


def _problem(action: object, obs: Observation) -> str | None:
    """Why an answer can't be played, or None if it can."""
    if not isinstance(action, Action):
        return "the answer was not a move"
    if action.move not in obs.legal:
        if action.move == CASH:
            return f"the first bet must be played here: choose {' or '.join(obs.options)}"
        return f"{action.move!r} is not a move here: choose one of {', '.join(obs.legal)}"
    p = action.win_probability
    if p is not None and not (
        isinstance(p, int | float) and math.isfinite(p) and 0.0 <= float(p) <= 1.0
    ):
        return "win_probability must be a number from 0 to 1"
    return None


def _add(total: dict[str, Any], meta: dict[str, Any]) -> None:
    """Numbers add up (tokens, cost, requests); anything else keeps the latest value."""
    for key, value in meta.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + value
        else:
            total[key] = value


def ask(agent: Agent, obs: Observation) -> tuple[Action | None, int, list[str], dict[str, Any]]:
    """The agent's move, asking once more (with the reason) if the first answer can't be
    played. Returns (action or None for a forfeit, retries used, the problems seen, what every
    attempt cost together)."""
    problems: list[str] = []
    meta: dict[str, Any] = {}
    for attempt in range(2):
        try:
            action = agent.decide(replace(obs, feedback=problems[-1]) if problems else obs)
        except AgentError as exc:
            _add(meta, exc.meta)
            problems.append(f"{exc} (said: {exc.raw})" if exc.raw else str(exc))
            continue
        if isinstance(action, Action):
            _add(meta, action.meta)
        problem = _problem(action, obs)
        if problem is None:
            return action, attempt, problems, meta
        problems.append(problem)
    return None, 1, problems, meta


class Arena:
    """One run: a game, a seed and a number of deals, kept in one file.

    `seed` and `deals` left as None take the saved run's values when resuming, else the defaults.
    """

    def __init__(
        self,
        rules: GameSpec,
        path: Path | str,
        seed: int | None = None,
        deals: int | None = None,
        budget: int = DEFAULT_BUDGET,
    ) -> None:
        self.rules = rules
        self.file = RunFile(path)
        self.seed = seed
        self.deals = deals
        self.budget = budget

    def run(
        self,
        agents: Sequence[Agent],
        on_deal: Callable[[int, int], None] | None = None,
        on_play: Callable[[str, list[dict[str, Any]]], None] | None = None,
    ) -> RunFile:
        """Play every deal not yet played by each agent. `on_deal(n, deals)` follows each deal;
        `on_play(agent, lines)` each agent's play of it."""
        names = [a.name for a in agents]
        twice = sorted({n for n in names if names.count(n) > 1})
        if twice:
            raise ValueError(f"each agent can play only once in a run: {', '.join(twice)}")
        deals, seed = self._open()
        done = self.file.done()
        oracle = oracle_for(self.rules, self.budget)
        summary = describe(self.rules)
        with self.file.writer() as write:
            for number, names_dealt in enumerate(deals, start=1):
                cards = [parse_card(c) for c in names_dealt]
                for agent in agents:
                    if (agent.name, number) not in done:
                        lines = self._play(agent, number, cards, seed, oracle, summary)
                        write(lines)
                        if on_play is not None:
                            on_play(agent.name, lines)
                if on_deal is not None:
                    on_deal(number, len(deals))
        return self.file

    def _open(self) -> tuple[list[list[str]], int]:
        """The deals and seed: the saved run's, or a new run's."""
        rules = self.rules
        if self.file.exists():
            h = self.file.header()
            seed = h["seed"] if self.seed is None else self.seed
            count = len(h["deals"]) if self.deals is None else self.deals
            if (seed, count, fingerprint(rules)) != (h["seed"], len(h["deals"]), h["fingerprint"]):
                raise ValueError(
                    f"{self.file.name} holds a different run ({h['game']}, seed {h['seed']}, "
                    f"{len(h['deals'])} deals): give it another name, or use the same game, "
                    "payouts, seed and deals to add agents to it"
                )
            return h["deals"], seed
        seed = DEFAULT_SEED if self.seed is None else self.seed
        deals = make_deals(rules, DEFAULT_DEALS if self.deals is None else self.deals, seed)
        self.file.start(
            {
                "type": "run",
                "format": FORMAT,
                "name": self.file.name,
                "created": datetime.now().isoformat(timespec="seconds"),
                "busride": __version__,
                "game": rules.name,
                "source": rules.source,
                "fingerprint": fingerprint(rules),
                "seed": seed,
                "rules": dump_rules(rules),
                "returns": list(rules.returns),
                "deals": deals,
            }
        )
        return deals, seed

    def _play(
        self,
        agent: Agent,
        number: int,
        cards: list[Card],
        seed: int,
        oracle: Oracle,
        summary: str,
    ) -> list[dict[str, Any]]:
        """One agent plays one deal. Returns its decision lines and the deal line."""
        rules = self.rules
        agent.reset(f"{seed}:{agent.name}:{number}")
        seen: list[Card] = []
        lines: list[dict[str, Any]] = []
        survived = 0
        end, payout = "full", rules.cash_value(rules.guess_count)
        started = time.perf_counter()
        for k, stage in enumerate(rules.stages):
            card = cards[k]
            if not stage.is_guess:
                seen.append(card)
                continue
            forced = survived == 0 and rules.forced_first_bet
            obs = Observation(
                game=rules.name,
                stage=survived + 1,
                stages=rules.guess_count,
                question=stage.question,
                kind=stage.kind,
                options=stage.guesses,
                can_cash_out=not forced,
                seen=tuple(seen),
                compare=tuple(seen[i] for i in stage.refs),
                cash_value=rules.cash_value(survived),
                ladder=rules.returns,
                rules=summary,
            )
            t0 = time.perf_counter()
            action, retries, problems, meta = ask(agent, obs)
            seconds = time.perf_counter() - t0
            line = self._grade(oracle, obs, action, forced)
            line.update(agent=agent.name, deal=number, position=k, retries=retries)
            line["seconds"] = round(seconds, 6)
            if problems:
                line["problems"] = problems
            if meta:
                line["meta"] = meta
            lines.append(line)
            if action is None:
                end, payout = "forfeit", 0.0
                break
            if action.move == CASH:
                end, payout = ("cash" if survived else "walk"), rules.cash_value(survived)
                line["result"] = "cash"
                break
            result = judge(stage.number, action.move, seen, card, rules)[1]
            seen.append(card)
            line["card"] = str(card)
            line["result"] = result.value
            if result is Result.LOSE:
                end, payout = "lost", 0.0
                break
            if result is Result.PUSH:
                end, payout = "push", rules.cash_value(survived)
                break
            survived += 1
        lines.append(
            {
                "type": "deal",
                "agent": agent.name,
                "deal": number,
                "payout": payout,
                "end": end,
                "survived": survived,
                "seconds": round(time.perf_counter() - started, 6),
            }
        )
        return lines

    def _grade(
        self, oracle: Oracle, obs: Observation, action: Action | None, forced: bool
    ) -> dict[str, Any]:
        """The decision line, before the card: the move against the exact answer."""
        line: dict[str, Any] = {
            "type": "decision",
            "stage": obs.stage,
            "seen": [str(c) for c in obs.seen],
            "move": "forfeit" if action is None else action.move,
            "valid": action is not None,
            "forced": forced,
            "result": "forfeit",
        }
        if action is not None:
            if action.move != CASH:
                odds = {o.guess: o for o in oracle.odds(obs.seen)}
                line["exact"] = odds[action.move].chance
                if action.win_probability is not None:
                    line["stated"] = float(action.win_probability)
            if action.reason:
                line["reason"] = action.reason
            if action.raw is not None:
                line["raw"] = action.raw
        d = oracle.decision(obs.seen)
        if d is None:  # no exact answer for this state
            line.update(q=None, value=None, best=None, regret=None, trivial=None)
            return line
        g = grade_decision(d, self.rules, d.best.guess if action is None else action.move)
        q = 0.0 if action is None else g.q
        line.update(
            q=q, value=g.value, best=g.best, regret=max(0.0, g.value - q), trivial=g.trivial
        )
        return line
