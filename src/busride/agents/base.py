"""What an agent is: anything that looks at the table and picks a move.

The arena hands an agent an `Observation` (everything a player at the table knows) and gets an
`Action` back. Agents never see the cards still to come; the arena grades each move afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from busride.engine.cards import RANKS, Card
from busride.engine.game import GameSpec, Stage
from busride.ui import fmt

CASH = "cash"  # the move that stops: cash out, or walk away before the first guess


class AgentError(ValueError):
    """An answer the arena can't use: unreadable, no move, a refusal. The message says why.

    The arena asks once more with the message, then counts the move as a forfeit. `meta` carries
    what the failed answer cost, so it still counts.
    """

    def __init__(
        self, message: str, raw: str | None = None, meta: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.raw = raw
        self.meta = meta or {}


class AgentUnavailable(RuntimeError):
    """The agent can't be reached or used at all: no API key, no such model, the server is
    down, a rate limit. Not the agent's fault, so not a forfeit: the run stops, and running the
    same command again carries on."""


@dataclass(frozen=True)
class Observation:
    """The table as a player sees it, just before a guess."""

    game: str
    stage: int  # guessing stage about to be played, from 1
    stages: int  # guessing stages in the game
    question: str  # "Higher or lower"
    kind: str  # the stage type: colour, higher_lower, inside_outside or suit
    options: tuple[str, ...]  # the guesses on offer
    can_cash_out: bool  # False while the first bet can't be refused
    seen: tuple[Card, ...]  # the cards on the table, in the order dealt
    compare: tuple[Card, ...]  # the cards this guess is judged against
    cash_value: float  # what stopping pays per 1 bet (before the first guess: the stake back)
    ladder: tuple[float, ...]  # what cashing out pays after each guessing stage
    rules: str  # the rules in plain words
    feedback: str | None = None  # why the previous answer was rejected, when asked again

    @property
    def legal(self) -> tuple[str, ...]:
        return self.options + ((CASH,) if self.can_cash_out else ())


@dataclass(frozen=True)
class Action:
    """A move: one of the options, or CASH."""

    move: str
    win_probability: float | None = None  # the agent's own estimate that its guess wins
    reason: str = ""
    raw: str | None = None  # what a model actually replied, kept in the run file
    meta: dict[str, Any] = field(default_factory=dict)  # model that answered, tokens, cost


class Agent(Protocol):
    name: str

    def reset(self, seed: str) -> None:
        """A new deal starts. Agents that use randomness seed it from `seed`."""

    def decide(self, obs: Observation) -> Action: ...


_TIES = {
    "lose": "loses",
    "push": "pushes: the round ends and pays what cashing out would",
    "win": "wins",
}


def _stage_text(stage: Stage) -> str:
    refs = [f"card {r + 1}" for r in stage.refs]
    if stage.kind == "colour":
        return "red or black"
    if stage.kind == "higher_lower":
        return f"higher or lower than {refs[0]}"
    if stage.kind == "inside_outside":
        return f"inside or outside {refs[0]} and {refs[1]} (inside means strictly between)"
    if stage.kind == "suit":
        return "the suit: hearts, diamonds, clubs or spades"
    return "a card is shown, with no guess"


def describe(rules: GameSpec) -> str:
    """The rules in plain words, for agents that read (and for people)."""
    if rules.deck_model == "with_replacement":
        deck = "Each card is drawn from a full deck, so cards can repeat within a round."
    else:
        size = len(rules.ranks) * 4
        pack = f"a {rules.decks}-deck shoe" if rules.deck_model == "shoe" else f"a {size}-card deck"
        deck = f"Cards come from {pack}, shuffled fresh each round."
        if rules.ranks != RANKS:
            deck += f" Ranks in the deck: {', '.join(str(r) for r in rules.ranks)} (14 = ace)."
    ace = {
        "high": "Aces are high.",
        "low": "Aces are low.",
        "either": "An ace counts high or low, whichever helps the guess.",
    }[rules.ace]
    kinds = {s.kind for s in rules.stages}
    ties = []
    if "higher_lower" in kinds:
        ties.append(f"In higher or lower, an equal rank {_TIES[rules.tie_higher_lower]}.")
    if "inside_outside" in kinds:
        ties.append(
            f"In inside or outside, a card equal to either end {_TIES[rules.tie_range_edge]}."
        )
    stages = "; ".join(f"{s.number}: {_stage_text(s)}" for s in rules.stages)
    ladder = ", ".join(fmt.ret(r) for r in rules.returns)
    first = (
        "The first guess must be played."
        if rules.forced_first_bet
        else "You may walk away before the first guess and keep your stake."
    )
    return " ".join(
        [
            f"{rules.name}. You bet 1, then one card is dealt per stage. Stages: {stages}.",
            deck,
            ace,
            *ties,
            "A wrong guess loses the bet.",
            "After each right guess you may cash out or play on. Cashing out after each "
            f"guessing stage pays (stake included): {ladder}.",
            first,
        ]
    )
