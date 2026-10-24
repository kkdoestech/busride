"""Render the main screens to SVG for the README (docs/demo/*.svg).

    uv run python scripts/record_demo.py

Every screen comes from the real code. The odds, advice and cheat-sheet screens use an example
ladder (1.9, 2.5, 3.8, 14); the rest use the built-in Ride the Bus.
"""

import io
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rich.console import Group, RenderableType

from busride.agents.baselines import make_agent
from busride.agents.rl.qlearning import train
from busride.arena.runner import Arena
from busride.arena.scoring import score
from busride.coach.explain import review, why
from busride.engine import solver
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_cards
from busride.engine.policy import cheatsheet
from busride.engine.rules import Rules
from busride.play import Session
from busride.ui import arena as arena_ui
from busride.ui import play as play_ui
from busride.ui import screens
from busride.ui import train as train_ui
from busride.ui.theme import Ui, make_ui

OUT = Path(__file__).resolve().parents[1] / "docs" / "demo"
RTB = BUILTIN_GAMES["ride-the-bus"]
EXAMPLE = Rules(
    game_version="example",
    captured_on="2026-10-24",
    returns=(1.9, 2.5, 3.8, 14.0),
    source="example ladder",
)


def save(name: str, title: str, build: Callable[[Ui], RenderableType]) -> None:
    ui = make_ui(width=80, record=True, force_terminal=True, file=io.StringIO())
    ui.console.print(f"$ {title}", style="muted")
    ui.console.print(build(ui))
    OUT.mkdir(parents=True, exist_ok=True)
    ui.console.save_svg(str(OUT / f"{name}.svg"), title=title)
    print("wrote", OUT / f"{name}.svg")


def _menu(ui: Ui) -> RenderableType:
    line = f"Your game: Ride the Bus {ui.g.dot} payouts 1.80 2.30 3.20 12.00"
    return screens.home_menu(line, solver.solve(RTB).rtp, screens.MENU_ITEMS, ui)


def _play(ui: Ui) -> RenderableType:
    session = Session(RTB, chips=1000, stake=10, cards=parse_cards("6h 3s 9d"))
    rnd = session.new_round()
    lines: list[RenderableType] = []
    for move in ("red", "lower"):
        decision = rnd.decision()
        lines.append(play_ui.table(rnd, decision, True, ui))
        step = rnd.act(move)
        assert step.graded is not None
        lines += [
            play_ui.after(step, rnd, ui),
            play_ui.coach_line(review(step.graded, 10), ui),
            play_ui.why_line(why(decision, RTB)),
        ]
    lines.append(play_ui.table(rnd, rnd.decision(), True, ui))
    return Group(*lines)


def _arena(ui: Ui) -> RenderableType:
    with tempfile.TemporaryDirectory() as folder:
        agents = [make_agent(a, RTB) for a in ("optimal", "stop:2", "greedy", "random")]
        run = Arena(RTB, Path(folder) / "demo.jsonl", seed=7, deals=2000).run(agents)
        boards = list(score(run).values())
        header, rules = run.header(), run.rules()
    name = "ride-the-bus-seed7-2000"
    return arena_ui.leaderboard(name, header, rules, boards, solver.solve(RTB).rtp, ui)


def _train(ui: Ui) -> RenderableType:
    t = replace(train(RTB, 300_000, seed=1), seconds=0.9)
    where = "C:/Users/you/AppData/Local/busride/agents/q-ride-the-bus.json"
    return train_ui.report(t, RTB, "q-ride-the-bus", where, ui)


def main() -> None:
    sol = solver.solve(EXAMPLE)
    save("menu", "busride", _menu)
    save("play", "busride play", _play)
    save(
        "odds",
        "busride odds",
        lambda ui: screens.analysis(solver.analyze(EXAMPLE), ui, timing=False),
    )
    save(
        "advise",
        "busride advise 9h Ks",
        lambda ui: screens.advisor(solver.decide(sol, parse_cards("9h Ks")), EXAMPLE, ui),
    )
    sheet = cheatsheet(sol)
    save("cheatsheet", "busride cheatsheet", lambda ui: screens.policy(EXAMPLE, sol.rtp, sheet, ui))
    save("arena", "busride arena run", _arena)
    save("train", "busride train", _train)


if __name__ == "__main__":
    main()
