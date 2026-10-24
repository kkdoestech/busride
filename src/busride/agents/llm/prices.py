"""What AI model calls cost, from a dated table you can edit.

Prices are US dollars per million tokens. The built-in table holds Anthropic's list prices on the
date below; `busride arena prices` writes it to your config folder (prices.toml), where you can
correct it or add other providers' models. A model missing from the table has an unknown cost,
and busride says so instead of guessing.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from busride import config

AS_OF = "2026-10-06 (Claude), 2026-10-24 (DeepSeek, peak hours)"
SOURCE = (
    "https://platform.claude.com/docs/en/about-claude/pricing and "
    "https://api-docs.deepseek.com/quick_start/pricing"
)
CACHE_WRITE = 1.25  # a 5-minute cache write costs 1.25x the input price
CACHE_READ = 0.1  # assumed when a model's cache-read price isn't in the table


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None

    def cost(
        self, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
    ) -> float:
        read = self.cache_read if self.cache_read is not None else self.input * CACHE_READ
        write = self.cache_write if self.cache_write is not None else self.input * CACHE_WRITE
        return (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_read * read
            + cache_write * write
        ) / 1_000_000


BUILT_IN: dict[str, Price] = {
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-5": Price(5.0, 25.0),
    "claude-opus-4-8": Price(5.0, 25.0),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.20),
    "claude-haiku-5-5": Price(0.10, 0.50),
    "claude-fable-5-1": Price(10.0, 50.0, 0.25),
    # DeepSeek's peak-hour prices (off-peak is half), so estimates err on the high side. A cache
    # miss costs the input price: there is no extra charge for writing the cache.
    "deepseek:deepseek-flash": Price(0.30, 1.20, 0.006, 0.30),
    "deepseek:deepseek-v4-flash": Price(0.30, 1.20, 0.006, 0.30),
    "deepseek:deepseek-v4-pro": Price(1.32, 3.96, 0.044, 1.32),
}


def prices_file() -> Path:
    return config.config_dir() / "prices.toml"


@dataclass(frozen=True)
class PriceTable:
    prices: dict[str, Price]
    as_of: str
    source: str  # where the table came from: "built in" or the file

    def get(self, model: str) -> Price | None:
        """By exact name ("claude-opus-5-5", "openai:gpt-x"), else without the provider."""
        return self.prices.get(model) or self.prices.get(model.split(":", 1)[-1])


def load_prices(path: Path | None = None) -> PriceTable:
    """Your prices.toml if you have one (it replaces the built-in table), else the built-in."""
    path = path or prices_file()
    if not path.exists():
        return PriceTable(dict(BUILT_IN), AS_OF, "built in")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return PriceTable(dict(BUILT_IN), AS_OF, f"built in ({path} could not be read)")
    table: dict[str, Price] = {}
    for name, entry in data.get("models", {}).items():
        if not isinstance(entry, dict):
            continue
        try:
            table[name] = Price(
                float(entry["input"]),
                float(entry["output"]),
                float(entry["cache_read"]) if "cache_read" in entry else None,
                float(entry["cache_write"]) if "cache_write" in entry else None,
            )
        except (KeyError, TypeError, ValueError):
            continue
    return PriceTable(table, str(data.get("as_of", "?")), str(path))


def dump_prices(table: PriceTable) -> str:
    lines = [
        "# busride: what AI model calls cost, in US dollars per million tokens.",
        f"# Checked on as_of against {SOURCE}; edit to match today's prices.",
        "# cache_read / cache_write may be left out: busride then assumes 0.1x and 1.25x input.",
        '# Add other providers\' models by name, for example [models."openai:MODEL"].',
        "# Local models (ollama:, lmstudio:) and OpenRouter :free models are always free;",
        "# give any other model input = 0 and output = 0 to mark it free (a free tier).",
        f'as_of = "{table.as_of}"',
        "",
    ]
    for name, p in table.prices.items():
        lines.append(f'[models."{name}"]')
        lines.append(f"input = {p.input!r}")
        lines.append(f"output = {p.output!r}")
        if p.cache_read is not None:
            lines.append(f"cache_read = {p.cache_read!r}")
        if p.cache_write is not None:
            lines.append(f"cache_write = {p.cache_write!r}")
        lines.append("")
    return "\n".join(lines)
