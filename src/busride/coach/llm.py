"""An AI model rewording the coach's explanations.

busride works out every number; the model only rewords the sentence around them. A reply that
adds a number, or changes one, is thrown away and busride's own wording is used instead. So is
any failure: no key, no server, a refusal.
"""

from __future__ import annotations

import re
from typing import Protocol

from busride.agents.base import AgentUnavailable
from busride.engine.game import GameSpec

SYSTEM = (
    "You reword short explanations for someone new to the card game Ride the Bus. Keep every "
    "number exactly as it is written, add no numbers or facts of your own, and answer with one "
    "or two plain, friendly sentences and nothing else."
)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class _Writer(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str | None: ...


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def keeps_numbers(original: str, reworded: str) -> bool:
    """True when the rewording uses only the original's numbers, and keeps at least one."""
    old, new = numbers(original), numbers(reworded)
    return bool(reworded.strip()) and new <= old and (bool(new) or not old)


class Rewording:
    """Rewords coach text with an AI model; falls back to the text itself on any trouble."""

    def __init__(self, name: str, rules: GameSpec) -> None:
        from busride.agents.llm import make_llm_agent  # the SDKs load only when used

        agent = make_llm_agent(name, rules)
        if not hasattr(agent, "complete"):
            raise ValueError(f"{name!r} can't word the coach's explanations")
        self.writer: _Writer = agent  # type: ignore[assignment]
        self.problem: str | None = None  # why it stopped trying, after a failure

    def __call__(self, text: str) -> str:
        if self.problem is not None:
            return text
        try:
            reworded = self.writer.complete(SYSTEM, f"Reword this: {text}")
        except AgentUnavailable as exc:
            self.problem = str(exc)
            return text
        if reworded is None or not keeps_numbers(text, reworded):
            return text
        return reworded
