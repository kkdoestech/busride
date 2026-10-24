"""M2: the commands work with every built-in game and with game files."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride.cli import app

runner = CliRunner()
GAMES = ["ride-the-bus", "hi-lo-5", "in-between", "colour-run-5"]


def run(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, [*args, "--plain"], input=input)
    assert result.exit_code == 0, result.output
    return result.output


def test_games_lists_every_built_in() -> None:
    out = run("games")
    for name in GAMES:
        assert name in out


def test_games_shows_one_game() -> None:
    out = run("games", "hi-lo-5")
    assert "higher or lower ×5" in out and "1.20x" in out
    assert "busride odds --game hi-lo-5" in out and "busride games use hi-lo-5" in out


@pytest.mark.parametrize("game", GAMES)
def test_analyze_and_policy_for_every_game(game: str) -> None:
    assert "HOUSE EDGE" in run("analyze", "--game", game)
    assert "Stage 1" in run("policy", "--game", game)


def test_advise_in_hi_lo() -> None:
    out = run("advise", "7h", "--game", "hi-lo-5")
    assert "Stage 1 of 5" in out and "28/51" in out
    assert "Your stake is in" in out


def test_advise_waits_for_a_shown_card() -> None:
    out = run("advise", "--game", "in-between", input="3h\nJs\nq\n")
    assert "Card 1 is shown with no guess" in out
    assert "Card 2 is shown with no guess" in out
    assert "Stage 1 of 1" in out and "INSIDE" in out


def test_ladder_presets_on_the_command_line() -> None:
    assert "PLAYER EDGE" in run("analyze", "--game", "ride-the-bus", "--ladder", "classic")
    fair = run("analyze", "--game", "hi-lo-5", "--ladder", "fair")
    assert "PLAYER EDGE" in fair  # perfect stopping beats the fair fixed plan


def test_bad_game_and_ladder_explain_themselves() -> None:
    result = runner.invoke(app, ["analyze", "--game", "poker", "--plain"])
    assert result.exit_code == 1 and "hi-lo-5" in result.output
    result = runner.invoke(app, ["analyze", "--game", "hi-lo-5", "--ladder", "2,3", "--plain"])
    assert result.exit_code == 1 and "needs 5 returns" in result.output


def test_sim_on_another_game() -> None:
    out = run("sim", "--game", "colour-run-5", "-n", "3000", "--seed", "2", "--strategy", "stop:3")
    assert "SIMULATED RTP" in out and "5 Red or black" in out
    result = runner.invoke(app, ["sim", "--game", "hi-lo-5", "--strategy", "stop:9", "--plain"])
    assert result.exit_code == 1 and "stop:5" in result.output


def test_sim_records_only_ride_the_bus(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["sim", "--game", "hi-lo-5", "-n", "10", "--record", str(tmp_path / "x.db"), "--plain"]
    )
    assert result.exit_code == 1 and "Ride the Bus only" in result.output


def test_a_game_file_on_the_command_line(tmp_path: Path) -> None:
    path = tmp_path / "two-colours.toml"
    path.write_text(
        '[game]\nname = "Two Colours"\n\n[[stage]]\ntype = "colour"\n\n[[stage]]\n'
        'type = "colour"\n\n[payout]\nladder = [1.9, 3.7]\n',
        encoding="utf-8",
    )
    out = run("analyze", "--game", str(path))
    assert "Two Colours" in out
    assert "Stage 2" in run("policy", "--game", str(path))
