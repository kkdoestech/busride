"""Screens for `busride train`: what is happening, a live learning curve, and the result."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from busride.agents.rl.qlearning import Checkpoint, Training
from busride.engine.game import GameSpec
from busride.play import CLOSE
from busride.ui import fmt
from busride.ui.banner import footer, heading, title, verdict
from busride.ui.bars import bar, sparkline
from busride.ui.theme import Ui

GAP = Text("")
NAMES = {"q-learning": "Q-learning", "sarsa": "SARSA"}
HOW = {
    "q-learning": "learns what each move is worth if it played perfectly from then on",
    "sarsa": "learns what each move is worth the way it actually plays, exploring included",
}
MATCHES = 0.001  # within 0.1 chip per 100 bet: as good as perfect play


def intro(rules: GameSpec, algorithm: str, episodes: int, ui: Ui) -> Text:
    return Text(
        f"The agent starts knowing nothing about {rules.name}. It plays {fmt.count(episodes)} "
        "practice rounds, sees only what each move paid, and keeps a running average of how "
        f"good each move is in each situation ({NAMES[algorithm]} {HOW[algorithm]}). Every few "
        "thousand rounds busride works out exactly what its current moves are worth, so the "
        "curve has no luck in it.",
        style="muted",
    )


def live(points: Sequence[Checkpoint], optimal: float, total: int, ui: Ui) -> Panel:
    last = points[-1]
    gave = [max(0.0, optimal - p.value) for p in points]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()
    grid.add_row(
        "Rounds played",
        Text.assemble(
            bar(last.episodes / max(1, total), 24, "accent", ui),
            f"  {fmt.count(last.episodes)} of {fmt.count(total)}",
        ),
    )
    grid.add_row(
        "Its moves are worth",
        f"{fmt.hundred(last.value)} per 100 bet (perfect play: {fmt.hundred(optimal)})",
    )
    grid.add_row("It gives up", f"{fmt.hundred(gave[-1])} per 100 bet")
    grid.add_row("Gives up, over time", sparkline(gave, 40, ui))
    grid.add_row("Exploring", f"{fmt.pct(last.epsilon, 0)} of its moves are random tries")
    return Panel(
        grid,
        title=title("train", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 72),
    )


def _kind(regret: float) -> tuple[str, str]:
    if regret <= MATCHES:
        return "good", "MATCHES PERFECT PLAY"
    if regret <= CLOSE:
        return "warn", "CLOSE TO PERFECT PLAY"
    return "bad", "STILL LEARNING"


def report(t: Training, rules: GameSpec, name: str | None, saved: str | None, ui: Ui) -> Group:
    learner = t.learner
    kind, headline = _kind(t.regret)
    detail = (
        f"After {fmt.count(learner.episodes)} practice rounds it gives up "
        f"{fmt.hundred(t.regret)} chips per 100 bet against perfect play: it gets back "
        f"{fmt.hundred(t.value)} of every 100 (perfect play: {fmt.hundred(t.optimal)})."
    )
    states = sum(
        len(level) for k, level in enumerate(learner.game.tree.levels) if rules.stages[k].is_guess
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()
    grid.add_row("Method", f"{NAMES[learner.algorithm]}: {HOW[learner.algorithm]}")
    grid.add_row(
        "Practice",
        f"{fmt.count(learner.episodes)} rounds in {fmt.duration(t.seconds)} (seed {learner.seed})",
    )
    grid.add_row("Situations met", f"{fmt.count(len(learner.q))} of {fmt.count(states)}")
    gave = [max(0.0, t.optimal - c.value) for c in t.curve]
    grid.add_row("Gives up, over time", sparkline(gave, 40, ui))

    table = Table(
        box=ui.g.table, pad_edge=False, show_edge=False, header_style="muted", padding=(0, 1)
    )
    table.add_column("After rounds", justify="right", no_wrap=True)
    table.add_column("Its moves are worth", justify="right", no_wrap=True)
    table.add_column("Gives up", justify="right", no_wrap=True)
    picks = sorted({round(f * (len(t.curve) - 1)) for f in (0, 0.1, 0.25, 0.5, 0.75, 1)})
    for i in picks:
        c = t.curve[i]
        table.add_row(fmt.count(c.episodes), fmt.hundred(c.value), fmt.hundred(gave[i]))

    rows: list[RenderableType] = [
        heading(title("train", ui), ui, rules.name),
        verdict(kind, headline, detail, ui),
        grid,
        GAP,
        Padding(table, (0, 0, 0, 2)),
        GAP,
    ]
    if saved and name:
        rows += [
            Text(f"Saved as rl:{name}: {saved}", style="muted", overflow="fold"),
            Text("Play it against the others in the arena:", style="accent"),
            Text(f"  busride arena run --agents optimal,rl:{name},greedy", style="accent"),
        ]
    if t.regret > CLOSE:
        rows.append(
            Text("More practice helps: try --episodes with a bigger number.", style="muted")
        )
    rows += [GAP, footer(rules, ui)]
    return Group(*rows)
