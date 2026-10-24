"""Screens for `busride arena`: the leaderboard, a deal replayed move by move, saved runs,
the agents you can use, and the table when you play in the arena yourself."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from busride.agents.base import CASH, Observation
from busride.arena.scoring import Board
from busride.engine.cards import parse_card
from busride.engine.game import GameSpec
from busride.play import CLOSE
from busride.ui import fmt
from busride.ui.banner import footer, heading, title
from busride.ui.cards import card_row, cards_inline
from busride.ui.theme import Ui

GAP = Text("")
_ENDS = {
    "lost": "lost at stage {next}",
    "cash": "cashed out after stage {survived}",
    "walk": "walked away before betting",
    "push": "pushed at stage {next}",
    "full": "rode the bus to the end",
    "forfeit": "forfeited at stage {next}",
}


def _table(ui: Ui) -> Table:
    return Table(
        box=ui.g.table,
        pad_edge=False,
        show_edge=False,
        header_style="muted",
        collapse_padding=True,
        padding=(0, 1),
    )


def _given_up_style(regret: float, value: float) -> str:
    if regret <= 1e-9:
        return "good.soft"
    return "warn.soft" if regret <= CLOSE * max(value, 1e-9) else "bad.soft"


def _indent(r: RenderableType) -> Padding:
    return Padding(r, (0, 0, 0, 2))


def _move(move: str | None) -> str:
    return {CASH: "cash out", "forfeit": "forfeit", None: "?"}.get(move, move or "?")


def payouts_line(rules: GameSpec) -> str:
    return "payouts " + " ".join(fmt.ret(r) for r in rules.returns)


def run_line(header: dict[str, Any], rules: GameSpec, ui: Ui) -> str:
    d = ui.g.dot
    deals = len(header["deals"])
    return (
        f"{rules.name} {d} {fmt.count(deals)} duplicate deal{'s' if deals != 1 else ''} {d} "
        f"seed {header['seed']} {d} {payouts_line(rules)}"
    )


def _calibration(b: Board, ui: Ui) -> Text:
    if b.calibration is None:
        return Text(ui.g.dash, style="muted")
    if b.calibration <= 1e-9:
        return Text("exact")
    return Text(fmt.points(b.calibration))


def _times(n: int) -> str:
    return "once" if n == 1 else f"{fmt.count(n)} times"


def _notes(boards: Sequence[Board]) -> list[str]:
    out = []
    for b in boards:
        parts = []
        if b.too_bold:
            parts.append(f"kept going {_times(b.too_bold)} when cashing out was better")
        if b.too_timid:
            parts.append(f"cashed out {_times(b.too_timid)} when playing on was better")
        if parts:
            out.append(f"{b.agent}: {', and '.join(parts)}.")
        if b.forfeits:
            out.append(
                f"{b.agent} forfeited {_times(b.forfeits)}: its answer was still unusable "
                "after one retry, so the deal was lost."
            )
        elif b.retries:
            out.append(f"{b.agent} needed a second try {_times(b.retries)}.")
        if b.coverage < 1:
            out.append(
                f"{b.agent}: {fmt.pct(b.coverage)} of its decisions could be graded exactly; the "
                "rest were in parts of the game too big to solve."
            )
    return out


def _cost(b: Board, ui: Ui) -> Text:
    m = b.meta
    if not m.get("requests"):
        return Text(ui.g.dash, style="muted")
    if m.get("free") or m.get("local"):
        return Text("free")
    if m.get("cost_unknown"):
        return Text("?", style="warn.soft")
    return Text(fmt.dollars(m.get("cost", 0.0)))


def _ai_notes(boards: Sequence[Board]) -> list[str]:
    """Speed, tokens, the cache and fallbacks, for the agents that called a model."""
    out = []
    for b in boards:
        m = b.meta
        requests = m.get("requests", 0)
        if not requests or not b.decisions:
            continue
        line = (
            f"{b.agent}: {fmt.duration(b.seconds)} and "
            f"{fmt.count(m.get('output_tokens', 0) / b.decisions)} output tokens per decision"
        )
        prompt_in = (
            m.get("input_tokens", 0)
            + m.get("cache_read_tokens", 0)
            + m.get("cache_write_tokens", 0)
        )
        if prompt_in and not m.get("local"):
            share = m.get("cache_read_tokens", 0) / prompt_in
            line += f"; {fmt.pct(share, 0)} of its prompts came from the cache"
        out.append(line + ".")
        if m.get("cost_unknown"):
            out.append(
                f"{b.agent}: its price isn't in your price table, so its cost is unknown "
                "(busride arena prices)."
            )
        if m.get("fallback"):
            n = int(m["fallback"])
            out.append(
                f"{b.agent}: {n} answer{'s' if n != 1 else ''} came from a fallback model after "
                "the first declined (run with --no-fallback to test the model alone)."
            )
    return out


def leaderboard(
    name: str,
    header: dict[str, Any],
    rules: GameSpec,
    boards: Sequence[Board],
    rtp: float | None,
    ui: Ui,
) -> Group:
    priced = any(b.meta.get("requests") for b in boards)
    t = _table(ui)
    t.add_column("#", justify="right", no_wrap=True, style="muted")
    t.add_column("Agent", overflow="fold", style="heading")
    t.add_column("Gives\nup", justify="right", no_wrap=True)
    t.add_column("Best\nmove", justify="right", no_wrap=True)
    t.add_column("Odds\nerror", justify="right", no_wrap=True)
    t.add_column("Return", justify="right", no_wrap=True)
    t.add_column("vs\noptimal", justify="right", no_wrap=True)
    if priced:
        t.add_column("Cost", justify="right", no_wrap=True)
    pm = "+/-" if ui.ascii else "±"
    for rank, b in enumerate(boards, start=1):
        rate = b.best_rate
        vs = (
            Text(f"{fmt.signed_hundred(b.vs_optimal[0])} {pm}{fmt.hundred(b.vs_optimal[1])}")
            if b.vs_optimal is not None
            else Text(ui.g.dash, style="muted")
        )
        cells: list[RenderableType] = [
            str(rank),
            b.agent,
            fmt.hundred(b.given_up_per_deal),
            fmt.pct(rate, 0) if rate is not None else Text(ui.g.dash, style="muted"),
            _calibration(b, ui),
            fmt.hundred(b.mean_return),  # luck included, so no colour: colour means value
            vs,
        ]
        t.add_row(*cells, *([_cost(b, ui)] if priced else []))
    rows: list[RenderableType] = [
        heading(title("arena", ui), ui, name),
        Text(run_line(header, rules, ui), style="muted"),
    ]
    others = [b for b in boards if b.agent != "optimal"]
    if rtp is not None and others:
        top = others[0]
        rows.append(
            Text(
                f"Perfect play gets back {fmt.hundred(rtp)} of every 100 bet, on average. "
                f"Closest to it here: {top.agent}, giving up {fmt.hundred(top.given_up_per_deal)}."
            )
        )
    rows += [GAP, t, GAP]
    legend = [
        "Gives up: chips lost to imperfect play per 100 bet, on average. Luck doesn't count: "
        "0 is perfect.",
        "Best move: how often it made the best move, counting only choices that mattered.",
        "Odds error: how far the win chances it stated were from the exact ones.",
        "Return: what it actually got back per 100 bet on these deals, luck included. "
        "vs optimal: the gap to perfect play on the same deals, give or take (95%).",
    ]
    rows += [_indent(Text(line, style="muted")) for line in legend]
    if priced:
        rows.append(
            _indent(Text("Cost: what its AI model calls cost, in US dollars.", style="muted"))
        )
    notes = _notes(boards)
    if notes:
        rows += [GAP, Text("Habits (counting only moves worse by more than 2%):", style="heading")]
        rows += [_indent(Text(line)) for line in notes]
    ai = _ai_notes(boards)
    if ai:
        rows += [GAP, Text("AI models:", style="heading")]
        rows += [_indent(Text(line)) for line in ai]
    rows += [GAP, footer(rules, ui)]
    return Group(*rows)


@dataclass(frozen=True)
class RunRow:
    name: str
    game: str
    deals: int
    agents: tuple[str, ...]
    created: str
    problem: str = ""


def runs_list(rows: Sequence[RunRow], folder: str, ui: Ui) -> Group:
    t = _table(ui)
    t.add_column("Name", no_wrap=True, style="heading")
    t.add_column("Game", no_wrap=True)
    t.add_column("Deals", justify="right", no_wrap=True)
    t.add_column("Agents", overflow="fold")
    t.add_column("Started", no_wrap=True, style="muted")
    for r in rows:
        if r.problem:
            t.add_row(r.name, "", "", Text(r.problem, style="warn.soft"), "")
            continue
        t.add_row(
            r.name,
            r.game,
            fmt.count(r.deals),
            ", ".join(r.agents) or Text("none yet", style="muted"),
            r.created.replace("T", " ")[:16],
        )
    count = f"{len(rows)} saved" if len(rows) != 1 else "1 saved"
    return Group(
        heading(title("arena runs", ui), ui, count),
        t,
        GAP,
        _indent(
            Text(
                "See one: busride arena leaderboard NAME. Add agents to one: busride arena run "
                "--name NAME --agents ...",
                style="muted",
            )
        ),
        Text(f"Saved in {folder}", style="muted", overflow="fold"),
    )


def no_runs(ui: Ui) -> Text:
    return Text(
        "No arena runs yet. Start one with: busride arena run (the built-in agents play "
        "2,000 deals in a few seconds).",
        style="warn.soft",
    )


def agents_list(
    built_in: Sequence[tuple[str, str]], ai: Sequence[tuple[str, str]], ui: Ui
) -> Group:
    t = _table(ui)
    t.add_column("Name", no_wrap=True, style="heading")
    t.add_column("Plays")
    for name, plays in built_in:
        t.add_row(name, plays)
    a = _table(ui)
    a.add_column("Name", no_wrap=True, style="heading")
    a.add_column("Plays")
    for name, plays in ai:
        a.add_row(name, plays)
    return Group(
        heading(title("arena agents", ui), ui),
        Text("Built in: free, and 2,000 deals take a second or two.", style="muted"),
        t,
        GAP,
        Text(
            "AI models: each decision is a call to the model. busride shows the cost and asks "
            "before it spends anything.",
            style="muted",
        ),
        a,
        GAP,
        _indent(
            Text(
                "Pick them with --agents, separated by commas: "
                "busride arena run --agents optimal,greedy,claude --deals 20",
                style="muted",
            )
        ),
    )


def _seen(cards: list[str], ui: Ui) -> Text:
    if not cards:
        return Text(ui.g.dash, style="muted")
    return cards_inline([parse_card(c) for c in cards], ui)


def _outcome(d: dict[str, Any], ui: Ui) -> Text:
    if d.get("card") is None:
        return Text(ui.g.dash, style="muted")
    out = cards_inline([parse_card(d["card"])], ui)
    mark = {"win": (ui.g.check, "good"), "lose": (ui.g.cross, "bad"), "push": ("=", "warn")}
    glyph, style = mark.get(d["result"], ("", "muted"))
    out.append(f" {glyph}", style=style)
    return out


def _decision_table(decisions: Sequence[dict[str, Any]], ui: Ui, deal_column: bool) -> Table:
    t = _table(ui)
    if deal_column:
        t.add_column("Deal", justify="right", no_wrap=True, style="muted")
    t.add_column("Stage", justify="right", no_wrap=True)
    t.add_column("Cards seen", no_wrap=True)
    t.add_column("Move", no_wrap=True)
    t.add_column("Win chance", justify="right", no_wrap=True)
    t.add_column("Best move", no_wrap=True)
    t.add_column("Gave up", justify="right", no_wrap=True)
    t.add_column("Next card", no_wrap=True)
    for d in decisions:
        exact = d.get("exact")
        chance = Text(fmt.pct(exact, 0)) if exact is not None else Text(ui.g.dash, style="muted")
        if d.get("regret") is None:
            best, gave = Text("not solved", style="muted"), Text(ui.g.dash, style="muted")
        else:
            best = Text(_move(d["best"]))
            gave = Text(fmt.hundred(d["regret"]), style=_given_up_style(d["regret"], d["value"]))
        row: list[RenderableType] = [
            str(d["stage"]),
            _seen(d["seen"], ui),
            Text(_move(d["move"]), style="heading"),
            chance,
            best,
            gave,
            _outcome(d, ui),
        ]
        t.add_row(*([str(d["deal"])] if deal_column else []), *row)
    return t


def _said(d: dict[str, Any]) -> str:
    """What the agent said beyond its move: a win chance unlike the exact one, its reason, and
    any answer that was rejected."""
    parts = []
    stated, exact = d.get("stated"), d.get("exact")
    if stated is not None and (exact is None or abs(stated - exact) >= 0.005):
        parts.append(f"said its chance was {fmt.pct(stated, 0)}")
    if d.get("reason"):
        parts.append(str(d["reason"]))
    for problem in d.get("problems", []):
        parts.append(f"rejected: {problem}")
    return "; ".join(parts)


def replay(
    name: str,
    number: int,
    deals: int,
    cards: list[str],
    plays: Sequence[tuple[str, Sequence[dict[str, Any]], dict[str, Any]]],
    rules: GameSpec,
    ui: Ui,
) -> Group:
    """One deal, each agent's moves beside the exact answer. plays: (agent, decisions, deal)."""
    rows: list[RenderableType] = [
        heading(
            title("arena replay", ui), ui, f"{name} {ui.g.dot} deal {number} of {fmt.count(deals)}"
        ),
        Text.assemble(("The cards in this deal: ", "muted"), _seen(cards, ui)),
        Text(
            "Every agent got the same cards; one that stopped early never saw the rest.",
            style="muted",
        ),
    ]
    for agent, decisions, deal in plays:
        how = _ENDS.get(deal["end"], deal["end"]).format(
            next=deal["survived"] + 1, survived=deal["survived"]
        )
        rows += [
            GAP,
            Text.assemble(
                (agent, "heading"),
                (f" {ui.g.dot} {how} {ui.g.dot} got back ", "muted"),
                (fmt.hundred(deal["payout"]), "heading"),
                (" per 100 bet", "muted"),
            ),
            _decision_table(decisions, ui, deal_column=False),
        ]
        notes = [f"stage {d['stage']}: {_said(d)}" for d in decisions if _said(d)]
        rows += [_indent(Text(n, style="muted")) for n in notes]
    rows += [
        GAP,
        _indent(
            Text(
                "Win chance is exact, from the cards left. Gave up is per 100 bet: the best "
                "move's value minus the value of the move made (0 = the best move).",
                style="muted",
            )
        ),
    ]
    if number < deals:
        rows.append(
            Text(f"Next deal: busride arena replay {name} --deal {number + 1}", style="accent")
        )
    return Group(*rows)


def mistakes(
    name: str, agent: str, decisions: Sequence[dict[str, Any]], total: int, ui: Ui
) -> Group:
    rows: list[RenderableType] = [heading(title("arena replay", ui), ui, name)]
    if not decisions:
        rows.append(Text(f"{agent} made the best move every time: nothing to show.", style="good"))
        return Group(*rows)
    rows += [
        Text(
            f"{agent}'s {len(decisions)} costliest decisions, of {fmt.count(total)}.",
            style="muted",
        ),
        GAP,
        _decision_table(decisions, ui, deal_column=True),
        GAP,
        _indent(
            Text(
                f"See one in full: busride arena replay {name} --deal {decisions[0]['deal']}",
                style="muted",
            )
        ),
    ]
    return Group(*rows)


def human_table(obs: Observation, ui: Ui) -> Group:
    """The table when you play in the arena: your cards, the question, what stopping pays."""
    rows: list[RenderableType] = [
        Text(
            f"Stage {obs.stage} of {obs.stages} {ui.g.dot} {obs.question.lower()}",
            style="heading",
        ),
    ]
    if obs.seen:
        rows += [GAP, card_row(obs.seen, ui)]
    rows.append(GAP)
    if obs.can_cash_out and obs.stage > 1:
        rows.append(
            Text.assemble(
                ("Cashing out now pays ", "muted"),
                (fmt.mult(obs.cash_value), "heading"),
                (" your bet.", "muted"),
            )
        )
    elif obs.can_cash_out:
        rows.append(Text("You can still walk away and keep your bet.", style="muted"))
    else:
        rows.append(Text("Your bet is in: make your first guess.", style="muted"))
    panel = Panel(
        Group(*rows),
        title=title("arena", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 57),
    )
    choices = Text(" ")
    for i, guess in enumerate(obs.options, start=1):
        choices.append(f"[{i}]", style="accent")
        choices.append(f" {guess}   ")
    if obs.can_cash_out:
        choices.append("[$]", style="accent")
        choices.append(" cash out   " if obs.stage > 1 else " walk away   ")
    choices.append("[q]", style="accent")
    choices.append(" stop", style="muted")
    return Group(panel, choices)


def human_result(number: int, deal: dict[str, Any], best: int, decisions: int, ui: Ui) -> Text:
    how = _ENDS.get(deal["end"], deal["end"]).format(
        next=deal["survived"] + 1, survived=deal["survived"]
    )
    out = Text.assemble(
        (f"Deal {number}: you {how}, got back ", "muted"),
        (fmt.mult(deal["payout"]), "heading"),
        (f" {ui.g.dot} best move {best} of {decisions} times", "muted"),
    )
    return out


@dataclass(frozen=True)
class CostRow:
    agent: str
    deals: int  # deals it still has to play
    estimate: float | None  # dollars for those deals; None when its price is unknown
    per_deal: float | None = None  # measured so far, when it has played


def cost_estimate(
    rows: Sequence[CostRow], prices: str, max_cost: float | None, measured: bool, ui: Ui
) -> Group:
    t = _table(ui)
    t.add_column("Agent", overflow="fold", style="heading")
    t.add_column("Deals to play", justify="right", no_wrap=True)
    t.add_column("Cost", justify="right", no_wrap=True)
    t.add_column("Based on", no_wrap=True, style="muted")
    for r in rows:
        if r.estimate is None:
            cost, basis = Text("unknown", style="warn.soft"), "its price isn't in the table"
        elif r.estimate == 0 and r.per_deal is None:
            cost, basis = Text("free"), "it runs on your computer"
        else:
            cost = Text(f"about {fmt.dollars(r.estimate)}")
            basis = (
                f"{fmt.dollars(r.per_deal)} per deal so far"
                if r.per_deal is not None
                else "a rough guess (no calls yet)"
            )
        t.add_row(r.agent, fmt.count(r.deals), cost, basis)
    head = (
        "Measured on the first deal:"
        if measured
        else "This run calls AI models that charge for every decision. Before it starts:"
    )
    out: list[RenderableType] = [Text(head, style="heading"), t]
    if prices:
        out.append(Text(prices, style="muted"))
    if max_cost is not None:
        out.append(
            Text(
                f"It stops once the calls cost {fmt.dollars(max_cost)} (--max-cost).", style="muted"
            )
        )
    return Group(*out)


def prices_table(
    rows: Sequence[tuple[str, float, float, float | None]], source: str, as_of: str, ui: Ui
) -> Group:
    t = _table(ui)
    t.add_column("Model", no_wrap=True, style="heading")
    t.add_column("Input", justify="right", no_wrap=True)
    t.add_column("Output", justify="right", no_wrap=True)
    t.add_column("Cache read", justify="right", no_wrap=True)
    for model, inp, out, read in rows:
        t.add_row(
            model,
            f"${inp:,.2f}",
            f"${out:,.2f}",
            f"${read:,.2f}" if read is not None else Text("0.1x input", style="muted"),
        )
    return Group(
        heading(title("arena prices", ui), ui, f"US dollars per million tokens {ui.g.dot} {as_of}"),
        t,
        GAP,
        Text(f"From: {source}", style="muted", overflow="fold"),
        _indent(
            Text(
                "Local models (ollama:, lmstudio:) are free. A model missing here has an "
                "unknown cost: add it to the file to get estimates.",
                style="muted",
            )
        ),
    )
