from pathlib import Path

import pytest

from busride.engine.rules import Rules
from busride.engine.solver import survival

# Fresh 52-card deck, ace high, ties lose: the baseline the spec's numbers assume.
BASE = Rules(game_version="test", captured_on="2026-10-23", source="rules.toml")
FAIR_LADDER = tuple(1 / s for s in survival(BASE))


@pytest.fixture(autouse=True)
def private_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own settings and data folders, never the real ones."""
    home = tmp_path / "busride-home"
    monkeypatch.setenv("BUSRIDE_HOME", str(home))
    return home


@pytest.fixture
def base_rules() -> Rules:
    return BASE


@pytest.fixture
def fair_rules() -> Rules:
    return BASE.with_returns(FAIR_LADDER)
