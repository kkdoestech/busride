"""The games busride knows out of the box, and loading a game by name or file."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from busride.engine.game import RIDE_THE_BUS, GameSpec, RulesError, make_stages
from busride.engine.rules import BUILT_IN_VERSION, load_rules
from busride.engine.solver import survival


def _builtin(
    key: str, name: str, kinds: list[str], returns: tuple[float, ...], description: str
) -> GameSpec:
    return GameSpec(
        name=name,
        game_version=BUILT_IN_VERSION,
        source=f"built-in {key}",
        stages=RIDE_THE_BUS if key == "ride-the-bus" else make_stages(kinds),
        returns=returns,
        description=description,
    )


BUILTIN_GAMES: dict[str, GameSpec] = {
    "ride-the-bus": _builtin(
        "ride-the-bus",
        "Ride the Bus",
        ["colour", "higher_lower", "inside_outside", "suit"],
        (1.8, 2.3, 3.2, 12.0),
        "Red or black, higher or lower, inside or outside, then the suit.",
    ),
    "hi-lo-5": _builtin(
        "hi-lo-5",
        "Hi-Lo 5",
        ["reveal"] + ["higher_lower"] * 5,
        (1.2, 1.6, 2.2, 3.0, 4.2),
        "One card is shown, then five higher-or-lower calls, each against the card before.",
    ),
    "in-between": _builtin(
        "in-between",
        "In-Between",
        ["reveal", "reveal", "inside_outside"],
        (1.4,),
        "Two cards are shown; bet whether the third lands between them or outside. "
        "A simplified Acey-Deucey with one fixed payout.",
    ),
    "colour-run-5": _builtin(
        "colour-run-5",
        "Colour Run 5",
        ["colour"] * 5,
        (1.9, 3.8, 7.5, 15.0, 29.0),
        "Five red-or-black calls in a row. Remembering the colours already seen helps.",
    ),
}

# Named ladders a game can be tried with: --ladder classic
PRESETS: dict[str, dict[str, tuple[float, ...]]] = {
    "ride-the-bus": {
        "house": (1.8, 2.3, 3.2, 12.0),
        "classic": (2.0, 3.0, 4.0, 20.0),  # round numbers that look fair, and aren't
    },
}


def builtin_name(spec: GameSpec) -> str | None:
    """The built-in game with this game's shape (its stages and deck), if any."""
    return next(
        (
            name
            for name, g in BUILTIN_GAMES.items()
            if g.stages == spec.stages and g.ranks == spec.ranks
        ),
        None,
    )


def load_game(name_or_path: str, search: Sequence[Path] = ()) -> GameSpec:
    """A game by name or file: a built-in (ride-the-bus, hi-lo-5, ...), one of your games
    (NAME.toml in a `search` folder), or the path of a .toml game file."""
    if name_or_path in BUILTIN_GAMES:
        return BUILTIN_GAMES[name_or_path]
    for folder in search:
        candidate = folder / f"{name_or_path}.toml"
        if candidate.exists():
            return replace(load_rules(candidate), source=f"your game {name_or_path}")
    path = Path(name_or_path)
    if path.suffix.lower() == ".toml" or path.exists():
        return load_rules(path)
    names = ", ".join(BUILTIN_GAMES)
    raise RulesError(
        f"there is no game called {name_or_path!r}: try one of {names}, or a .toml file"
    )


def your_games(folder: Path) -> dict[str, GameSpec | RulesError]:
    """The games in your games folder, by name. A file that doesn't load maps to its error."""
    out: dict[str, GameSpec | RulesError] = {}
    if not folder.exists():
        return out
    for path in sorted(folder.glob("*.toml")):
        try:
            out[path.stem] = replace(load_rules(path), source=f"your game {path.stem}")
        except RulesError as exc:
            out[path.stem] = exc
    return out


def slug(name: str) -> str:
    """A file-friendly game name: 'My Hi-Lo 7' -> 'my-hi-lo-7'."""
    out = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return out or "my-game"


def resolve_ladder(text: str, spec: GameSpec) -> tuple[float, ...]:
    """A ladder typed as numbers ('2, 2.7, 4.1, 15'), or a preset name: house, classic, fair."""
    word = text.strip().lower()
    presets = PRESETS.get(builtin_name(spec) or "", {})
    if word == "fair":
        return tuple(1.0 / s for s in survival(spec))
    if word == "house" and builtin_name(spec):
        return BUILTIN_GAMES[builtin_name(spec) or ""].returns
    if word in presets:
        return presets[word]
    if re.fullmatch(r"[a-z]+", word):
        known = ", ".join(["fair", "house", *[p for p in presets if p != "house"]])
        raise RulesError(f"no ladder called {word!r} for {spec.name}: try {known}, or numbers")
    parts = [p for p in text.replace(",", " ").split() if p]
    need = spec.guess_count
    if len(parts) != need:
        raise RulesError(f"{spec.name} needs {need} returns, got {len(parts)}: {text!r}")
    try:
        values = tuple(float(p.rstrip("xX")) for p in parts)
    except ValueError:
        raise RulesError(f"the ladder must be numbers, like {', '.join(['2'] * need)}") from None
    if any(v < 0 for v in values):
        raise RulesError("ladder returns cannot be negative")
    return values
