"""Screens rendered at width 80 and compared with stored text. Regenerate the stored text with
UPDATE_SNAPSHOTS=1 after a deliberate change, then read the diff before committing."""

import functools
import io
import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Group, RenderableType

from busride.agents.base import Action, Observation, describe
from busride.agents.baselines import AI_AGENTS, BASELINES, make_agent
from busride.agents.llm.anthropic_agent import ClaudeAgent
from busride.agents.llm.prices import BUILT_IN
from busride.agents.rl.qlearning import Training, train
from busride.arena.runner import Arena
from busride.arena.runs import RunFile
from busride.arena.scoring import score
from busride.coach.explain import review, why
from busride.engine import solver
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_card, parse_cards
from busride.engine.policy import cheatsheet
from busride.engine.rules import Rules
from busride.play import Round, Session
from busride.sim import Greedy, generate_rounds, simulate
from busride.stats.report import verify
from busride.ui import arena as arena_ui
from busride.ui import play as play_ui
from busride.ui import screens
from busride.ui import train as train_ui
from busride.ui.banner import footer
from busride.ui.theme import Ui, make_ui

from .conftest import BASE, FAIR_LADDER

SNAPSHOTS = Path(__file__).parent / "snapshots"
FAIR = BASE.with_returns(FAIR_LADDER)  # type: ignore[arg-type]
LADDER = BASE.with_returns((1.9, 2.5, 3.8, 14.0))


def _advisor(cards: str, rules: Rules = FAIR) -> Callable[[Ui], RenderableType]:
    def build(ui: Ui) -> RenderableType:
        decision = solver.decide(solver.solve(rules), parse_cards(cards) if cards else [])
        return screens.advisor(decision, rules, ui)

    return build


def _policy(rules: Rules = LADDER) -> Callable[[Ui], RenderableType]:
    def build(ui: Ui) -> RenderableType:
        sol = solver.solve(rules)
        return screens.policy(rules, sol.rtp, cheatsheet(sol), ui)

    return build


def _games(ui: Ui) -> RenderableType:
    rows = [
        screens.GameRow(name, spec.description, solver.solve(spec).rtp, name == "ride-the-bus")
        for name, spec in BUILTIN_GAMES.items()
    ]
    rows.append(screens.GameRow("two-colours", "Two red-or-black calls", 0.975, yours=True))
    return screens.games_list(rows, ui)


def _play_round(cards: str) -> tuple[Session, Round]:
    session = Session(BUILTIN_GAMES["ride-the-bus"], chips=1000, stake=10, cards=parse_cards(cards))
    return session, session.new_round()


def _play_table(ui: Ui) -> RenderableType:
    _, rnd = _play_round("6h 3s")
    rnd.act("red")
    return play_ui.table(rnd, rnd.decision(), True, ui)


def _play_steps(ui: Ui) -> RenderableType:
    session, rnd = _play_round("6h 3s 9d")
    lines = []
    for move in ("red", "lower", "cash"):
        decision = rnd.decision()
        step = rnd.act(move)
        assert step.graded is not None
        lines += [
            play_ui.after(step, rnd, ui),
            play_ui.coach_line(review(step.graded, 10), ui),
            play_ui.why_line(why(decision, rnd.rules)),
        ]
    lines.append(play_ui.round_line(rnd, session.chips, 10, ui))
    return Group(*lines)


def _play_summary(ui: Ui) -> RenderableType:
    session, rnd = _play_round("6h 3s 2c")
    rnd.act("red")
    rnd.act("lower")
    rnd.act("cash")
    session.new_round().act("red")  # 2c is black
    return play_ui.summary(session.summary(), 10, footer(rnd.rules, ui), ui)


def _menu(ui: Ui) -> RenderableType:
    line = f"Your game: Ride the Bus {ui.g.dot} payouts 1.80 2.30 3.20 12.00"
    return screens.home_menu(line, 0.963, screens.MENU_ITEMS, ui)


HI_LO = BUILTIN_GAMES["hi-lo-5"]


def _verify(n: int) -> Callable[[Ui], RenderableType]:
    def build(ui: Ui) -> RenderableType:
        logs = generate_rounds(LADDER, Greedy(LADDER), n, seed=4)
        rounds = [[parse_card(c) for c in cards] for cards, _ in logs]
        return screens.verify_report(verify(rounds, LADDER), LADDER, ui)

    return build


def _sim(ui: Ui) -> RenderableType:
    res = simulate(LADDER, Greedy(LADDER, 2), 20_000, seed=3)
    plan = solver.fixed_plan(LADDER, 2)
    return screens.sim_report(res, LADDER, ui, "stop:2", plan.value, plan, seed=3, timing=False)


class _Hunch:
    """Plays the likeliest guess but always says 60%, and fumbles its first answer at stage 3."""

    name = "hunch"

    def __init__(self) -> None:
        self.greedy = make_agent("greedy", BUILTIN_GAMES["ride-the-bus"])

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        if obs.stage == 3 and obs.feedback is None:
            return Action("maybe")
        return Action(self.greedy.decide(obs).move, 0.6, "a hunch")


_ARENA_DIR = tempfile.TemporaryDirectory(prefix="busride-snapshots-")


@functools.cache
def _arena_run() -> RunFile:
    rules = BUILTIN_GAMES["ride-the-bus"]
    agents = [make_agent(a, rules) for a in ("optimal", "greedy", "stop:2", "random")]
    path = Path(_ARENA_DIR.name) / "demo.jsonl"
    return Arena(rules, path, seed=7, deals=200).run([*agents, _Hunch()])


def _arena_leaderboard(ui: Ui) -> RenderableType:
    run = _arena_run()
    rules = run.rules()
    boards = list(score(run).values())
    return arena_ui.leaderboard("demo", run.header(), rules, boards, solver.solve(rules).rtp, ui)


def _arena_replay(ui: Ui) -> RenderableType:
    run = _arena_run()
    number = 2
    finished = {(r["agent"], r["deal"]): r for r in run.finished()}
    plays = [
        (
            a,
            [d for d in run.decisions() if d["agent"] == a and d["deal"] == number],
            finished[a, number],
        )
        for a in run.agents()
    ]
    deals = run.header()["deals"]
    return arena_ui.replay("demo", number, len(deals), deals[1], plays, run.rules(), ui)


def _arena_worst(ui: Ui) -> RenderableType:
    mine = [d for d in _arena_run().decisions() if d["agent"] == "greedy"]
    costly = sorted(mine, key=lambda d: (-d["regret"], d["deal"]))[:10]
    return arena_ui.mistakes("demo", "greedy", costly, len(mine), ui)


def _arena_human(ui: Ui) -> RenderableType:
    rules = BUILTIN_GAMES["ride-the-bus"]
    obs = Observation(
        game=rules.name,
        stage=3,
        stages=4,
        question="Inside or outside",
        kind="inside_outside",
        options=("inside", "outside"),
        can_cash_out=True,
        seen=tuple(parse_cards("9h Ks")),
        compare=tuple(parse_cards("9h Ks")),
        cash_value=2.3,
        ladder=rules.returns,
        rules=describe(rules),
    )
    return arena_ui.human_table(obs, ui)


def _fake_claude() -> object:
    """A stand-in for the Anthropic client: the first legal guess, at 70%, with fixed usage."""

    def create(**params: object) -> object:
        messages = params["messages"]
        assert isinstance(messages, list)
        text = messages[-1]["content"]
        choice = text.split("Legal moves: ")[1].split(",")[0].split(" (")[0].rstrip(".")
        call = SimpleNamespace(
            type="tool_use", name="make_guess", input={"choice": choice, "win_probability": 0.7}
        )
        usage = SimpleNamespace(
            input_tokens=120,
            output_tokens=900,
            cache_read_input_tokens=700,
            cache_creation_input_tokens=0,
            iterations=None,
        )
        return SimpleNamespace(
            content=[call], stop_reason="tool_use", stop_details=None, model="claude-opus-5-5",
            usage=usage,
        )  # fmt: skip

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


@functools.cache
def _arena_ai_run() -> RunFile:
    rules = BUILTIN_GAMES["ride-the-bus"]
    agents = [make_agent(a, rules) for a in ("optimal", "greedy")]
    claude = ClaudeAgent(rules, client=_fake_claude())
    path = Path(_ARENA_DIR.name) / "ai.jsonl"
    return Arena(rules, path, seed=7, deals=20).run([*agents, claude])


def _arena_ai_leaderboard(ui: Ui) -> RenderableType:
    run = _arena_ai_run()
    rules = run.rules()
    boards = list(score(run).values())
    for d in run.decisions():  # timings vary run to run: show a fixed one
        assert d["seconds"] >= 0
    boards = [replace(b, seconds=2.5) if b.meta.get("requests") else b for b in boards]
    return arena_ui.leaderboard("ai", run.header(), rules, boards, solver.solve(rules).rtp, ui)


@functools.cache
def _training() -> Training:
    t = train(BUILTIN_GAMES["ride-the-bus"], 100_000, seed=1, checkpoints=20)
    return replace(t, seconds=0.35)  # timing varies run to run


def _train_report(ui: Ui) -> RenderableType:
    t = _training()
    return train_ui.report(
        t, t.learner.rules, "q-ride-the-bus", "C:/Users/you/AppData/Local/busride/agents", ui
    )


def _train_live(ui: Ui) -> RenderableType:
    t = _training()
    return train_ui.live(t.curve[:12], t.optimal, 100_000, ui)


def _arena_runs(ui: Ui) -> RenderableType:
    rows = [
        arena_ui.RunRow(
            "ride-the-bus-seed7-2000",
            "Ride the Bus",
            2000,
            ("optimal", "greedy", "stop:2", "random"),
            "2026-10-24T09:15:00",
        ),
        arena_ui.RunRow("hi-lo", "Hi-Lo 5", 20, ("optimal", "human"), "2026-10-23T20:01:12"),
        arena_ui.RunRow("broken", "", 0, (), "", problem="broken.jsonl is not an arena run"),
    ]
    return arena_ui.runs_list(rows, "C:/Users/you/AppData/Local/busride/runs", ui)


SCREENS: dict[str, Callable[[Ui], RenderableType]] = {
    "advise_9h_ks": _advisor("9h Ks"),
    "advise_start": _advisor(""),
    "advise_stage4": _advisor("2h 5s 9d", LADDER),
    "analyze": lambda ui: screens.analysis(solver.analyze(LADDER), ui, timing=False),
    "analyze_no_ladder": lambda ui: screens.analysis(solver.analyze(BASE), ui, timing=False),
    "policy": _policy(),
    "verify": _verify(300),
    "verify_few_rounds": _verify(5),  # most tests still waiting for data
    "sim": _sim,
    "rules": lambda ui: screens.rules_panel(LADDER, ["An example warning."], ui),
    "round_over": lambda ui: screens.round_over(parse_cards("2h 9s 5d 7c"), FAIR, ui),
    # play
    "play_table": _play_table,
    "play_steps": _play_steps,
    "play_summary": _play_summary,
    # the arena
    "arena_leaderboard": _arena_leaderboard,
    "arena_replay": _arena_replay,
    "arena_worst": _arena_worst,
    "arena_human": _arena_human,
    "arena_runs": _arena_runs,
    "arena_agents": lambda ui: arena_ui.agents_list(BASELINES, AI_AGENTS, ui),
    "arena_ai_leaderboard": _arena_ai_leaderboard,
    "arena_cost_estimate": lambda ui: arena_ui.cost_estimate(
        [
            arena_ui.CostRow("claude:claude-opus-5-5", 20, 0.84),
            arena_ui.CostRow("openai:gpt-x", 20, None),
            arena_ui.CostRow("ollama:qwen3:4b", 20, 0.0),
        ],
        "Prices: built in, checked 2026-10-06. See or edit them: busride arena prices",
        2.0,
        measured=False,
        ui=ui,
    ),
    "train_report": _train_report,
    "train_live": _train_live,
    "train_intro": lambda ui: train_ui.intro(
        BUILTIN_GAMES["ride-the-bus"], "q-learning", 300_000, ui
    ),
    "arena_prices": lambda ui: arena_ui.prices_table(
        [(n, p.input, p.output, p.cache_read) for n, p in BUILT_IN.items()],
        "built in",
        "2026-10-06",
        ui,
    ),
    # the beginner shell
    "menu": _menu,
    "settings": lambda ui: screens.settings_panel(
        [("Your game", "Ride the Bus (ride-the-bus)"), ("Coach", "review")],
        [("Settings file", "C:/Users/you/AppData/Local/busride/config.toml")],
        ui,
    ),
    "doctor": lambda ui: screens.doctor_report(
        [
            ("good", "Python", "3.13"),
            ("warn", "Card symbols", "add --ascii"),
            ("muted", "ANTHROPIC_API_KEY", "not set"),
        ],
        [("Settings folder", "C:/Users/you/AppData/Local/busride")],
        ui,
    ),
    # the other built-in games
    "games": _games,
    "hi_lo_rules": lambda ui: screens.rules_panel(HI_LO, [], ui),
    "hi_lo_analyze": lambda ui: screens.analysis(solver.analyze(HI_LO), ui, timing=False),
    "hi_lo_advise": _advisor("7h", HI_LO),
    "hi_lo_advise_later": _advisor("7h Qs 4d", HI_LO),
    "hi_lo_reveal": lambda ui: screens.reveal_wait([], HI_LO, ui),
    "hi_lo_policy": _policy(HI_LO),
    "in_between_policy": _policy(BUILTIN_GAMES["in-between"]),
    "colour_run_policy": _policy(BUILTIN_GAMES["colour-run-5"]),
    "colour_run_sim": lambda ui: screens.sim_report(
        simulate(
            BUILTIN_GAMES["colour-run-5"], Greedy(BUILTIN_GAMES["colour-run-5"]), 5000, seed=1
        ),
        BUILTIN_GAMES["colour-run-5"],
        ui,
        "greedy",
        None,
        seed=1,
        timing=False,
    ),
}


def render(
    build: Callable[[Ui], RenderableType],
    *,
    plain: bool = True,
    ascii: bool = False,
    color: bool = False,
) -> str:
    buf = io.StringIO()
    ui = make_ui(plain=plain, ascii=ascii, width=80, file=buf, force_terminal=color)
    ui.console.print(build(ui))
    return buf.getvalue()


@pytest.mark.parametrize("name", list(SCREENS))
def test_snapshot_at_width_80(name: str) -> None:
    text = render(SCREENS[name])
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.exists(), f"no snapshot for {name}: run with UPDATE_SNAPSHOTS=1"
    assert text == path.read_text(encoding="utf-8")
    assert max(len(line) for line in text.splitlines()) <= 80
    assert "…" not in text, "a column was too narrow and Rich cut its text short"


@pytest.mark.parametrize("name", list(SCREENS))
def test_plain_has_no_escape_codes(name: str) -> None:
    assert "\x1b" not in render(SCREENS[name], plain=True, color=True)


@pytest.mark.parametrize("name", list(SCREENS))
def test_ascii_mode_is_pure_ascii(name: str) -> None:
    text = render(SCREENS[name], ascii=True)
    assert all(ord(ch) < 128 for ch in text), {ch for ch in text if ord(ch) >= 128}


def test_colour_mode_uses_colour() -> None:
    assert "\x1b[" in render(SCREENS["advise_9h_ks"], plain=False, color=True)


def test_no_color_env_drops_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    text = render(SCREENS["advise_9h_ks"], plain=False, color=True)
    assert "38;" not in text  # no foreground colours, only bold
