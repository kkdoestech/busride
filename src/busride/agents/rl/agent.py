"""Trained agents on disk, and playing one in the arena (`rl:NAME`).

A trained agent is a JSON file: the game it learned (with a fingerprint of its rules and
payouts), how it was trained, its exact score, its learning curve, and its move for every state
of the game tree. With real cards, each of its moves is matched to the real guess that leads to
the same outcomes, so a policy learned on "two hearts seen" also plays "two clubs seen".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from busride import __version__, config
from busride.agents.base import CASH, Action, Observation
from busride.agents.rl.qlearning import Training
from busride.arena.runs import fingerprint
from busride.engine.game import GameSpec
from busride.engine.rules import dump_rules
from busride.engine.solver import Key, branch_of, game_tree, same_move
from busride.engine.stages import state_key

FORMAT = 1


def agents_dir() -> Path:
    return config.data_dir() / "agents"


def _slot(k: int, key: Key) -> str:
    return f"{k}|{key!r}"


def agent_path(name: str) -> Path:
    """A saved agent by name (in your data folder), or the path of a .json file."""
    if name.lower().endswith(".json"):
        return Path(name)
    return agents_dir() / f"{name}.json"


def save(training: Training, name: str, path: Path | None = None) -> Path:
    learner = training.learner
    rules = learner.rules
    tree = learner.game.tree
    choose = learner.policy()
    policy: dict[str, str] = {}
    for k, level in enumerate(tree.levels):
        if not rules.stages[k].is_guess:
            continue
        for key in level:
            pick = choose(k, key)
            policy[_slot(k, key)] = CASH if pick is None else pick
    q = {
        _slot(*state): {m: [round(v, 6), learner.visits[state][m]] for m, v in row.items()}
        for state, row in learner.q.items()
    }
    data: dict[str, Any] = {
        "type": "busride-agent",
        "format": FORMAT,
        "name": name,
        "busride": __version__,
        "trained": datetime.now().isoformat(timespec="seconds"),
        "algorithm": learner.algorithm,
        "episodes": learner.episodes,
        "seed": learner.seed,
        "game": rules.name,
        "fingerprint": fingerprint(rules),
        "rules": dump_rules(rules),
        "returns": list(rules.returns),
        "value": training.value,
        "optimal": training.optimal,
        "seconds": round(training.seconds, 3),
        "curve": [[c.episodes, c.value] for c in training.curve],
        "policy": policy,
        "q": q,
    }
    path = path or agent_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return path


def load(name: str) -> dict[str, Any]:
    path = agent_path(name)
    if not path.exists():
        raise ValueError(
            f"there is no trained agent called {name!r}: train one with `busride train --name "
            f"{name}`"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} can't be read as a trained agent: {exc}") from None
    if not isinstance(data, dict) or data.get("type") != "busride-agent":
        raise ValueError(f"{path} is not a trained busride agent")
    if data.get("format", 0) > FORMAT:
        raise ValueError(f"{path} was saved by a newer busride: update to use it")
    return data


class RLAgent:
    """Plays the moves a trained agent learned."""

    def __init__(self, name: str, data: dict[str, Any], rules: GameSpec) -> None:
        if data["fingerprint"] != fingerprint(rules):
            raise ValueError(
                f"rl:{name} learned {data['game']} with other rules or payouts: train one for this "
                "game (busride train, with the same --game and --ladder)"
            )
        self.name = f"rl:{Path(name).stem if name.lower().endswith('.json') else name}"
        self.rules = rules
        self.policy: dict[str, str] = data["policy"]
        self.tree = game_tree(rules)

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        seen = obs.seen
        k = len(seen)
        key = state_key(self.rules, seen)
        branches = self.tree.levels[k].get(key)
        pick = self.policy.get(_slot(k, key))
        if branches is None or pick is None:  # can't happen for the game it learned
            return Action(obs.options[0], reason="a situation it never learned")
        if pick == CASH:
            if obs.can_cash_out:
                return Action(CASH, reason="learned to cash out here")
            pick = branches[0].guess
        target = next(b for b in branches if b.guess == pick)
        for guess in obs.options:  # the real guess that leads where the learned one does
            if same_move(branch_of(self.rules, seen, guess), target):
                return Action(guess, reason="learned to play on here")
        return Action(obs.options[0], reason="no matching move")


def load_agent(name: str, rules: GameSpec) -> RLAgent:
    return RLAgent(name, load(name), rules)
