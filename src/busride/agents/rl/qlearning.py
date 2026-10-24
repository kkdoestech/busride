"""Tabular Q-learning and SARSA, in pure Python, on the game's own states.

The agent learns from rounds played on the exact game tree (the solver's canonical states), so
nothing has to be dealt or judged while it trains, and every round is a faithful round of the
real game: each move's outcomes come with the true card counts. It is never shown those counts
or the solver's values, only what each round paid. Its progress is measured exactly: the value
of the moves it currently thinks best is computed on the tree, with no sampling noise.
"""

from __future__ import annotations

import bisect
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from busride.agents.base import CASH
from busride.engine.game import GameSpec
from busride.engine.solver import GameTree, Key, game_tree, policy_value, solve

ALGORITHMS = ("q-learning", "sarsa")
State = tuple[int, Key]  # (cards seen, the solver's key for them)


@dataclass(frozen=True)
class _Move:
    """One move's outcomes: cumulative weights for bisecting, and what each outcome does."""

    cumulative: tuple[int, ...]
    outcomes: tuple[Key | str, ...]  # a next key, "push" or "lose"
    total: int


class TreeGame:
    """The game as the learner sees it: states, legal moves, and a random outcome per move."""

    def __init__(self, rules: GameSpec, tree: GameTree | None = None) -> None:
        self.rules = rules
        self.tree = tree or game_tree(rules)
        self.n = len(rules.stages)
        self.root: State = (0, next(iter(self.tree.levels[0])))
        self._moves: dict[tuple[int, Key, str], _Move] = {}
        for k, level in enumerate(self.tree.levels):
            for key, branches in level.items():
                for b in branches:
                    weights = [w for _, w in b.wins]
                    outcomes: list[Key | str] = [nk for nk, _ in b.wins]
                    if b.push:
                        weights.append(b.push)
                        outcomes.append("push")
                    lose = b.total - sum(weights)
                    if lose:
                        weights.append(lose)
                        outcomes.append("lose")
                    cumulative, running = [], 0
                    for w in weights:
                        running += w
                        cumulative.append(running)
                    self._moves[k, key, b.guess] = _Move(
                        tuple(cumulative), tuple(outcomes), b.total
                    )

    def is_guess(self, k: int) -> bool:
        return self.rules.stages[k].is_guess

    def cash(self, k: int) -> float:
        return self.rules.cash_value(self.rules.guesses_before(k))

    def moves(self, state: State) -> list[str]:
        """The guesses (in the representative's labels), then CASH where stopping is allowed."""
        k, key = state
        guesses = [b.guess for b in self.tree.levels[k][key]]
        survived = self.rules.guesses_before(k)
        if survived > 0 or not self.rules.forced_first_bet:
            guesses.append(CASH)
        return guesses

    def play(self, state: State, move: str, rng: random.Random) -> tuple[float | None, State]:
        """(payout if the round ended, else None; the next state). Reveal stages pass by."""
        k, key = state
        m = self._moves[k, key, move]
        outcome = m.outcomes[bisect.bisect_right(m.cumulative, rng.randrange(m.total))]
        if outcome == "lose":
            return 0.0, state
        if outcome == "push":
            return self.cash(k), state
        return self.advance((k + 1, outcome), rng)  # type: ignore[arg-type]

    def advance(self, state: State, rng: random.Random) -> tuple[float | None, State]:
        """Deal through reveal stages; a finished round pays the top of the ladder."""
        while True:
            k = state[0]
            if k == self.n:
                return self.cash(k), state
            if self.is_guess(k):
                return None, state
            result, state = self.play(state, "", rng)
            if result is not None:
                return result, state


@dataclass
class Learner:
    """A table of move values, learned from the payouts of rounds played."""

    rules: GameSpec
    algorithm: str = "q-learning"
    seed: int = 1
    epsilon: float = 0.3  # exploration at the start: the share of random moves
    epsilon_floor: float = 0.02
    q: dict[State, dict[str, float]] = field(default_factory=dict)
    visits: dict[State, dict[str, int]] = field(default_factory=dict)
    episodes: int = 0

    def __post_init__(self) -> None:
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"algorithm must be one of {', '.join(ALGORITHMS)}")
        self.game = TreeGame(self.rules)
        self.rng = random.Random(self.seed)

    def _values(self, state: State) -> dict[str, float]:
        row = self.q.get(state)
        if row is None:
            # every move starts at the cash-out value, which the rules show any player: a
            # situation is worth at least that, so playing on doesn't look worthless at first
            start = self.game.cash(state[0])
            row = self.q[state] = dict.fromkeys(self.game.moves(state), start)
            self.visits[state] = dict.fromkeys(row, 0)
        return row

    def best(self, state: State) -> str:
        """The move it thinks best (on a tie, the first listed: guesses before cashing out)."""
        row = self._values(state)
        best_move, best_value = "", -1.0
        for move, value in row.items():
            if value > best_value + 1e-12:
                best_move, best_value = move, value
        return best_move

    def _choose(self, state: State, epsilon: float) -> str:
        if self.rng.random() < epsilon:
            return self.rng.choice(list(self._values(state)))
        return self.best(state)

    def current_epsilon(self, total: int) -> float:
        """Exploration fades over the first 60% of training, down to the floor."""
        progress = min(1.0, self.episodes / max(1, int(total * 0.6)))
        return self.epsilon_floor + (self.epsilon - self.epsilon_floor) * (1 - progress)

    def episode(self, epsilon: float) -> float:
        """Play one round, learning after every move. Returns what it paid."""
        game = self.game
        result, state = game.advance(game.root, self.rng)
        if result is not None:
            return result
        move = self._choose(state, epsilon)
        while True:
            if move == CASH:
                payout: float | None = game.cash(state[0])
                nxt = state
            else:
                payout, nxt = game.play(state, move, self.rng)
            if payout is not None:
                self._learn(state, move, payout)
                self.episodes += 1
                return payout
            next_move = self._choose(nxt, epsilon)
            if self.algorithm == "sarsa":
                target = self._values(nxt)[next_move]
            else:
                target = max(self._values(nxt).values())
            self._learn(state, move, target)
            state, move = nxt, next_move

    def _learn(self, state: State, move: str, target: float) -> None:
        row = self._values(state)
        counts = self.visits[state]
        counts[move] += 1
        # the running average of every target seen for this move: early rounds move the
        # estimate a lot, later ones less, so close calls settle precisely
        row[move] += (target - row[move]) / counts[move]

    def policy(self) -> Callable[[int, Key], str | None]:
        def choose(k: int, key: Key) -> str | None:
            state = (k, key)
            if state not in self.q:
                return None if self.game.moves(state)[-1] == CASH else self.game.moves(state)[0]
            move = self.best(state)
            return None if move == CASH else move

        return choose

    def value(self) -> float:
        """The exact return per 1 bet of the moves it currently thinks best."""
        return policy_value(self.rules, self.policy(), self.game.tree)


@dataclass(frozen=True)
class Checkpoint:
    episodes: int
    value: float  # exact return per 1 bet of the learned moves at this point
    epsilon: float


@dataclass(frozen=True)
class Training:
    learner: Learner
    optimal: float
    curve: tuple[Checkpoint, ...]
    seconds: float

    @property
    def value(self) -> float:
        return self.curve[-1].value

    @property
    def regret(self) -> float:
        """What it still gives up against perfect play, per 1 bet."""
        return max(0.0, self.optimal - self.value)


def train(
    rules: GameSpec,
    episodes: int,
    algorithm: str = "q-learning",
    seed: int = 1,
    checkpoints: int = 50,
    on_checkpoint: Callable[[Checkpoint, float], None] | None = None,
) -> Training:
    """Train for `episodes` rounds, measuring the learned moves exactly `checkpoints` times.
    `on_checkpoint(checkpoint, optimal)` follows each measurement (for a live screen)."""
    started = time.perf_counter()
    learner = Learner(rules, algorithm, seed)
    optimal = solve(rules).rtp
    every = max(1, episodes // max(1, checkpoints))
    curve = [Checkpoint(0, learner.value(), learner.current_epsilon(episodes))]
    if on_checkpoint is not None:
        on_checkpoint(curve[0], optimal)
    while learner.episodes < episodes:
        epsilon = learner.current_epsilon(episodes)
        for _ in range(min(every, episodes - learner.episodes)):
            learner.episode(epsilon)
        point = Checkpoint(learner.episodes, learner.value(), epsilon)
        curve.append(point)
        if on_checkpoint is not None:
            on_checkpoint(point, optimal)
    return Training(learner, optimal, tuple(curve), time.perf_counter() - started)
