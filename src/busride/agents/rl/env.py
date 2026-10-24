"""A Gymnasium environment for any busride game, for training your own agents.

Needs the `rl` extra (`uv sync --extra rl`, or `pip install "busride[rl]"`).

    import gymnasium
    from busride.agents.rl.env import BusRideEnv
    env = BusRideEnv("ride-the-bus")
    obs, info = env.reset(seed=1)
    obs, reward, terminated, truncated, info = env.step(info["legal"][0])

- **Observation:** `{"stage": index of the stage about to be played, "cards": the cards dealt so
  far, each 1..52 (rank-major: 2h=1, 2d=2, ... As=52; 0 = not dealt yet)}`.
- **Actions:** one index per move the game ever offers (`env.moves`: the guesses, then "cash").
  `info["action_mask"]` marks the legal ones; an illegal move ends the round as a forfeit.
- **Reward:** given when the round ends: what it paid per 1 bet, minus the bet (so perfect play
  averages a little below 0 on a game with a house edge).
"""

from __future__ import annotations

from typing import Any

try:
    import gymnasium as gym
    import numpy as np
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover - depends on the extra
    raise ImportError(
        "the Gymnasium environment needs the rl extra: uv sync --extra rl (or pip install "
        '"busride[rl]")'
    ) from exc

from busride.agents.base import CASH
from busride.engine.builtins import BUILTIN_GAMES, load_game
from busride.engine.cards import FULL_DECK, Card, copies_per_card, deck_of
from busride.engine.game import GameSpec
from busride.engine.stages import Result, judge

CARD_INDEX = {card: i + 1 for i, card in enumerate(FULL_DECK)}


class BusRideEnv(gym.Env[dict[str, Any], Any]):
    metadata: dict[str, Any] = {"render_modes": ["ansi"]}  # noqa: RUF012 (as Gymnasium declares it)

    def __init__(self, game: str | GameSpec = "ride-the-bus", render_mode: str | None = None):
        self.rules = (
            game if isinstance(game, GameSpec) else (BUILTIN_GAMES.get(game) or load_game(game))
        )
        self.render_mode = render_mode
        self.moves = [*dict.fromkeys(g for s in self.rules.stages for g in s.guesses), CASH]
        n = len(self.rules.stages)
        self.action_space = spaces.Discrete(len(self.moves))
        self.observation_space = spaces.Dict(
            {
                "stage": spaces.Discrete(n + 1),
                "cards": spaces.MultiDiscrete([len(FULL_DECK) + 1] * n),
            }
        )
        self._deal: list[Card] = []
        self._seen: list[Card] = []
        self._survived = 0

    def _legal(self) -> list[int]:
        k = len(self._seen)
        stage = self.rules.stages[k]
        legal = [self.moves.index(g) for g in stage.guesses]
        if self._survived > 0 or not self.rules.forced_first_bet:
            legal.append(self.moves.index(CASH))
        return legal

    def _obs(self) -> dict[str, Any]:
        cards = np.zeros(len(self.rules.stages), dtype=np.int64)
        for i, card in enumerate(self._seen):
            cards[i] = CARD_INDEX[card]
        return {"stage": len(self._seen), "cards": cards}

    def _info(self) -> dict[str, Any]:
        if len(self._seen) >= len(self.rules.stages):
            return {"action_mask": np.zeros(len(self.moves), dtype=np.int8), "legal": []}
        legal = self._legal()
        mask = np.zeros(len(self.moves), dtype=np.int8)
        mask[legal] = 1
        return {"action_mask": mask, "legal": legal}

    def _reveal(self) -> None:
        while (
            len(self._seen) < len(self.rules.stages)
            and not self.rules.stages[len(self._seen)].is_guess
        ):
            self._seen.append(self._deal[len(self._seen)])

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        super().reset(seed=seed)
        deck = list(deck_of(self.rules.ranks))
        copies = copies_per_card(self.rules.deck_model, self.rules.effective_decks)
        n = len(self.rules.stages)
        if copies is None:
            picks = self.np_random.integers(0, len(deck), size=n)
        else:
            picks = self.np_random.choice(len(deck) * copies, size=n, replace=False) % len(deck)
        self._deal = [deck[int(i)] for i in picks]
        self._seen, self._survived = [], 0
        self._reveal()
        return self._obs(), self._info()

    def step(self, action: Any) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        rules = self.rules
        action = int(action)
        if action not in self._legal():
            return self._obs(), -1.0, True, False, {**self._info(), "illegal": True}
        move = self.moves[action]
        if move == CASH:
            return self._end(rules.cash_value(self._survived))
        k = len(self._seen)
        card = self._deal[k]
        result = judge(rules.stages[k].number, move, self._seen, card, rules)[1]
        self._seen.append(card)
        if result is Result.LOSE:
            return self._end(0.0)
        if result is Result.PUSH:
            return self._end(rules.cash_value(self._survived))
        self._survived += 1
        self._reveal()
        if len(self._seen) == len(rules.stages):
            return self._end(rules.cash_value(rules.guess_count))
        return self._obs(), 0.0, False, False, self._info()

    def _end(self, payout: float) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        return self._obs(), payout - 1.0, True, False, {**self._info(), "payout": payout}

    def render(self) -> str | None:
        if self.render_mode != "ansi":
            return None
        cards = " ".join(str(c) for c in self._seen) or "no cards yet"
        return f"{self.rules.name}: {cards}"
