"""Where busride keeps your settings and data, and what the settings are.

Everything lives in your user folders (from platformdirs), so busride works from any folder with
nothing to set up. Set BUSRIDE_HOME to keep everything in one folder instead (handy for tests and
for carrying busride on a USB stick).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import platformdirs

COACH_LEVELS = ("off", "hints", "review", "explain")
DEFAULT_GAME = "ride-the-bus"
DEFAULT_AI = "claude"  # claude-opus-5-5
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def config_dir() -> Path:
    home = os.environ.get("BUSRIDE_HOME")
    return Path(home) / "config" if home else Path(platformdirs.user_config_dir("busride", False))


def data_dir() -> Path:
    home = os.environ.get("BUSRIDE_HOME")
    return Path(home) / "data" if home else Path(platformdirs.user_data_dir("busride", False))


def settings_file() -> Path:
    return config_dir() / "config.toml"


def games_dir() -> Path:
    """Your own games, one .toml file each (made by `busride games new` or `busride init`)."""
    return config_dir() / "games"


def runs_dir() -> Path:
    """Arena runs, one .jsonl file each."""
    return data_dir() / "runs"


ENV_FROM: dict[str, Path] = {}  # variables busride set from a .env file, and which file


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines (quotes, `export` and # comments allowed). Values stay in memory only."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key.isidentifier():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def env_files() -> list[Path]:
    """Where API keys may be kept: .env in this folder, then .env in your settings folder."""
    return [Path(".env"), config_dir() / ".env"]


def load_env_files(paths: list[Path] | None = None) -> dict[str, Path]:
    """Set the variables in .env files that aren't set already (your terminal's win).
    Returns what was set, by name, with the file it came from."""
    for path in env_files() if paths is None else paths:
        if not path.is_file():
            continue
        try:
            values = read_env_file(path)
        except (OSError, UnicodeDecodeError):
            continue
        for key, value in values.items():
            if value and not os.environ.get(key):
                os.environ[key] = value
                ENV_FROM[key] = path
    return dict(ENV_FROM)


def ollama_url() -> str:
    """Where Ollama listens: OLLAMA_HOST, else http://localhost:11434."""
    host = os.environ.get("OLLAMA_HOST", "").strip().rstrip("/") or "http://localhost:11434"
    return host if "://" in host else f"http://{host}"


def rounds_db() -> Path:
    """The logged rounds: ./rounds.db if you logged in this folder before, else your data folder."""
    here = Path("rounds.db")
    return here if here.exists() else data_dir() / "rounds.db"


@dataclass(frozen=True)
class Settings:
    game: str = DEFAULT_GAME  # a built-in game, one of your games, or a .toml path
    coach: str = "review"
    chips: int = 1000
    stake: float = 10.0
    payouts: dict[str, tuple[float, ...]] = field(default_factory=dict)  # your ladder per game
    ai: str = DEFAULT_AI  # the AI model `--agents ai` means
    effort: str = "medium"  # how hard Claude thinks, when the agent name doesn't say
    coach_ai: str = ""  # an AI model to phrase the coach's explanations; "" = the template
    problem: str = ""  # why the settings file was ignored, if it was

    def with_payouts(self, game: str, ladder: tuple[float, ...] | None) -> Settings:
        payouts = dict(self.payouts)
        if ladder is None:
            payouts.pop(game, None)
        else:
            payouts[game] = tuple(ladder)
        return replace(self, payouts=payouts)


def _parse(data: dict[str, Any]) -> Settings:
    base = Settings()
    coach = data.get("coach", base.coach)
    if coach not in COACH_LEVELS:
        raise ValueError(f"coach = {coach!r}: use one of {', '.join(COACH_LEVELS)}")
    chips, stake = data.get("chips", base.chips), data.get("stake", base.stake)
    if not isinstance(chips, int) or chips <= 0 or not isinstance(stake, int | float) or stake <= 0:
        raise ValueError("chips and stake must be positive numbers")
    payouts: dict[str, tuple[float, ...]] = {}
    for name, ladder in dict(data.get("payouts", {})).items():
        if not isinstance(ladder, list) or not all(isinstance(r, int | float) for r in ladder):
            raise ValueError(f"payouts for {name!r} must be a list of numbers")
        payouts[str(name)] = tuple(float(r) for r in ladder)
    effort = data.get("effort", base.effort)
    if effort not in EFFORTS:
        raise ValueError(f"effort = {effort!r}: use one of {', '.join(EFFORTS)}")
    return Settings(
        game=str(data.get("game", base.game)),
        coach=str(coach),
        chips=chips,
        stake=float(stake),
        payouts=payouts,
        ai=str(data.get("ai", base.ai)),
        effort=str(effort),
        coach_ai=str(data.get("coach_ai", base.coach_ai)),
    )


def load_settings() -> Settings:
    """Your settings, or the defaults. A broken file is ignored (and reported), never fatal."""
    path = settings_file()
    if not path.exists():
        return Settings()
    try:
        return _parse(tomllib.loads(path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
        return Settings(problem=f"{path} was ignored: {exc}")


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_settings(settings: Settings) -> Path:
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# busride settings. Change them with `busride settings`, or edit this file.",
        f"game = {_q(settings.game)}",
        f"# How much the coach says while you play: {' | '.join(COACH_LEVELS)}",
        f"coach = {_q(settings.coach)}",
        "# Fake chips to start a play session with, and the stake per round.",
        f"chips = {settings.chips}",
        f"stake = {settings.stake!r}",
        "# The AI model `--agents ai` plays: claude, claude:MODEL, ollama:MODEL, openai:MODEL...",
        f"ai = {_q(settings.ai)}",
        f"# How hard Claude thinks: {' | '.join(EFFORTS)}",
        f"effort = {_q(settings.effort)}",
        "# An AI model that rewords the coach's explanations (empty: busride's own wording).",
        f"coach_ai = {_q(settings.coach_ai)}",
        "",
        "# Your own payout ladder for a game, replacing its default.",
        "[payouts]",
    ]
    for name, ladder in sorted(settings.payouts.items()):
        lines.append(f"{_q(name)} = [{', '.join(repr(float(r)) for r in ladder)}]")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
