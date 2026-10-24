"""The example games in examples/ load, solve, and return what examples/README.md says."""

from pathlib import Path

import pytest

from busride.engine.builtins import load_game
from busride.engine.rules import static_warnings
from busride.engine.solver import solve

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
RETURNS = {
    "ride-the-bus-rules": 0.963,
    "short-deck": 0.961,
    "two-deck-shoe": 0.961,
    "first-card-high-low": 0.961,
    "in-between-walkaway": 1.399,
}


def test_every_example_is_listed() -> None:
    assert {p.stem for p in EXAMPLES.glob("*.toml")} == set(RETURNS)
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    assert all(f"`{name}.toml`" in readme for name in RETURNS)


@pytest.mark.parametrize("name", list(RETURNS))
def test_example_solves_to_its_documented_return(name: str) -> None:
    spec = load_game(str(EXAMPLES / f"{name}.toml"))
    assert not spec.unknown_keys
    assert solve(spec).rtp == pytest.approx(RETURNS[name], abs=0.0006)
    assert not [w for w in static_warnings(spec) if "Unknown key" in w]


def test_the_example_arena_run_reads_as_the_readme_says() -> None:
    from busride.arena.runs import RunFile
    from busride.arena.scoring import score

    boards = score(RunFile(EXAMPLES / "arena-example.jsonl"))
    assert list(boards)[:3] == ["optimal", "deepseek:deepseek-flash", "rl:q-ride-the-bus"]
    deepseek = boards["deepseek:deepseek-flash"]
    assert deepseek.given_up_per_deal == pytest.approx(0, abs=1e-12) and deepseek.deals == 30
    assert boards["ollama:qwen3:4b-instruct"].given_up_per_deal == pytest.approx(0.632, abs=0.001)
