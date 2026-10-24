"""What an AI model is told, and how its answer becomes a move. Shared by every provider.

The system prompt and the two tools depend only on the game, so they are byte-identical for every
decision of a run and the provider can cache them. Everything about the current situation, the
legal moves included, goes in the user message.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from busride.agents.base import CASH, Action, AgentError, Observation, describe
from busride.engine.cards import RED_SUITS, SUIT_NAMES, Card
from busride.engine.game import GameSpec
from busride.ui import fmt

GUESS_TOOL = "make_guess"
CASH_TOOL = "cash_out"

_RANK_NAMES = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "jack",
    12: "queen",
    13: "king",
    14: "ace",
}


def card_name(card: Card) -> str:
    """'10d (ten of diamonds)'."""
    return f"{card} ({_RANK_NAMES[card.rank]} of {SUIT_NAMES[card.suit]})"


def all_guesses(rules: GameSpec) -> list[str]:
    """Every guess the game ever offers, in the order its stages first offer them."""
    out: list[str] = []
    for stage in rules.stages:
        out += [g for g in stage.guesses if g not in out]
    return out


def system_prompt(rules: GameSpec, json_reply: bool = False) -> str:
    red = " and ".join(SUIT_NAMES[s] for s in sorted(RED_SUITS))
    parts = [
        f"You are playing {rules.name}, a card game. Each of your decisions is graded against "
        "perfect play, so play to get the most back on average over many rounds, not for the "
        "biggest possible win in this one.",
        "",
        f"The rules: {describe(rules)}",
        "",
        "Cards are written as rank then suit: 2 to 10, J, Q, K, A, then h (hearts), d "
        "(diamonds), c (clubs) or s (spades). So 10d is the ten of diamonds and As the ace of "
        f"spades. {red.capitalize()} are red; clubs and spades are black.",
        "",
        "Each message describes one decision: the cards on the table, the question, the legal "
        "moves, and what cashing out pays. Only the legal moves listed in the message count.",
    ]
    if json_reply:
        parts += [
            "",
            "Reply with one JSON object and nothing else, in this form: "
            '{"move": "<one legal move; cash to cash out>", "win_probability": <your '
            "probability from 0 to 1 that your guess wins, or null when you cash out>, "
            '"reason": "<one short sentence>"}',
        ]
    else:
        parts += [
            "",
            f"Answer by calling exactly one tool: {GUESS_TOOL} to make a guess (with your "
            "probability, from 0 to 1, that the guess wins, and a one-sentence reason), or "
            f"{CASH_TOOL} to stop and take the cash-out value.",
        ]
    parts += [
        "",
        "A guess wins only if the round goes on (or pays) because of it: a tie that loses or "
        "pushes is not a win.",
    ]
    return "\n".join(parts)


def tool_schemas(rules: GameSpec) -> list[tuple[str, str, dict[str, Any]]]:
    """(name, description, JSON schema) for the two tools, the same for every decision."""
    reason = {"type": "string", "description": "One short sentence: why."}
    guess = {
        "type": "object",
        "properties": {
            "choice": {
                "type": "string",
                "enum": all_guesses(rules),
                "description": "Your guess. Use one of the legal moves listed in the message.",
            },
            "win_probability": {
                "type": "number",
                "description": "Your probability, from 0 to 1, that this guess wins.",
            },
            "reason": reason,
        },
        "required": ["choice", "win_probability", "reason"],
        "additionalProperties": False,
    }
    cash = {
        "type": "object",
        "properties": {"reason": reason},
        "required": ["reason"],
        "additionalProperties": False,
    }
    return [
        (GUESS_TOOL, "Make a guess for the current stage.", guess),
        (
            CASH_TOOL,
            "Stop now and take the cash-out value from the message (before the first guess, "
            "when the game allows it, this means walking away with your bet).",
            cash,
        ),
    ]


def _cards(cards: Sequence[Card]) -> str:
    return ", ".join(card_name(c) for c in cards)


def user_message(obs: Observation, rules: GameSpec) -> str:
    """The situation for one decision."""
    lines = [f"Stage {obs.stage} of {obs.stages}: {obs.question.lower()}."]
    if obs.seen:
        lines.append(f"Cards on the table, in the order dealt: {_cards(obs.seen)}.")
    else:
        lines.append("No cards are on the table yet.")
    if obs.compare:
        lines.append(f"This guess is judged against: {_cards(obs.compare)}.")
    if rules.deck_model != "with_replacement":
        left = len(rules.ranks) * 4 * rules.effective_decks - len(obs.seen)
        lines.append(f"Cards left in the deck: {left}.")
    cash = ", or cash out" if obs.can_cash_out else " (cashing out is not allowed yet)"
    lines.append(f"Legal moves: {', '.join(obs.options)}{cash}.")
    after = rules.cash_value(obs.stage)
    if obs.can_cash_out and obs.stage > 1:
        lines.append(
            f"Cashing out now pays {fmt.ret(obs.cash_value)} per 1 bet. If your guess wins, "
            f"you can then cash out for {fmt.ret(after)} or play on; if it loses, you get "
            "nothing."
        )
    elif obs.can_cash_out:
        lines.append(
            "You can walk away now and keep your bet (cash). If you guess and win, you can "
            f"cash out for {fmt.ret(after)} or play on; if you lose, the bet is gone."
        )
    else:
        lines.append(
            "Your bet is in, so you must guess. If you win, you can cash out for "
            f"{fmt.ret(after)} or play on; if you lose, the bet is gone."
        )
    if obs.feedback:
        lines.append(f"Your previous answer was rejected: {obs.feedback}. Answer again.")
    return "\n".join(lines)


def _probability(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise AgentError(f"win_probability should be a number from 0 to 1, not {value!r}")
    try:
        return float(value)
    except ValueError:
        raise AgentError(f"win_probability should be a number from 0 to 1, not {value!r}") from None


def to_action(tool: str, args: Any, raw: str, meta: dict[str, Any]) -> Action:
    """A tool call as a move. The arena checks the move is legal and the probability in range."""
    if not isinstance(args, dict):
        raise AgentError("the tool arguments were not an object", raw=raw, meta=meta)
    reason = str(args.get("reason", ""))[:500]
    if tool == CASH_TOOL:
        return Action(CASH, None, reason, raw, meta)
    if tool != GUESS_TOOL:
        raise AgentError(f"there is no tool called {tool!r}", raw=raw, meta=meta)
    choice = args.get("choice")
    if not isinstance(choice, str):
        raise AgentError(f"{GUESS_TOOL} needs a choice", raw=raw, meta=meta)
    try:
        p = _probability(args.get("win_probability"))
    except AgentError as exc:
        raise AgentError(str(exc), raw=raw, meta=meta) from None
    return Action(choice.strip().lower(), p, reason, raw, meta)


def from_json_reply(text: str, meta: dict[str, Any]) -> Action:
    """A plain-text reply holding a JSON object: {"move": ..., "win_probability": ..., ...}."""
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and ("move" in obj or "choice" in obj):
            move = str(obj.get("move", obj.get("choice", ""))).strip().lower()
            if move in ("cash", "cash out", "cash_out", "stop", "walk away"):
                return Action(CASH, None, str(obj.get("reason", ""))[:500], text, meta)
            args = {**obj, "choice": move}
            return to_action(GUESS_TOOL, args, text, meta)
    raise AgentError("no JSON object with a move in the reply", raw=text[:500], meta=meta)
