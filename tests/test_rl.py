"""M7: learning agents. Trained on the game tree, measured exactly, played with real cards."""

import io
import json
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from busride import config
from busride.agents.baselines import make_agent
from busride.agents.rl.agent import RLAgent, agent_path, load, save
from busride.agents.rl.qlearning import Learner, TreeGame, train
from busride.arena.runner import Arena
from busride.arena.runs import fingerprint
from busride.arena.scoring import score
from busride.cli import app, run_menu
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.solver import fixed_plan, game_tree, policy_value, solve
from busride.ui.theme import make_ui

RTB = BUILTIN_GAMES["ride-the-bus"]
runner = CliRunner()


def run_cli(*args: str) -> str:
    result = runner.invoke(app, [*args, "--plain"])
    assert result.exit_code == 0, result.output
    return result.output


# ── exact evaluation of any policy ───────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(BUILTIN_GAMES))
def test_policy_value_reproduces_the_solver_and_the_fixed_plan(name: str) -> None:
    rules = BUILTIN_GAMES[name]
    sol = solve(rules)
    best = policy_value(
        rules, lambda k, key: sol.best_guess[k][key] if sol.continues(k, key) else None
    )
    assert best == pytest.approx(sol.rtp, abs=1e-12)
    tree = game_tree(rules)
    greedy = policy_value(
        rules, lambda k, key: max(tree.levels[k][key], key=lambda b: b.win_weight).guess
    )
    assert greedy == pytest.approx(fixed_plan(rules).value, abs=1e-12)


def test_the_tree_game_deals_with_the_true_odds() -> None:
    game = TreeGame(RTB)
    rng = random.Random(5)
    n = 20_000
    wins = sum(game.play(game.root, "red", rng)[0] is None for _ in range(n))
    assert abs(wins / n - 0.5) < 4 * (0.25 / n) ** 0.5
    # after a 2, "higher" wins 48 of 51
    state = next((1, key) for key, seen in game.tree.reps[1].items() if seen[0].rank == 2)
    wins = sum(game.play(state, "higher", rng)[0] is None for _ in range(n))
    p = 48 / 51
    assert abs(wins / n - p) < 4 * (p * (1 - p) / n) ** 0.5


# ── learning ─────────────────────────────────────────────────────────────────────────────


def test_q_learning_gets_within_one_percent_of_perfect_play() -> None:
    # M7 acceptance: under 1% regret on Ride the Bus within a fixed budget, with a fixed seed
    started = time.perf_counter()
    t = train(RTB, 300_000, "q-learning", seed=1)
    assert t.regret < 0.01
    assert time.perf_counter() - started < 15
    first, last = t.curve[0], t.curve[-1]
    assert t.optimal - first.value > 0.05 and last.value > first.value
    assert all(c.value <= t.optimal + 1e-9 for c in t.curve)  # nothing beats perfect play


def test_sarsa_learns_too() -> None:
    assert train(RTB, 300_000, "sarsa", seed=1).regret < 0.02


def test_training_is_reproducible() -> None:
    a = train(RTB, 20_000, seed=4, checkpoints=5)
    b = train(RTB, 20_000, seed=4, checkpoints=5)
    assert [c.value for c in a.curve] == [c.value for c in b.curve]
    assert [c.value for c in a.curve] != [
        c.value for c in train(RTB, 20_000, seed=5, checkpoints=5).curve
    ]


def test_other_games_learn() -> None:
    for name in ("in-between", "colour-run-5"):
        assert train(BUILTIN_GAMES[name], 100_000, seed=1).regret < 0.01, name


def test_unknown_algorithm() -> None:
    with pytest.raises(ValueError):
        Learner(RTB, "dqn")


# ── saved agents in the arena ────────────────────────────────────────────────────────────


def test_a_trained_agent_plays_real_cards_as_it_learned(tmp_path: Path) -> None:
    t = train(RTB, 200_000, seed=2)
    path = save(t, "t1", tmp_path / "t1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["episodes"] == 200_000 and data["value"] == pytest.approx(t.value)
    agent = RLAgent("t1", data, RTB)
    run = Arena(RTB, tmp_path / "run.jsonl", seed=3, deals=3000).run([agent])
    board = score(run)["rl:t1"]
    exact = t.optimal - t.value  # what the arena's regret per deal estimates
    assert abs(board.given_up_per_deal - exact) < 4 * board.given_up_se + 1e-9


def test_moves_are_matched_across_suit_relabellings(tmp_path: Path) -> None:
    # an "agent" holding the solver's own moves must give up exactly nothing on real cards
    sol = solve(RTB)
    tree = game_tree(RTB)
    policy = {
        f"{k}|{key!r}": (sol.best_guess[k][key] if sol.continues(k, key) else "cash")
        for k, level in enumerate(tree.levels)
        for key in level
    }
    data = {"fingerprint": fingerprint(RTB), "game": RTB.name, "policy": policy}
    run = Arena(RTB, tmp_path / "run.jsonl", seed=9, deals=1500).run(
        [RLAgent("perfect", data, RTB)]
    )
    assert all(d["regret"] <= 1e-12 for d in run.decisions())


def test_an_agent_only_plays_the_game_it_learned(tmp_path: Path) -> None:
    t = train(RTB, 5_000, seed=1, checkpoints=2)
    data = json.loads(save(t, "t2", tmp_path / "t2.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="other rules or payouts"):
        RLAgent("t2", data, RTB.with_returns((2.0, 3.0, 4.0, 20.0)))
    with pytest.raises(ValueError, match="no trained agent"):
        load("nobody")


# ── the commands ─────────────────────────────────────────────────────────────────────────


def test_train_saves_an_agent_for_the_arena() -> None:
    out = run_cli("train", "--episodes", "60000", "--name", "mine")
    assert "Saved as rl:mine" in out and "gives up" in out
    assert agent_path("mine").exists() and agent_path("mine").parent == config.data_dir() / "agents"
    board = run_cli("arena", "run", "--agents", "optimal,rl:mine", "--deals", "200")
    assert "rl:mine" in board
    assert make_agent("rl:mine", RTB).name == "rl:mine"
    run_cli("train", "--episodes", "1000", "--name", "gone", "--no-save")
    assert not agent_path("gone").exists()
    result = runner.invoke(app, ["train", "--method", "dqn", "--plain"])
    assert result.exit_code == 1 and "q-learning" in result.output


def test_train_names_itself_after_the_method_and_game() -> None:
    out = run_cli("train", "--method", "sarsa", "--episodes", "20000", "--game", "colour-run-5")
    assert "rl:sarsa-colour-run-5" in out


def test_the_menu_trains_an_agent() -> None:
    buf = io.StringIO()
    ui = make_ui(plain=True, width=80, file=buf)
    answers = iter(["7", "", "q"])
    run_menu(ui, read=lambda prompt: next(answers))
    out = buf.getvalue()
    assert "PERFECT PLAY" in out and "Next time, type: busride train" in out


def test_the_report_shows_the_curve_and_the_time() -> None:
    from busride.ui import train as train_ui

    t = replace(train(RTB, 20_000, seed=1, checkpoints=4), seconds=1.0)
    buf = io.StringIO()
    ui = make_ui(plain=True, width=80, file=buf)
    ui.console.print(train_ui.report(t, RTB, None, None, ui))
    out = buf.getvalue()
    assert "20,000 rounds in 1.00 s" in out and "Gives up, over time" in out


# ── the Gymnasium environment ────────────────────────────────────────────────────────────


def test_the_gymnasium_environment() -> None:
    gymnasium = pytest.importorskip("gymnasium")
    from gymnasium.utils.env_checker import check_env

    from busride.agents.rl.env import BusRideEnv

    env = BusRideEnv("ride-the-bus")
    check_env(env, skip_render_check=True)
    obs, info = env.reset(seed=3)
    assert obs["stage"] == 0 and list(info["legal"]) == [
        env.moves.index("red"),
        env.moves.index("black"),
    ]
    _, reward, terminated, _, info = env.step(env.moves.index("cash"))  # not allowed yet
    assert terminated and reward == -1.0 and info["illegal"]
    # always red, then cash out: pays 1.8 half the time, so the mean reward is -0.1
    rewards = []
    for seed in range(4000):
        env.reset(seed=seed)
        _, r, done, _, _ = env.step(env.moves.index("red"))
        if not done:
            _, r, done, _, _ = env.step(env.moves.index("cash"))
        assert done
        rewards.append(r)
    mean = sum(rewards) / len(rewards)
    assert abs(mean - (-0.1)) < 4 * 0.9 / len(rewards) ** 0.5
    assert isinstance(gymnasium.spaces.Discrete(2), gymnasium.Space)
    hi_lo = BusRideEnv("hi-lo-5")
    obs, info = hi_lo.reset(seed=1)
    assert obs["stage"] == 1 and obs["cards"][0] > 0  # the shown card is dealt at once
