"""M4: playing with fake chips, every decision graded exactly, and the coach."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride import config
from busride.cli import app
from busride.coach.explain import review, why
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_cards
from busride.engine.solver import decide, solve
from busride.play import Session, grade, parse_choice

RTB = BUILTIN_GAMES["ride-the-bus"]  # house ladder 1.8 2.3 3.2 12
runner = CliRunner()


def run(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, [*args, "--plain"], input=input)
    assert result.exit_code == 0, result.output
    return result.output


# ── grading ──────────────────────────────────────────────────────────────────────────────


def test_grading_uses_the_exact_values() -> None:
    sol = solve(RTB)
    seen = parse_cards("9h Ks")  # cash 2.30; outside wins 32/50 and is worth 2.05
    stopped = grade(sol, seen, "cash")
    assert stopped.optimal and stopped.best == "cash"
    went_on = grade(sol, seen, "outside")
    assert went_on.regret == pytest.approx(2.30 - decide(sol, seen).continue_value)
    assert not went_on.optimal
    worst = grade(sol, seen, "inside")
    assert worst.regret > went_on.regret > 0


def test_a_choice_with_nothing_to_choose_is_trivial() -> None:
    first = grade(solve(RTB), [], "red")  # red or black are worth the same, and you must bet
    assert first.trivial and first.optimal and first.forced


# ── the session ──────────────────────────────────────────────────────────────────────────


def play_best(session: Session, rounds: int) -> None:
    for _ in range(rounds):
        rnd = session.new_round()
        while not rnd.over:
            if not rnd.next_stage.is_guess:  # type: ignore[union-attr]
                rnd.reveal()
                continue
            d = rnd.decision()
            rnd.act(d.best.guess if d.should_continue or not rnd.can_stop else "cash")


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_perfect_play_gives_nothing_up(name: str) -> None:
    session = Session(BUILTIN_GAMES[name], chips=1000, stake=10, seed=3)
    play_best(session, 30)
    summary = session.summary()
    assert summary.given_up == pytest.approx(0, abs=1e-9)
    assert summary.best_moves == summary.decisions
    assert summary.rounds == 30


def test_chips_add_up() -> None:
    session = Session(RTB, chips=1000, stake=10, seed=5)
    play_best(session, 20)
    paid = sum(r.payout for r in session.rounds)
    assert session.chips == pytest.approx(1000 - 20 * 10 + paid)
    summary = session.summary()
    assert summary.net == pytest.approx(session.chips - 1000)
    assert summary.luck == pytest.approx(summary.net - summary.expected_net)


def test_a_fixed_deal_wins_cashes_and_loses() -> None:
    # 9h red (win), Ks higher (win), then cash out at 2.30
    session = Session(RTB, chips=100, stake=10, cards=parse_cards("9h Ks 2c 3d"))
    rnd = session.new_round()
    assert session.chips == 90  # the stake is on the table
    assert rnd.act("red").result == "win"
    assert rnd.act("higher").result == "win"
    step = rnd.act("cash")
    assert step.result == "cash" and step.payout == pytest.approx(23.0)
    assert session.chips == pytest.approx(113.0)
    # next round, the dealer goes on from the fixed cards: 2c is black, so red loses
    lost = session.new_round()
    assert lost.act("red").result == "lose" and lost.over == "lost"
    assert session.chips == pytest.approx(103.0)


def test_running_out_of_chips_ends_the_session() -> None:
    session = Session(RTB, chips=10, stake=10, cards=parse_cards("2c"))
    session.new_round().act("red")
    assert not session.can_play()
    with pytest.raises(ValueError, match="chips"):
        session.new_round()


def test_the_biggest_mistake_is_named() -> None:
    session = Session(RTB, chips=100, stake=10, cards=parse_cards("9h Ks Qd 2c"))
    rnd = session.new_round()
    rnd.act("red")
    rnd.act("higher")
    rnd.act("inside")  # the worst choice: cashing out was best
    summary = session.summary()
    assert summary.biggest is not None and summary.biggest.action == "inside"
    assert summary.biggest.best == "cash"
    # riding on with higher on a 9 was a (smaller) slip too
    assert summary.given_up > summary.biggest.regret * 10 > 0


def test_typed_choices() -> None:
    stage = RTB.stages[1]  # higher or lower
    assert parse_choice("1", stage, can_stop=True) == "higher"
    assert parse_choice("L", stage, can_stop=True) == "lower"
    assert parse_choice("lower", stage, can_stop=True) == "lower"
    assert parse_choice("$", stage, can_stop=True) == "cash"
    assert parse_choice("$", stage, can_stop=False) is None  # the first bet can't be refused
    assert parse_choice("q", stage, can_stop=True) == "quit"
    assert parse_choice("banana", stage, can_stop=True) is None
    suit = RTB.stages[3]
    assert parse_choice("h", suit, can_stop=True) == "hearts"
    assert parse_choice("4", suit, can_stop=True) == "spades"


# ── the coach ────────────────────────────────────────────────────────────────────────────


def test_review_says_how_good_a_move_was() -> None:
    sol = solve(RTB)
    seen = parse_cards("9h Ks")
    assert review(grade(sol, seen, "cash"), stake=10).kind == "good"
    worse = review(grade(sol, seen, "inside"), stake=10)
    assert worse.kind == "bad" and "CASH OUT" in worse.text and "chips" in worse.text


def test_why_explains_with_the_real_numbers() -> None:
    sol = solve(RTB)
    text = why(decide(sol, parse_cards("9h Ks")), RTB)
    assert "2.30" in text and "32/50" in text and "2.05" in text


# ── the command ──────────────────────────────────────────────────────────────────────────


def test_a_scripted_three_round_game() -> None:
    out = run("play", "--rounds", "3", "--seed", "7", "--coach", "review", input="1\n" * 60)
    for text in ("Round 1", "Round 2", "Round 3", "Coach:", "SESSION"):
        assert text in out
    assert "3 rounds" in out
    assert "Round 4" not in out


@pytest.mark.parametrize(
    ("coach", "present", "absent"),
    [
        ("off", [], ["Coach:", "Why:", "█"]),
        ("hints", ["█"], ["Coach:", "Why:"]),
        ("review", ["Coach:"], ["Why:"]),
        ("explain", ["Coach:", "Why:"], []),
    ],
)
def test_coach_levels(coach: str, present: list[str], absent: list[str]) -> None:
    out = run("play", "--rounds", "2", "--seed", "4", "--coach", coach, input="1\n" * 40)
    for text in present:
        assert text in out
    session_part = out.split("SESSION")[0]
    for text in absent:
        assert text not in session_part


def test_quitting_early_still_shows_the_summary() -> None:
    out = run("play", "--seed", "1", input="q\n")
    assert "SESSION" in out and "0 rounds" in out


def test_play_uses_your_settings() -> None:
    config.save_settings(config.Settings(chips=300, stake=25.0, coach="off"))
    out = run("play", "--rounds", "1", "--seed", "2", input="1\n" * 20)
    assert "300" in out and "25.00" in out and "Coach:" not in out.split("SESSION")[0]


def test_play_other_games(tmp_path: Path) -> None:
    out = run("play", "--game", "hi-lo-5", "--rounds", "2", "--seed", "3", input="1\n" * 40)
    assert "shown" in out and "SESSION" in out
