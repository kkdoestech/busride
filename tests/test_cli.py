"""End-to-end runs of every command through Typer's test runner."""

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride.cli import app, parse_entry
from busride.engine import solver
from busride.engine.cards import parse_cards
from busride.engine.policy import advise
from busride.engine.rules import Rules, dump_rules, load_rules
from busride.store import Store

runner = CliRunner()


@pytest.fixture
def rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "rules.toml"
    rules = Rules(game_version="0.4.1", captured_on="2026-10-23", returns=(1.9, 2.5, 3.8, 14.0))
    path.write_text(dump_rules(rules), encoding="utf-8")
    return path


def run(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, [*args, "--plain"], input=input)
    assert result.exit_code == 0, result.output
    return result.output


def test_analyze(rules_file: Path, tmp_path: Path) -> None:
    out = run("analyze", "--rules", str(rules_file), "--db", str(tmp_path / "none.db"))
    assert "PLAYER EDGE +5.4%" in out
    assert "15.86x" in out and "solved exactly" in out


def test_analyze_without_rules_points_to_init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", "--rules", str(tmp_path / "missing.toml")])
    assert result.exit_code == 1
    assert "busride init" in result.output


def test_advise_one_shot(rules_file: Path) -> None:
    out = run("advise", "9h", "Ks", "--rules", str(rules_file))
    for text in ("Stage 3 of 4", "OUTSIDE", "32/50", "12/50", "6/50", "TIE (loses)"):
        assert text in out
    # 32/50 x 3.80 = 2.43 is worth less than the 2.50 in hand
    assert "Cash out 2.50  vs  continue 2.43" in out and "CASH OUT" in out


@pytest.mark.parametrize(
    ("cards", "message"),
    [
        (["9h", "9s"], "ties the first card"),
        (["9h", "Kx"], "no suit"),
        (["9h", "9h"], "already on the table"),
    ],
)
def test_advise_explains_bad_input(rules_file: Path, cards: list[str], message: str) -> None:
    result = runner.invoke(app, ["advise", *cards, "--rules", str(rules_file), "--plain"])
    assert result.exit_code == 1
    assert message in result.output
    assert "Traceback" not in result.output


def test_advise_live_loop(rules_file: Path) -> None:
    out = run("advise", "--rules", str(rules_file), input="9h\nzz\nKs\nu\nn\n2c\nq\n")
    assert "no suit" in out  # bad card re-prompts
    assert "Stage 3 of 4" in out and "Stage 2 of 4" in out


def test_advise_answers_under_100_ms(rules_file: Path) -> None:
    sol = solver.solve(load_rules(rules_file))
    for cards in ("", "9h", "9h Ks", "9h Ks 3d"):
        started = time.perf_counter()
        advise(sol, parse_cards(cards) if cards else [])
        assert time.perf_counter() - started < 0.1


def test_policy(rules_file: Path) -> None:
    out = run("policy", "--rules", str(rules_file))
    assert "Stage 3" in out and "1st\\2nd" in out


def test_sim_and_record_then_verify(rules_file: Path, tmp_path: Path) -> None:
    db = tmp_path / "sim.db"
    out = run(
        "sim",
        "-n",
        "3000",
        "--seed",
        "1",
        "--strategy",
        "greedy",
        "--record",
        str(db),
        "--rules",
        str(rules_file),
    )
    assert "SIMULATED RTP" in out and "Saved 3,000" in out
    out = run("verify", "--db", str(db), "--rules", str(rules_file))
    assert "Fresh 52-card deck: consistent with 3,000 rounds" in out


def test_sim_will_not_write_into_real_logs(rules_file: Path, tmp_path: Path) -> None:
    db = tmp_path / "rounds.db"
    with Store(db) as store:
        store.add(["9h"], 1.0, None, "0.4.1")
    result = runner.invoke(
        app, ["sim", "-n", "100", "--record", str(db), "--rules", str(rules_file)]
    )
    assert result.exit_code == 1 and "separate file" in result.output


def test_log_entries_and_undo(rules_file: Path, tmp_path: Path) -> None:
    db = tmp_path / "rounds.db"
    out = run(
        "log",
        "--db",
        str(db),
        "--rules",
        str(rules_file),
        "--stake",
        "10",
        "-e",
        "9h Ks 3d 38",
        "-e",
        "2c 5h",
    )
    assert "paid 38.00 (3.80x)" in out and "lost at stage 2" in out
    out = run(
        "log",
        "--db",
        str(db),
        "--rules",
        str(rules_file),
        "--stake",
        "10",
        input="Qd Js x2.5\nu\nAh Ah\nn\nKd 4c 9.99\nbogus\nq\n",
    )
    assert "removed #3" in out
    assert "not on the ladder" in out  # 9.99 at stake 10 is 1.00x
    assert "has no" in out
    with Store(db) as store:
        assert [r.cards for r in store.rounds()] == [("9h", "Ks", "3d"), ("2c", "5h"), ("Kd", "4c")]


def test_parse_entry() -> None:
    assert parse_entry("9h Ks 3d 42", 10) == (["9h", "Ks", "3d"], 42.0)
    assert parse_entry("9h Ks x4.2", 10) == (["9h", "Ks"], pytest.approx(42.0))
    assert parse_entry("9h Ks 4.2x", 10) == (["9h", "Ks"], pytest.approx(42.0))
    assert parse_entry("2c 5h", 10) == (["2c", "5h"], None)
    with pytest.raises(ValueError, match="at most 4"):
        parse_entry("2c 3c 4c 5c 6c", 1)


def test_verify_empty(rules_file: Path, tmp_path: Path) -> None:
    assert "NO ROUNDS LOGGED YET" in run(
        "verify", "--db", str(tmp_path / "x.db"), "--rules", str(rules_file)
    )


def test_init_non_interactive(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    out = run(
        "init",
        "--rules",
        str(path),
        "--yes",
        "--ladder",
        "1.9,2.5,3.8,14",
        "--game-version",
        "0.4.1",
        "--ace",
        "low",
    )
    assert "Written to" in out
    rules = load_rules(path)
    assert rules.returns == (1.9, 2.5, 3.8, 14.0) and rules.ace == "low"


def test_init_wizard(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    answers = "0.4.2\nshoe\n4\neither\npush\nlose\n1.9\n2.6\n3.9\n14.5\n10\n1000\nlose\n"
    run("init", "--rules", str(path), input=answers)
    rules = load_rules(path)
    assert (rules.game_version, rules.deck_model, rules.decks, rules.ace) == (
        "0.4.2",
        "shoe",
        4,
        "either",
    )
    assert rules.tie_higher_lower == "push" and rules.max_stake == 1000.0


def test_init_flags_a_payout_above_fair(tmp_path: Path) -> None:
    out = run("init", "--rules", str(tmp_path / "r.toml"), "--yes", "--ladder", "2.1,2.5,3.8,14")
    assert "above the fair 2.00x" in out
