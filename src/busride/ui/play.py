"""Screens for `busride play`: the table, what happened after each move, and the session."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from busride.coach.explain import Review, move_name
from busride.engine.solver import Decision
from busride.play import Round, Step, Summary
from busride.ui import fmt
from busride.ui.banner import title, verdict
from busride.ui.bars import bar
from busride.ui.cards import card_row, card_text
from busride.ui.theme import Ui

WIDTH = 57  # the same width as the advisor


def _odds(decision: Decision, ui: Ui) -> Table:
    """One neutral bar per guess, in the game's own order: odds, not advice."""
    by_guess = {o.guess: o for o in decision.options}
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=11, no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    width = 22
    for guess in decision.stage.guesses:
        o = by_guess[guess]
        grid.add_row(
            Text(guess.upper(), style="heading"),
            bar(o.win_chance, width, "accent", ui),
            fmt.pct(o.win_chance),
            fmt.frac(o.wins, o.total),
        )
    best = decision.best
    if best.ties:
        tie = {"lose": "loses", "push": "pushes", "win": "wins"}[best.tie_result.value]
        grid.add_row(
            Text(f"TIE ({tie})", style="muted"),
            bar(best.ties / best.total, width, "muted", ui),
            fmt.pct(best.ties / best.total),
            fmt.frac(best.ties, best.total),
        )
    return grid


def table(rnd: Round, decision: Decision | None, hints: bool, ui: Ui) -> Group:
    """The table before a guess: cards so far, odds if the coach shows them, the pot."""
    rules = rnd.rules
    k = len(rnd.seen)
    stage = rules.stages[k]
    number = rules.guesses_before(k) + 1
    rows: list[RenderableType] = [
        Text(
            f"Round {rnd.number} {ui.g.dot} stage {number} of {rules.guess_count} {ui.g.dot} "
            f"{stage.question.lower()}",
            style="heading",
        ),
        Text(""),
    ]
    if rnd.seen:
        rows += [card_row(rnd.seen, ui), Text("")]
    if hints and decision is not None:
        rows += [_odds(decision, ui), Text("")]
    if rnd.survived:
        rows.append(
            Text.assemble(
                ("In the pot: ", "muted"),
                (fmt.money(rnd.pot), "heading"),
                (" if you cash out now", "muted"),
            )
        )
    elif rnd.can_stop:
        rows.append(Text("You can still walk away and keep your stake.", style="muted"))
    else:
        rows.append(Text("Your stake is in: make your first guess.", style="muted"))
    panel = Panel(
        Group(*rows),
        title=title("play", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, WIDTH),
    )
    return Group(panel, choices(rnd, ui))


def choices(rnd: Round, ui: Ui) -> Text:
    stage = rnd.next_stage
    out = Text(" ")
    if stage is None:
        return out
    for i, guess in enumerate(stage.guesses, start=1):
        out.append(f"[{i}]", style="accent")
        out.append(f" {guess}   ")
    if rnd.can_stop:
        out.append("[$]", style="accent")
        if rnd.survived:
            out.append(f" cash out {fmt.money(rnd.pot)}   ")
        else:
            out.append(" walk away   ")
    out.append("[q]", style="accent")
    out.append(" quit", style="muted")
    return out


def shown(step: Step, ui: Ui) -> Text:
    assert step.card is not None
    return Text.assemble(("  Card shown: ", "muted"), card_text(step.card, ui))


def after(step: Step, rnd: Round, ui: Ui) -> Text:
    """What the move did: the card, and win, loss, push or cash."""
    out = Text("  ")
    if step.result == "cash":
        out.append(f"{ui.g.check} Cashed out: ", style="good")
        out.append(f"+{fmt.money(step.payout or 0.0)} chips", style="good")
        return out
    if step.result == "walk":
        out.append("Walked away: your stake comes back.", style="muted")
        return out
    assert step.card is not None and step.graded is not None
    out.append_text(card_text(step.card, ui))
    guess = step.graded.action
    if step.result == "win":
        out.append(f"   {ui.g.check} {guess} wins", style="good")
        if rnd.over == "full":
            out.append(f": you rode the bus! +{fmt.money(rnd.payout)} chips", style="good")
    elif step.result == "push":
        out.append(f"   = a tie pushes: +{fmt.money(rnd.payout)} chips back", style="warn")
    else:
        out.append(f"   {ui.g.cross} {guess} loses: the stake is gone", style="bad")
    return out


def coach_line(rev: Review, ui: Ui) -> Text:
    return Text.assemble(("  Coach: ", "muted"), (rev.text, f"{rev.kind}.soft"))


def why_line(text: str) -> Text:
    return Text.assemble(("  Why: ", "muted"), (text, "muted"))


def round_line(rnd: Round, chips: float, stake: float, ui: Ui) -> Text:
    how = {
        "lost": f"lost at stage {rnd.survived + 1}",
        "cash": f"cashed out after stage {rnd.survived}",
        "walk": "walked away",
        "push": f"pushed at stage {rnd.survived + 1}",
        "full": "rode the bus",
    }.get(rnd.over or "", "unfinished")
    net = rnd.payout - stake
    style = "good.soft" if net > 0 else "bad.soft" if net < 0 else "muted"
    return Text.assemble(
        (f"Round {rnd.number} {ui.g.dot} {how} {ui.g.dot} ", "muted"),
        (f"{fmt.signed_money(net)}", style),
        (f" {ui.g.dot} chips {fmt.money(chips)}", "muted"),
    )


def summary(s: Summary, stake: float, rules_footer: Text, ui: Ui) -> Group:
    if s.net > 0:
        kind, headline = "good", f"SESSION: UP {fmt.money(s.net)} CHIPS"
    elif s.net < 0:
        kind, headline = "bad", f"SESSION: DOWN {fmt.money(-s.net)} CHIPS"
    else:
        kind, headline = "warn", "SESSION: EVEN"
    rounds = f"{fmt.count(s.rounds)} rounds" if s.rounds != 1 else "1 round"
    if s.decisions:
        rate = s.best_moves / s.decisions
        detail = (
            f"{rounds}. You made the best move {s.best_moves} of {s.decisions} times "
            f"({fmt.pct(rate, 0)})"
        )
        if s.close_moves:
            were = "was" if s.close_moves == 1 else "were"
            detail += f", and {s.close_moves} more {were} within 2%."
        else:
            detail += "."
    else:
        detail = f"{rounds}."
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()
    grid.add_row(
        "Chips",
        f"{fmt.money(s.start_chips)} {ui.g.arrow} {fmt.money(s.chips)} ({fmt.signed_money(s.net)})",
    )
    grid.add_row("Given up", f"{fmt.money(s.given_up)} chips against perfect play, on average")
    luck = "added" if s.luck >= 0 else "took"
    grid.add_row(
        "Your play",
        f"worth {fmt.signed_money(s.expected_net)} chips on average; luck {luck} "
        f"{fmt.money(abs(s.luck))}",
    )
    if s.biggest is not None:
        b = s.biggest
        walk = b.stage == 1 and not b.forced
        grid.add_row(
            "Biggest slip",
            f"round {b.round}, stage {b.stage}: {move_name(b.action, walk)} instead of "
            f"{move_name(b.best, walk)}, {fmt.money(b.regret * stake)} chips",
        )
    return Group(verdict(kind, headline, detail, ui), grid, Text(""), rules_footer)


def out_of_chips(ui: Ui) -> Text:
    return Text("Out of chips for another stake: the session is over.", style="warn")


def welcome(chips: float, stake: float, coach: str, ui: Ui) -> Panel:
    body = Text.assemble(
        ("You have ", "muted"),
        (f"{fmt.money(chips)} chips", "heading"),
        (" and each round costs ", "muted"),
        (f"{fmt.money(stake)}", "heading"),
        (". The coach is set to ", "muted"),
        (coach, "heading"),
        (".\nType the number of your choice, $ to cash out, q to stop.", "muted"),
    )
    return Panel(body, box=ui.g.panel, padding=(0, 2), width=min(ui.width, 72))


def deal_prompt(number: int, ui: Ui) -> str:
    return f"Round {number}: press Enter to deal (q to stop) "
