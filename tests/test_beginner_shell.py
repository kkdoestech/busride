"""M3: the beginner shell. Settings live in the user folder, there is always a current game, and
`busride` alone opens a menu (or prints help when it isn't attached to a terminal)."""

import io
from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride import config
from busride.cli import app, run_menu
from busride.ui.theme import make_ui

runner = CliRunner()


def run(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, [*args, "--plain"], input=input)
    assert result.exit_code == 0, result.output
    return result.output


@pytest.fixture(autouse=True)
def elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run from an empty folder, as a first-time user would."""
    folder = tmp_path / "anywhere"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


# ── settings ─────────────────────────────────────────────────────────────────────────────


def test_settings_default_then_round_trip(private_home: Path) -> None:
    assert config.load_settings() == config.Settings()
    saved = config.Settings(game="hi-lo-5", coach="hints", chips=500, stake=5.0).with_payouts(
        "ride-the-bus", (2.0, 3.0, 4.0, 20.0)
    )
    path = config.save_settings(saved)
    assert path.is_relative_to(private_home)
    assert config.load_settings() == saved


def test_a_broken_settings_file_is_ignored_not_fatal() -> None:
    config.settings_file().parent.mkdir(parents=True)
    config.settings_file().write_text("coach = 'shouting'", encoding="utf-8")
    settings = config.load_settings()
    assert settings.game == "ride-the-bus" and "shouting" in settings.problem
    assert "was ignored" in run("doctor")


# ── the current game ─────────────────────────────────────────────────────────────────────


def test_zero_setup_plays_ride_the_bus() -> None:
    out = run("odds")
    assert "Ride the Bus" in out and "HOUSE EDGE 3.7%" in out
    assert "96 of every 100" in out  # plain words, not just "RTP"


def test_games_use_switches_the_current_game() -> None:
    assert "Hi-Lo 5 is now your game" in run("games", "use", "hi-lo-5")
    assert config.load_settings().game == "hi-lo-5"
    assert "Hi-Lo 5" in run("odds")
    assert "Stage 5" in run("cheatsheet")


def test_your_payouts_replace_the_default() -> None:
    run("settings", "--ladder", "classic")
    assert "PLAYER EDGE" in run("odds")
    assert "your payouts" in run("odds")
    run("settings", "--reset-payouts")
    assert "HOUSE EDGE 3.7%" in run("odds")


def test_a_one_off_game_does_not_change_the_current_one() -> None:
    assert "Colour Run 5" in run("odds", "--game", "colour-run-5")
    assert config.load_settings().game == "ride-the-bus"


def test_unknown_game_is_refused() -> None:
    result = runner.invoke(app, ["games", "use", "poker", "--plain"])
    assert result.exit_code == 1 and "hi-lo-5" in result.output
    assert config.load_settings().game == "ride-the-bus"


# ── making your own game ─────────────────────────────────────────────────────────────────


def test_games_new_from_flags() -> None:
    out = run(
        "games",
        "new",
        "--name",
        "Two Colours",
        "--stages",
        "colour,colour",
        "--ladder",
        "1.9,3.7",
        "--use",
    )
    assert "Saved" in out
    path = config.games_dir() / "two-colours.toml"
    assert path.exists()
    assert config.load_settings().game == "two-colours"
    assert "Two Colours" in run("odds")
    assert "two-colours" in run("games")


def test_games_new_wizard() -> None:
    answers = (
        "Hi Lo 3\n4\nreveal\nhigher_lower\nhigher_lower\nhigher_lower\n\n\n\n1.3\n1.9\n2.8\ny\n"
    )
    out = run("games", "new", input=answers)
    assert "Fair would be" in out
    assert config.load_settings().game == "hi-lo-3"
    assert "higher or lower ×3" in run("games", "hi-lo-3")


def test_init_saves_your_rules_as_your_game() -> None:
    run("init", "--yes", "--ladder", "1.9,2.5,3.8,14", "--game-version", "1.0")
    assert (config.games_dir() / "my-ride-the-bus.toml").exists()
    assert config.load_settings().game == "my-ride-the-bus"
    assert "1.90x" in run("odds")


# ── the front door ───────────────────────────────────────────────────────────────────────


def test_no_arguments_prints_help_when_not_in_a_terminal() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output
    for command in ("odds", "cheatsheet", "advise", "games", "tutorial", "doctor"):
        assert command in result.output


def test_old_command_names_still_work_but_are_hidden() -> None:
    assert "HOUSE EDGE" in run("analyze")
    assert "Stage 1" in run("policy")
    assert "SIMULATED" in run("sim", "-n", "500", "--seed", "1")
    help_text = run("--help")
    assert " analyze " not in help_text and " policy " not in help_text


def test_the_menu_runs_an_action_and_teaches_the_command() -> None:
    buf = io.StringIO()
    ui = make_ui(plain=True, width=80, file=buf)
    answers = iter(["5", "", "q"])  # "How fair is this game?", Enter, quit
    run_menu(ui, read=lambda prompt: next(answers))
    out = buf.getvalue()
    assert "How fair is this game?" in out
    assert "HOUSE EDGE" in out
    assert "Next time, type: busride odds" in out


def test_the_menu_survives_a_failing_action_and_a_typo() -> None:
    buf = io.StringIO()
    ui = make_ui(plain=True, width=80, file=buf)
    config.save_settings(config.Settings(game="no-such-game"))
    answers = iter(["banana", "5", "", "q"])
    run_menu(ui, read=lambda prompt: next(answers))
    out = buf.getvalue()
    assert "Choose one of" in out  # the typo
    assert "no game called" in out  # the failed action reported, menu still running


def test_tutorial_runs_through_without_a_terminal() -> None:
    out = run("tutorial")
    for heading in ("What busride does", "How to read the advice", "Where to go next"):
        assert heading in out


def test_doctor_reports_without_revealing_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-very-secret")
    out = run("doctor")
    assert "ANTHROPIC_API_KEY" in out and "found" in out
    assert "sk-test-very-secret" not in out
    assert str(config.config_dir()) in out.replace("\n", "")


def test_rounds_go_to_your_data_folder() -> None:
    run("log", "-e", "9h Ks 3d 42")
    assert (config.data_dir() / "rounds.db").exists()
    assert "1 rounds" in run("verify")
