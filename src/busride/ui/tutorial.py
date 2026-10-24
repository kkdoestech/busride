"""The tutorial: four short pages for someone who knows the card game and nothing else."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from busride.engine.rules import Rules
from busride.engine.solver import Decision
from busride.ui import fmt, screens
from busride.ui.theme import Ui

PAGES = ("What busride does", "How to read the advice", "Is the game fair?", "Where to go next")


def _page(number: int, ui: Ui, *body: RenderableType) -> Group:
    head = Text(
        f"busride tutorial {ui.g.dot} {number} of {len(PAGES)} {ui.g.dot} {PAGES[number - 1]}",
        style="heading",
    )
    return Group(head, Text(""), *body)


def _bullets(lines: list[str], ui: Ui) -> Text:
    out = Text()
    for i, line in enumerate(lines):
        if i:
            out.append("\n")
        out.append(f"  {ui.g.dot} ", style="accent")
        out.append(line)
    return out


def pages(rules: Rules, example: Decision, rtp: float, ui: Ui) -> list[RenderableType]:
    """The pages, in order. `example` is the advice for 9h Ks, `rtp` the game's return."""
    stages = Table.grid(padding=(0, 2))
    stages.add_column(style="accent", justify="right")
    stages.add_column(style="heading", no_wrap=True)
    stages.add_column()
    for number, (question, win) in enumerate(
        [
            ("Red or black?", "the first card has the colour you named"),
            ("Higher or lower?", "the second card is higher or lower than the first, as you said"),
            ("Inside or outside?", "the third card falls between the first two, or outside them"),
            ("Which suit?", "the fourth card has the suit you named"),
        ],
        start=1,
    ):
        stages.add_row(str(number), question, Text(f"you win if {win}", style="muted"))

    one = _page(
        1,
        ui,
        Text("You bet a stake, then answer up to four questions, one card at a time:"),
        Text(""),
        stages,
        Text(""),
        Text(
            "After each win you can cash out (take the money) or ride on. A wrong answer loses "
            "the stake. busride works out the best play exactly, for every card you could see:",
            style="muted",
        ),
        Text(""),
        _bullets(
            [
                "advice for the cards on the table right now",
                "a cheat sheet with the best play for every situation",
                "how much the game takes from you in the long run, and where",
            ],
            ui,
        ),
    )

    two = _page(
        2,
        ui,
        Text("Say you see a 9 of hearts, then a king of spades. busride shows:"),
        Text(""),
        screens.advisor(example, rules, ui),
        Text(""),
        _bullets(
            [
                "Each bar is a guess. 32/50 means 32 of the 50 cards left in the deck make it win.",
                "TIE: cards equal to one of yours. Here a tie loses.",
                "The last line is the decision: what cashing out pays now, against what going on "
                "is worth on average. The bigger one wins.",
            ],
            ui,
        ),
    )

    edge = 1 - rtp
    three = _page(
        3,
        ui,
        Text(screens.per_hundred(rtp)),
        Text(""),
        Text(
            f"That missing {fmt.pct(edge)} is the house edge: what the game keeps over many "
            "rounds. No strategy removes it; busride shows the one that loses least. In a short "
            "session luck matters far more, so you can still win (or lose) a lot.",
            style="muted",
        )
        if edge > 0
        else Text(
            "With these payouts perfect play comes out ahead in the long run.", style="muted"
        ),
    )

    commands = Table.grid(padding=(0, 2))
    commands.add_column(style="heading", no_wrap=True)
    commands.add_column()
    for cmd, what in (
        ("busride", "the menu: everything below, one number away"),
        ("busride advise", "live advice: type the cards as they appear"),
        ("busride cheatsheet", "the best play for every situation, to keep open"),
        ("busride odds", "how fair the game is, stage by stage"),
        ("busride games", "other games, and your own"),
        ("busride settings", "your payouts and chips"),
        ("busride doctor", "check your setup"),
    ):
        commands.add_row(cmd, Text(what, style="muted"))
    four = _page(
        4,
        ui,
        commands,
        Text(""),
        Panel(
            Text("Start with `busride`: the menu has all of this, and nothing to remember."),
            box=ui.g.panel,
            border_style="accent",
            width=min(ui.width, 72),
        ),
    )
    return [one, two, three, four]
