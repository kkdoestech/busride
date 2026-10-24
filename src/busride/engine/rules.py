"""Game files (TOML): reading, writing and sanity-checking them.

A file with no [[stage]] tables is Ride the Bus, so the original rules.toml keeps working.
The engine never hard-codes a guess about the game: everything comes from here.
"""

from __future__ import annotations

import tomllib
from itertools import pairwise
from pathlib import Path
from typing import Any

from busride.engine.cards import DECK_MODELS, RANKS
from busride.engine.game import PLACEHOLDER_VERSION as PLACEHOLDER_VERSION
from busride.engine.game import RIDE_THE_BUS, GameSpec, Stage, make_stages
from busride.engine.game import RulesError as RulesError

ACE_RULES = ("high", "low", "either")
TIE_RULES = ("lose", "push", "win")
TIMEOUT_RULES = ("unknown", "lose", "cash_out", "random_guess")
BUILT_IN_VERSION = "built-in"

_KNOWN_KEYS = {
    "game": {
        "name",
        "game_version",
        "captured_on",
        "min_stake",
        "max_stake",
        "timeout",
        "forced_first_bet",
        "description",
    },
    "deck": {"model", "decks", "ace", "ranks"},
    "ties": {"higher_lower", "range_edge"},
    "payout": {"return_after_stage", "ladder"},
}
_STAGE_KEYS = {"type", "against", "between"}

# The name predates other games; it stays as an alias of GameSpec.
Rules = GameSpec


def _choice(value: Any, allowed: tuple[str, ...], where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RulesError(f"{where} = {value!r}: expected one of {', '.join(allowed)}")
    return value


def _number(value: Any, where: str, *, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RulesError(f"{where} = {value!r}: expected a number")
    if value < 0:
        raise RulesError(f"{where} = {value!r}: cannot be negative")
    return float(value)


def parse_ladder(text: str, count: int = 4) -> tuple[float, ...]:
    """Read returns typed as '2, 2.7, 4.1, 15' or '2 2.7 4.1 15'."""
    parts = [p for p in text.replace(",", " ").split() if p]
    if len(parts) != count:
        raise RulesError(f"the ladder needs {count} returns, got {len(parts)}: {text!r}")
    try:
        values = tuple(float(p.rstrip("xX")) for p in parts)
    except ValueError as exc:
        raise RulesError(f"the ladder must be numbers, like 2,2.7,4.1,15 ({exc})") from None
    if any(v < 0 for v in values):
        raise RulesError("ladder returns cannot be negative")
    return values


def _parse_stages(data: dict[str, Any]) -> tuple[tuple[Stage, ...], list[str]]:
    raw = data.get("stage")
    if raw is None:
        return RIDE_THE_BUS, []
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise RulesError("each [[stage]] must be a table with a type")
    items: list[str | tuple[str, list[int]]] = []
    unknown: list[str] = []
    for i, table in enumerate(raw, start=1):
        kind = table.get("type")
        if not isinstance(kind, str):
            raise RulesError(
                f'stage {i} has no type: add type = "colour" (or higher_lower, '
                "inside_outside, suit, reveal)"
            )
        refs = table.get({"higher_lower": "against", "inside_outside": "between"}.get(kind, ""))
        if refs is None:
            items.append(kind)
        else:
            refs = [refs] if isinstance(refs, int) and not isinstance(refs, bool) else refs
            if not isinstance(refs, list) or not all(
                isinstance(r, int) and not isinstance(r, bool) for r in refs
            ):
                raise RulesError(f"stage {i}: 'against' and 'between' take stage numbers")
            items.append((kind, refs))
        unknown += [f"stage[{i}].{k}" for k in table if k not in _STAGE_KEYS]
    return make_stages(items), unknown


def parse_rules(data: dict[str, Any], source: str = "rules.toml") -> GameSpec:
    """Turn parsed TOML into a GameSpec, with a precise message for every bad value."""
    game = data.get("game", {})
    deck = data.get("deck", {})
    ties = data.get("ties", {})
    payout = data.get("payout", {})
    for section in (game, deck, ties, payout):
        if not isinstance(section, dict):
            raise RulesError("each of [game], [deck], [ties], [payout] must be a table")

    stages, unknown = _parse_stages(data)
    unknown = [s for s in data if s not in _KNOWN_KEYS and s != "stage"] + unknown
    for section, keys in _KNOWN_KEYS.items():
        table = data.get(section, {})
        unknown += [f"{section}.{k}" for k in table if k not in keys]

    guesses = sum(1 for s in stages if s.is_guess)
    key = "ladder" if "ladder" in payout else "return_after_stage"
    returns = payout.get(key, [0.0] * guesses)
    if not isinstance(returns, list):
        raise RulesError(f"payout.{key} must be a list of {guesses} numbers")
    ladder = tuple(float(_number(r, f"payout.{key}[{i}]") or 0.0) for i, r in enumerate(returns))

    decks = deck.get("decks", 1)
    if isinstance(decks, bool) or not isinstance(decks, int) or decks < 1:
        raise RulesError(f"deck.decks = {decks!r}: expected a whole number of at least 1")
    ranks = deck.get("ranks", list(RANKS))
    if not isinstance(ranks, list) or not all(isinstance(r, int) for r in ranks):
        raise RulesError("deck.ranks must be a list of ranks from 2 to 14 (14 = ace)")
    forced = game.get("forced_first_bet", True)
    if not isinstance(forced, bool):
        raise RulesError(f"game.forced_first_bet = {forced!r}: expected true or false")

    return GameSpec(
        name=str(game.get("name", GameSpec.name)),
        game_version=str(game.get("game_version", PLACEHOLDER_VERSION)),
        captured_on=str(game.get("captured_on", "")),
        deck_model=_choice(deck.get("model", "fresh_52"), DECK_MODELS, "deck.model"),
        decks=decks,
        ace=_choice(deck.get("ace", "high"), ACE_RULES, "deck.ace"),
        tie_higher_lower=_choice(ties.get("higher_lower", "lose"), TIE_RULES, "ties.higher_lower"),
        tie_range_edge=_choice(ties.get("range_edge", "lose"), TIE_RULES, "ties.range_edge"),
        returns=ladder,
        # 0 in the file means "not recorded"
        min_stake=_number(game.get("min_stake"), "game.min_stake", allow_none=True) or None,
        max_stake=_number(game.get("max_stake"), "game.max_stake", allow_none=True) or None,
        timeout=_choice(game.get("timeout", "unknown"), TIMEOUT_RULES, "game.timeout"),
        source=source,
        unknown_keys=tuple(unknown),
        stages=stages,
        forced_first_bet=forced,
        ranks=tuple(sorted(set(ranks))),
        description=str(game.get("description", "")),
    )


def load_rules(path: str | Path) -> GameSpec:
    p = Path(path)
    if not p.exists():
        raise RulesError(f"no rules file at {p}. Run `busride init` to capture the rules first")
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RulesError(f"{p} is not valid TOML: {exc}") from None
    return parse_rules(data, source=str(path))


def static_warnings(rules: GameSpec, include_ladder: bool = True) -> list[str]:
    """Odd values that need no solving to spot."""
    out: list[str] = []
    if not rules.ladder_captured:
        if include_ladder:
            out.append(
                f"The payout ladder is empty: set the {rules.guess_count} returns of the game "
                "you play."
            )
    else:
        r = rules.returns
        if any(b < a for a, b in pairwise(r)):
            out.append("The ladder goes down at some stage: returns should grow as you survive.")
        if 0 < r[0] <= 1.0:
            out.append("Cashing out after stage 1 pays no more than the stake.")
    if rules.game_version != BUILT_IN_VERSION:
        if rules.game_version.strip() in ("", PLACEHOLDER_VERSION):
            out.append("No game version recorded: results cannot be tied to a game update.")
        if not rules.captured_on:
            out.append("No capture date recorded.")
    if rules.deck_model != "shoe" and rules.decks != 1:
        out.append(f'deck.decks = {rules.decks} is ignored unless deck.model = "shoe".')
    if rules.deck_model == "shoe" and rules.decks == 1:
        out.append("A one-deck shoe is the same as fresh_52.")
    if (
        rules.min_stake is not None
        and rules.max_stake is not None
        and rules.min_stake > rules.max_stake
    ):
        out.append("min_stake is larger than max_stake.")
    for key in rules.unknown_keys:
        out.append(f"Unknown key '{key}' is ignored: check the spelling.")
    return out


def _toml_value(v: float | None) -> str:
    return "0" if v is None else repr(float(v))


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _stage_tables(stages: tuple[Stage, ...]) -> str:
    out = []
    for i, stage in enumerate(stages):
        lines = ["[[stage]]", f'type = "{stage.kind}"']
        # the comparison make_stages picks when none is given: the card(s) just before
        default = {"higher_lower": (i - 1,), "inside_outside": (i - 2, i - 1)}.get(stage.kind, ())
        if stage.refs != default:
            numbers = [r + 1 for r in stage.refs]
            if stage.kind == "higher_lower":
                lines.append(f"against = {numbers[0]}")
            else:
                lines.append(f"between = [{', '.join(map(str, numbers))}]")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def dump_rules(rules: GameSpec) -> str:
    """Game-file text, with comments that explain each field.

    Ride the Bus on a full deck keeps the original rules.toml layout; any other game lists its
    stages as [[stage]] tables.
    """
    ladder = ", ".join(_toml_value(r) for r in rules.returns)
    classic = rules.stages == RIDE_THE_BUS and rules.ranks == RANKS and rules.forced_first_bet
    extra_game = ""
    if rules.description:
        extra_game += f'description = "{_esc(rules.description)}"\n'
    if not classic:
        extra_game += (
            "# true: the first guess must be played; false: you may walk away before it\n"
            f"forced_first_bet = {'true' if rules.forced_first_bet else 'false'}\n"
        )
    ranks = ""
    if rules.ranks != RANKS:
        ranks = (
            "# Ranks in the deck (14 = ace); leave out for a full deck.\n"
            f"ranks = [{', '.join(map(str, rules.ranks))}]\n"
        )
    if classic:
        payout = (
            "# Total payout per 1 staked, stake included, if you cash out after surviving each "
            f"stage.\nreturn_after_stage = [{ladder}]\n"
        )
        stages = ""
    else:
        payout = (
            "# Total payout per 1 staked, stake included, for cashing out after each guessing\n"
            f"# stage (reveal stages don't count).\nladder = [{ladder}]\n"
        )
        stages = (
            "\n# The stages, in order: colour | higher_lower | inside_outside | suit | reveal.\n"
            "# higher_lower compares with the previous card unless `against = N`; inside_outside\n"
            "# with the two previous cards unless `between = [A, B]` (stage numbers).\n"
            + _stage_tables(rules.stages)
            + "\n"
        )

    return f"""\
# busride game rules. Set these to match the game you play (docs/SPEC.md, section 5),
# then run `busride odds`.

[game]
name = "{_esc(rules.name)}"
game_version = "{_esc(rules.game_version)}"
captured_on = "{_esc(rules.captured_on)}"
{extra_game}# Stake limits; 0 = not recorded.
min_stake = {_toml_value(rules.min_stake)}
max_stake = {_toml_value(rules.max_stake)}
# What a draw that runs out of time does: unknown | lose | cash_out | random_guess
timeout = "{rules.timeout}"

[deck]
# fresh_52 (new deck every round) | with_replacement (cards can repeat) | shoe
model = "{rules.deck_model}"
# Only used by "shoe".
decks = {rules.decks}
# high | low | either (either = whichever value helps you)
ace = "{rules.ace}"
{ranks}
[ties]
# lose | push | win. A push ends the round and pays your current cash-out value.
higher_lower = "{rules.tie_higher_lower}"
# The same, for a card equal to either end of the inside/outside range.
range_edge = "{rules.tie_range_edge}"
{stages}
[payout]
{payout}"""
