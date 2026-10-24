"""M5: the arena. Every agent plays the same deals, and every decision is graded exactly."""

import io
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride import config
from busride.agents.base import Action, AgentError, Observation, describe
from busride.agents.baselines import make_agent
from busride.agents.oracle import Oracle
from busride.arena.runner import Arena, make_deals
from busride.arena.runs import RunFile
from busride.arena.scoring import score
from busride.cli import app, run_menu
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_card, parse_cards
from busride.engine.game import GameSpec
from busride.engine.solver import decide, fixed_plan, solve, solve_from
from busride.ui.theme import make_ui

RTB = BUILTIN_GAMES["ride-the-bus"]
runner = CliRunner()


def run_cli(*args: str) -> str:
    result = runner.invoke(app, [*args, "--plain"])
    assert result.exit_code == 0, result.output
    return result.output


def arena(
    tmp_path: Path, agents: list[str], deals: int, seed: int = 7, rules: GameSpec = RTB
) -> RunFile:
    path = tmp_path / "run.jsonl"
    Arena(rules, path, seed=seed, deals=deals).run([make_agent(a, rules) for a in agents])
    return RunFile(path)


# ── duplicate deals ──────────────────────────────────────────────────────────────────────


def test_deals_are_reproducible_and_legal() -> None:
    a = make_deals(RTB, 50, seed=7)
    assert a == make_deals(RTB, 50, seed=7)
    assert a != make_deals(RTB, 50, seed=8)
    for deal in a:
        cards = [parse_card(c) for c in deal]
        assert len(cards) == 4 and len(set(cards)) == 4  # a fresh deck never repeats a card


def test_every_agent_sees_the_same_cards(tmp_path: Path) -> None:
    run = arena(tmp_path, ["optimal", "greedy", "random"], deals=30)
    first: dict[int, set[str]] = {}
    for d in run.decisions():
        if d["position"] == 0:
            continue
        first.setdefault(d["deal"], set()).add(d["seen"][0])
    assert all(len(cards) == 1 for cards in first.values())


# ── exact grading ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_optimal_gives_up_nothing(tmp_path: Path, name: str) -> None:
    rules = BUILTIN_GAMES[name]
    run = arena(tmp_path, ["optimal"], deals=200, rules=rules)
    decisions = list(run.decisions())
    assert decisions and all(d["regret"] <= 1e-12 for d in decisions)
    board = score(run)["optimal"]
    assert board.given_up_per_deal == pytest.approx(0, abs=1e-12)
    assert board.calibration == pytest.approx(0, abs=1e-12)  # it states the exact odds


@pytest.mark.parametrize(("agent", "stop"), [("greedy", None), ("stop:2", 2)])
def test_greedy_gives_up_what_the_exact_formula_says(
    tmp_path: Path, agent: str, stop: int | None
) -> None:
    # expected total regret per deal = V*(root) - V_greedy(root)
    run = arena(tmp_path, [agent], deals=3000)
    board = score(run)[agent]
    exact = solve(RTB).rtp - fixed_plan(RTB, stop).value
    assert abs(board.given_up_per_deal - exact) < 4 * board.given_up_se, (board, exact)
    assert abs(board.mean_return - fixed_plan(RTB, stop).value) < 4 * board.return_se


def test_random_is_reproducible_and_worse(tmp_path: Path) -> None:
    one = score(arena(tmp_path / "a", ["random", "optimal"], deals=300))
    two = score(arena(tmp_path / "b", ["random", "optimal"], deals=300))
    assert one["random"].given_up_per_deal == two["random"].given_up_per_deal
    assert one["random"].given_up_per_deal > 0.05
    assert one["random"].calibration is None  # it never states a probability


def test_bold_and_timid_are_counted(tmp_path: Path) -> None:
    board = score(arena(tmp_path, ["greedy", "stop:1"], deals=300))
    assert board["greedy"].too_bold > 0 and board["greedy"].too_timid == 0  # never cashes out
    assert board["stop:1"].too_timid > 0


# ── resume ───────────────────────────────────────────────────────────────────────────────


def test_resume_skips_what_is_done(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    Arena(RTB, path, seed=3, deals=40).run([make_agent("optimal", RTB)])
    lines_before = path.read_text(encoding="utf-8").count("\n")
    Arena(RTB, path, seed=3, deals=40).run([make_agent("optimal", RTB), make_agent("greedy", RTB)])
    run = RunFile(path)
    deals = [r for r in run.records() if r["type"] == "deal"]
    assert sum(1 for r in deals if r["agent"] == "optimal") == 40
    assert sum(1 for r in deals if r["agent"] == "greedy") == 40
    assert path.read_text(encoding="utf-8").count("\n") > lines_before


def test_resume_refuses_a_different_run(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    Arena(RTB, path, seed=3, deals=10).run([make_agent("optimal", RTB)])
    with pytest.raises(ValueError, match="different"):
        Arena(RTB, path, seed=4, deals=10).run([make_agent("optimal", RTB)])


def test_runs_store_their_deals_and_rules(tmp_path: Path) -> None:
    run = arena(tmp_path, ["optimal"], deals=5)
    header = run.header()
    assert header["deals"] == make_deals(RTB, 5, seed=7)
    assert run.rules().returns == RTB.returns
    assert json.loads(run.path.read_text(encoding="utf-8").splitlines()[0])["type"] == "run"


# ── agents that misbehave ────────────────────────────────────────────────────────────────


class Flaky:
    """Answers nonsense once per decision, then a legal guess."""

    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        self.calls += 1
        if obs.feedback is None:
            raise AgentError("I said 'purple'")
        return Action(obs.options[0])


class Broken:
    name = "broken"

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        return Action("purple")


def test_one_retry_then_a_forfeit(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    Arena(RTB, path, seed=1, deals=20).run([Flaky(), Broken()])
    run = RunFile(path)
    flaky = [d for d in run.decisions() if d["agent"] == "flaky"]
    assert flaky and all(d["retries"] == 1 and d["valid"] for d in flaky)
    broken = [d for d in run.decisions() if d["agent"] == "broken"]
    assert all(not d["valid"] and d["move"] == "forfeit" for d in broken)
    assert all(d["regret"] == pytest.approx(d["value"]) for d in broken)
    board = score(run)
    assert board["broken"].forfeits == 20 and board["broken"].mean_return == 0
    assert board["flaky"].retries == len(flaky)


# ── speed and the command ────────────────────────────────────────────────────────────────


def test_two_thousand_deals_for_four_baselines_is_quick(tmp_path: Path) -> None:
    started = time.perf_counter()
    arena(tmp_path, ["optimal", "greedy", "random", "stop:2"], deals=2000)
    assert time.perf_counter() - started < 10


def test_arena_commands() -> None:
    out = run_cli(
        "arena", "run", "--agents", "optimal,greedy,random", "--deals", "200", "--seed", "3",
        "--name", "t1",
    )  # fmt: skip
    assert "optimal" in out and "greedy" in out and "Gives up" in out
    assert (config.data_dir() / "runs" / "t1.jsonl").exists()
    assert "random" in run_cli("arena", "leaderboard", "t1")
    replay = run_cli("arena", "replay", "t1", "--agent", "greedy", "--deal", "1")
    assert "deal 1" in replay.lower() and "best" in replay.lower()
    assert "t1" in run_cli("arena", "runs")
    agents = run_cli("arena", "agents")
    assert "optimal" in agents and "stop:K" in agents
    result = runner.invoke(app, ["arena", "run", "--agents", "wizard", "--plain"])
    assert result.exit_code == 1 and "optimal" in result.output


def test_leaderboard_without_runs_explains() -> None:
    out = run_cli("arena", "leaderboard")
    assert "no arena runs yet" in out.lower()


def test_regret_is_never_negative(tmp_path: Path) -> None:
    run = arena(tmp_path, ["random", "greedy", "stop:3"], deals=300)
    assert all(d["regret"] >= -1e-12 for d in run.decisions())
    assert all(math.isfinite(d["value"]) for d in run.decisions())


# ── games too big to solve whole ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(("name", "cards"), [("ride-the-bus", "9h Ks"), ("hi-lo-5", "7h Qs")])
def test_solving_from_a_state_matches_the_whole_solve(name: str, cards: str) -> None:
    rules = BUILTIN_GAMES[name]
    seen = parse_cards(cards)
    part, whole = decide(solve_from(rules, seen), seen), decide(solve(rules), seen)
    assert [(o.guess, o.wins) for o in part.options] == [(o.guess, o.wins) for o in whole.options]
    assert [o.ev for o in part.options] == pytest.approx([o.ev for o in whole.options], abs=1e-12)


def test_a_game_too_big_to_solve_whole_is_graded_part_by_part(tmp_path: Path) -> None:
    # hi-lo-5 has 28,237 states: 6,605 after the first card, 1,159 after the second
    rules = BUILTIN_GAMES["hi-lo-5"]
    whole = arena(tmp_path / "whole", ["optimal", "greedy"], deals=60, rules=rules)
    path = tmp_path / "parts.jsonl"
    oracle = Oracle(rules, budget=2000)
    assert oracle.solution is None and oracle.rtp is None
    agents = [make_agent(a, rules, oracle) for a in ("optimal", "greedy")]
    Arena(rules, path, seed=7, deals=60, budget=2000).run(agents)
    parts = RunFile(path)
    exact = {(d["agent"], d["deal"], d["position"]): d for d in whole.decisions()}
    first = [d for d in parts.decisions() if d["position"] == 1]
    assert first and all(d["regret"] is None for d in first)
    later = [d for d in parts.decisions() if d["position"] > 1 and d["agent"] == "greedy"]
    assert later
    for d in later:
        assert d["regret"] == pytest.approx(exact["greedy", d["deal"], d["position"]]["regret"])
    board = score(parts)["greedy"]
    assert 0 < board.coverage < 1
    assert board.calibration == pytest.approx(0)  # the odds need no solving


# ── agents and their names ───────────────────────────────────────────────────────────────


def test_the_rules_in_plain_words() -> None:
    text = describe(RTB)
    for part in ("1.80, 2.30, 3.20, 12.00", "Aces are high", "first guess must be played"):
        assert part in text
    assert "inside or outside card 1 and card 2" in text
    assert "an equal rank loses" in text
    loose = replace(BUILTIN_GAMES["in-between"], forced_first_bet=False, tie_range_edge="push")
    text = describe(loose)
    assert "walk away" in text and "pushes" in text and "higher or lower" not in text


def test_agent_names_are_checked() -> None:
    for bad in ("stop:0", "stop:5", "wizard", "human"):
        with pytest.raises(ValueError):
            make_agent(bad, RTB)
    loose = replace(RTB, forced_first_bet=False)
    assert make_agent("stop:0", loose).name == "stop:0"
    assert make_agent(" Greedy ", RTB).name == "greedy"


def test_an_agent_plays_only_once_per_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only once"):
        Arena(RTB, tmp_path / "r.jsonl", deals=2).run([make_agent("greedy", RTB)] * 2)


def test_a_line_cut_short_is_played_again(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    Arena(RTB, path, seed=5, deals=10).run([make_agent("greedy", RTB)])
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.rstrip("\n").rfind("\n") + 30], encoding="utf-8")  # a crash
    assert len(RunFile(path).done()) == 9
    Arena(RTB, path, seed=5, deals=10).run([make_agent("greedy", RTB)])
    run = RunFile(path)
    assert len(run.done()) == 10
    tenth = [d for d in run.decisions() if d["deal"] == 10]
    assert [d["position"] for d in tenth] == list(range(len(tenth)))


# ── the commands ─────────────────────────────────────────────────────────────────────────


def test_a_run_carries_on_under_its_name() -> None:
    run_cli("arena", "run", "--agents", "optimal", "--deals", "50", "--name", "t2")
    out = run_cli("arena", "run", "--agents", "greedy", "--name", "t2")  # 50 deals, from the file
    assert "optimal" in out and "greedy" in out and "50 duplicate deals" in out
    result = runner.invoke(app, ["arena", "run", "--name", "t2", "--deals", "60", "--plain"])
    assert result.exit_code == 1 and "different run" in result.output


def test_the_same_command_again_resumes_the_default_run() -> None:
    run_cli("arena", "run", "--agents", "optimal", "--deals", "30")
    out = run_cli("arena", "run", "--agents", "optimal,random", "--deals", "30")
    assert "ride-the-bus-seed7-30" in out and "random" in out
    other = run_cli("arena", "run", "--agents", "optimal", "--deals", "30", "--ladder", "classic")
    assert "ride-the-bus-seed7-30-" in other  # another ladder, so another run
    assert "2 saved" in run_cli("arena", "runs")


def test_replay_shows_the_costliest_moves() -> None:
    run_cli("arena", "run", "--agents", "optimal,greedy", "--deals", "100", "--name", "t3")
    out = run_cli("arena", "replay", "t3", "--worst")  # greedy is the only one to show
    assert "greedy's 10 costliest decisions" in out and "cash out" in out
    result = runner.invoke(app, ["arena", "replay", "t3", "--deal", "101", "--plain"])
    assert result.exit_code == 1 and "deals 1 to 100" in result.output
    result = runner.invoke(app, ["arena", "leaderboard", "nope", "--plain"])
    assert result.exit_code == 1 and "busride arena runs" in result.output


def test_you_can_play_in_the_arena() -> None:
    result = runner.invoke(
        app,
        ["arena", "run", "--agents", "human,optimal", "--deals", "3", "--name", "me", "--plain"],
        input="banana\n" + "1\n" * 12,
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Your move" in out and "Type 1 red, 2 black" in out
    assert "Deal 1: you" in out and "human" in out.split("RIDE THE BUS · arena")[-1]


def test_a_human_gets_new_cards_each_time() -> None:
    for _ in range(2):
        result = runner.invoke(
            app, ["arena", "run", "--agents", "human", "--deals", "1", "--plain"], input="1\n" * 4
        )
        assert result.exit_code == 0, result.output
    assert "2 saved" in run_cli("arena", "runs")


def test_stopping_partway_keeps_the_finished_deals() -> None:
    result = runner.invoke(
        app,
        ["arena", "run", "--agents", "human", "--deals", "5", "--name", "me2", "--plain"],
        input="1\n" * 4 + "q\n",
    )
    assert result.exit_code == 0, result.output
    assert "Stopped" in result.output
    done = RunFile(config.data_dir() / "runs" / "me2.jsonl").done()
    assert 1 <= len(done) < 5


def test_the_menu_opens_the_arena() -> None:
    buf = io.StringIO()
    ui = make_ui(plain=True, width=80, file=buf)
    answers = iter(["6", "", "q"])
    run_menu(ui, read=lambda prompt: next(answers))
    out = buf.getvalue()
    assert "Gives up" in out and "Next time, type: busride arena run" in out
