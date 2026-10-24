"""Whole screens. Each one is assembled from the shared parts: framed cards, block bars,
one verdict banner and the rules footer."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from busride.engine.cards import RANK_LABELS, Card, parse_card
from busride.engine.game import RIDE_THE_BUS
from busride.engine.policy import SheetCell, SheetStage, grade
from busride.engine.rules import BUILT_IN_VERSION, Rules
from busride.engine.solver import Analysis, Decision, FixedPlan
from busride.engine.stages import Result
from busride.sim import SimResult
from busride.stats.report import PayoutCheck, VerifyReport
from busride.stats.tests import TestResult
from busride.ui import fmt
from busride.ui.banner import footer, heading, title, verdict, warnings
from busride.ui.bars import bar, sparkline
from busride.ui.cards import card_row, cards_inline
from busride.ui.theme import Ui

GAP = Text("")
LETTER = {"higher": "H", "lower": "L", "inside": "I", "outside": "O"}
TIE_WORD = {Result.LOSE: "loses", Result.PUSH: "pushes", Result.WIN: "wins"}
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


def _count_word(n: int) -> str:
    return NUMBER_WORDS.get(n, str(n))


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _advisor_width(ui: Ui) -> int:
    """The advisor panel is 57 columns, as in the spec, or the terminal if narrower."""
    return min(ui.width, 57)


def per_hundred(rtp: float) -> str:
    """The RTP in plain words: 'Even playing perfectly, you get back about 96 of every 100...'"""
    lead = "Even playing perfectly" if rtp < 1 else "Playing perfectly"
    return f"{lead}, you get back about {fmt.count(rtp * 100)} of every 100 you bet."


def _rtp_banner(rtp: float, ui: Ui, detail: str | Text) -> Panel:
    if rtp > 1.02:
        return verdict("good", f"PLAYER EDGE {fmt.signed_pct(rtp - 1)}", detail, ui)
    if rtp >= 0.98:
        return verdict("warn", f"NEAR BREAK-EVEN {fmt.signed_pct(rtp - 1)}", detail, ui)
    return verdict("bad", f"HOUSE EDGE {fmt.pct(1 - rtp)}", detail, ui)


def _table(ui: Ui, title: str | None = None) -> Table:
    """The one table style: header rule only, columns two spaces apart."""
    return Table(
        box=ui.g.table,
        pad_edge=False,
        show_edge=False,
        header_style="muted",
        collapse_padding=True,
        padding=(0, 1),
        title=title,
        title_justify="left",
        title_style="heading",
    )


def _edge_style(edge: float | None) -> str:
    """An edge is the house's: positive is bad for you."""
    if edge is None:
        return "muted"
    if edge > 0.02:
        return "bad.soft"
    if edge >= -0.02:
        return "warn.soft"
    return "good.soft"


def _ladder_missing(ui: Ui) -> Text:
    return Text(
        "! The payout ladder is empty, so every return reads 0.00. Run `busride init` "
        "(or pass --ladder) with the returns of the game you play.",
        style="warn.soft",
    )


# ── advisor ──────────────────────────────────────────────────────────────────────────────


def _stage_line(rules: Rules, k: int, ui: Ui) -> Text:
    """'Stage 3 of 4 · inside or outside', counting guessing stages only."""
    stage = rules.stages[k]
    number = rules.guesses_before(k) + 1
    return Text(
        f"Stage {number} of {rules.guess_count} {ui.g.dot} {stage.question.lower()}",
        style="heading",
    )


def advisor(decision: Decision, rules: Rules, ui: Ui, elapsed: float | None = None) -> Group:
    st = decision.stage
    k = len(decision.seen)
    rows: list[RenderableType] = [_stage_line(rules, k, ui), GAP]
    if decision.seen:
        rows.append(card_row(decision.seen, ui))
    elif st.kind == "colour":
        rows.append(Text(" No cards yet: bet on the first card's colour.", style="muted"))
    else:
        rows.append(Text(" No cards yet.", style="muted"))
    rows.append(GAP)

    best = decision.best
    cash = decision.cash_out
    # (label, share, count, style) per row: each guess, then the tie row if ties can happen
    lines = []
    for opt in decision.options:
        # the best guess is judged against cashing out, the others against the best play
        alt = cash if opt is best else max(best.ev, cash)
        style = grade(opt.ev, alt) + ("" if opt is best else ".soft")
        lines.append((opt.guess.upper(), opt.win_chance, fmt.frac(opt.wins, opt.total), style))
    if best.ties:
        lines.append(
            (
                f"TIE ({TIE_WORD[best.tie_result]})",
                best.ties / best.total,
                fmt.frac(best.ties, best.total),
                "muted",
            )
        )
    label_w = max(11, *(len(ln[0]) for ln in lines))
    pct_w = max(len(fmt.pct(ln[1])) for ln in lines)
    frac_w = max(len(ln[2]) for ln in lines)
    bar_w = max(8, _advisor_width(ui) - 6 - label_w - pct_w - frac_w - 6)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(min_width=label_w, no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)
    for label, share, counts, style in lines:
        grid.add_row(Text(label, style=style), bar(share, bar_w, style, ui), fmt.pct(share), counts)
    rows += [grid, GAP]

    go = decision.should_continue
    chosen, other = (decision.continue_value, cash) if go else (cash, decision.continue_value)
    style = grade(chosen, other)
    first_guess = rules.guesses_before(k) == 0
    must_play = first_guess and rules.forced_first_bet and k > 0
    guess_note = "" if go or must_play else "  (if you play on)"
    rows.append(
        Text.assemble(
            ("Best guess   ", "muted"), (best.guess.upper(), "heading"), (guess_note, "muted")
        )
    )
    if must_play:
        # the stake went down before the cards were shown: this guess can't be refused
        rows.append(
            Text.assemble(
                ("Your stake is in: make this guess. It is worth ", "muted"),
                (fmt.ret(decision.continue_value), grade(decision.continue_value, 1.0)),
                (" per 1 staked.", "muted"),
            )
        )
    else:
        if first_guess and rules.forced_first_bet:
            stop_word, go_word = "Skip", "play"
            action = "PLAY" if go else "SKIP THIS ROUND"
        elif first_guess:
            stop_word, go_word = "Walk away", "bet"
            action = "BET" if go else "WALK AWAY"
        else:
            stop_word, go_word = "Cash out", "continue"
            action = "CONTINUE" if go else "CASH OUT"
        rows.append(
            Text.assemble(
                (f"{stop_word} ", "muted"),
                (fmt.ret(cash), style if not go else "muted"),
                ("  vs  ", "muted"),
                (f"{go_word} ", "muted"),
                (fmt.ret(decision.continue_value), style if go else "muted"),
                (f"   {ui.g.arrow}   ", "muted"),
                (action, style),
            )
        )
    if not rules.ladder_captured:
        rows += [GAP, _ladder_missing(ui)]

    panel = Panel(
        Group(*rows),
        title=title("advisor", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=_advisor_width(ui),
    )
    extra = f"answered in {fmt.duration(elapsed)}" if elapsed is not None else ""
    return Group(panel, footer(rules, ui, extra))


def round_over(seen: Sequence[Card], rules: Rules, ui: Ui) -> Group:
    body = Group(
        Text(f"Round over: all {_count_word(rules.guess_count)} stages survived.", style="good"),
        GAP,
        card_row(seen, ui),
        GAP,
        Text.assemble(
            ("Paid ", "muted"), (fmt.mult(rules.returns[-1]), "good"), (" per 1 staked", "muted")
        ),
    )
    return Group(_advisor_panel(body, ui), footer(rules, ui))


def reveal_wait(seen: Sequence[Card], rules: Rules, ui: Ui) -> Group:
    """The next card is only shown: nothing to decide yet."""
    k = len(seen)
    rows: list[RenderableType] = [
        Text(f"Card {k + 1} is shown with no guess", style="heading"),
        GAP,
    ]
    if seen:
        rows += [card_row(seen, ui), GAP]
    rows.append(
        Text("Type it when it appears, and the advice for the next guess follows.", style="muted")
    )
    return Group(_advisor_panel(Group(*rows), ui), footer(rules, ui))


def _advisor_panel(body: RenderableType, ui: Ui) -> Panel:
    return Panel(
        body,
        title=title("advisor", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=_advisor_width(ui),
    )


# ── analyze ──────────────────────────────────────────────────────────────────────────────


def analysis(
    a: Analysis,
    ui: Ui,
    payouts: PayoutCheck | None = None,
    notes: Sequence[str] = (),
    timing: bool = True,
) -> Group:
    rules = a.rules
    worst = a.stages[a.worst_step - 1] if a.worst_step else None
    if a.rtp is None:
        be = " / ".join(fmt.mult(s.break_even) for s in a.stages)
        banner = verdict(
            "warn",
            "PAYOUT LADDER NOT CAPTURED",
            "The odds below are exact for your deck and tie rules. With the fair shape, perfect "
            f"play breaks even at {be}. Set the returns of the game you play with "
            "`busride init`.",
            ui,
        )
    else:
        detail = per_hundred(a.rtp)
        if worst is not None and worst.step_edge is not None:
            detail += (
                f" Stage {a.worst_step} ({worst.stage.question.lower()}) takes the most: "
                f"each 1 you let ride through it comes back as {fmt.ret(1 - worst.step_edge)}."
            )
        banner = _rtp_banner(a.rtp, ui, detail)

    t = _table(ui)
    t.add_column("Stage", no_wrap=True)
    for name in ("Win", "Survive", "Fair", "Offered", "Break\neven", "Step\nedge", "Plan\nedge"):
        t.add_column(name, justify="right", no_wrap=True)
    for i, s in enumerate(a.stages, start=1):
        hot = worst is not None and s is worst
        t.add_row(
            Text(f"{i} {s.stage.question}", style="heading" if hot else ""),
            fmt.pct(s.win_chance),
            fmt.pct(s.survive),
            fmt.mult(s.fair),
            Text(fmt.mult(s.offered), style=_edge_style(s.plan_edge))
            if rules.ladder_captured
            else Text(ui.g.dash, style="muted"),
            fmt.mult(s.break_even) if s.break_even else ui.g.dash,
            Text(fmt.signed_pct(s.step_edge), style=_edge_style(s.step_edge))
            if s.step_edge is not None
            else Text(ui.g.dash, style="muted"),
            Text(fmt.signed_pct(s.plan_edge), style=_edge_style(s.plan_edge))
            if s.plan_edge is not None
            else Text(ui.g.dash, style="muted"),
        )

    explain = Text(
        "Win: chance at that stage, given you got there. Fair = 1/survive, the break-even for "
        "always playing to that stage. Break even: your ladder scaled so perfect play returns "
        "exactly 1. Step edge: what letting the pot ride through that stage costs. Plan edge: "
        "always playing to that stage, then cashing out.",
        style="muted",
    )

    rows: list[RenderableType] = [
        heading(title("analysis", ui), ui, rules.name),
        banner,
        t,
        explain,
        GAP,
    ]

    alt_label = "cards could repeat" if a.alt_model == "with_replacement" else "the deck were fresh"
    line = Text(f"If {alt_label}: ", style="muted")
    if a.alt_rtp is not None:
        line.append(f"perfect play would return {fmt.ret(a.alt_rtp)}, and ")
    line.append(
        f"surviving all {_count_word(len(a.stages))} would happen "
        f"{fmt.pct(a.alt_survive_all, 2)} of the time "
        f"(your rules: {fmt.pct(a.stages[-1].survive, 2)})."
    )
    if rules.stages == RIDE_THE_BUS:
        line.append(" `busride verify` tests which one the game uses.")
    rows.append(line)
    rows.append(_payout_lines(payouts, rules, ui))
    if notes:
        rows += [GAP, warnings(list(notes), ui)]
    extra = f"solved exactly: {a.states} states in {fmt.duration(a.seconds)}" if timing else ""
    rows += [GAP, footer(rules, ui, extra)]
    return Group(*rows)


def _payout_lines(payouts: PayoutCheck | None, rules: Rules, ui: Ui) -> Text:
    if payouts is None or payouts.paid_rounds == 0:
        return Text(
            "No logged payouts to check against the ladder yet (`busride log` records them).",
            style="muted",
        )
    paid = fmt.count(payouts.paid_rounds)
    if not rules.ladder_captured:
        return Text(
            f"{paid} logged payouts are waiting to be checked: the ladder in rules.toml is empty.",
            style="muted",
        )
    if not payouts.mismatches:
        return Text.assemble(
            (f"{ui.g.check} ", "good"),
            (f"Logged payouts match the ladder in rules.toml ({paid} paid rounds).", "muted"),
        )
    out = Text()
    for i, g in enumerate(payouts.mismatches):
        if i:
            out.append("\n")
        out.append(f"{ui.g.cross} ", style="bad")
        out.append(
            f"{fmt.count(g.rounds)} paid round(s) with {g.cards} card(s) paid "
            f"{fmt.mult(g.multiple)}; rules.toml says {fmt.mult(g.expected)} and no stage matches.",
            style="bad.soft",
        )
    return out


# ── policy ───────────────────────────────────────────────────────────────────────────────

_RELATIVE = {
    "fewer": "the colour seen less",
    "more": "the colour seen more",
    "either": "either colour",
    "least": "a suit seen least",
    "other": "another suit",
}


def _sheet_letter(cell: SheetCell | None, ui: Ui) -> Text:
    if cell is None:
        return Text(ui.g.dot, style="muted")
    letter = LETTER.get(cell.guess, cell.guess[:1].upper()) if cell.should_continue else "$"
    if not cell.unanimous:
        letter += "*"
    return Text(letter, style=cell.grade)


def _cash_note(sheet: SheetStage) -> str:
    if sheet.cash_value is None:
        return "" if sheet.layout == "first" else "your stake is in: no cash-out yet"
    if sheet.index == 1:
        return "or walk away and keep your stake"
    return f"cash out pays {fmt.mult(sheet.cash_value)}"


def _sheet_first(sheet: SheetStage, rtp: float) -> Text:
    cell = sheet.cells[()]
    what = "Either colour" if sheet.stage.kind == "colour" else "Any suit"
    text = f"{what}, {fmt.pct(cell.survive)}."
    if sheet.cash_value is None:
        text += (
            " There is no cash-out before it, so the only choice is whether to play: "
            f"perfect play returns {fmt.ret(rtp)} per 1."
        )
    else:
        choice = "play" if cell.should_continue else "walk away"
        text += (
            f" Betting is worth {fmt.ret(cell.continue_value)} against 1.00 for keeping your "
            f"stake: {choice}."
        )
    return Text(text, style="muted")


def _sheet_strip(sheet: SheetStage, rules: Rules, ui: Ui) -> Table:
    ref = sheet.stage.refs[0]
    if ref == 0:
        label = "first card"
    elif ref == sheet.stage.number - 2:
        label = "previous card"
    else:
        label = f"card {ref + 1}"
    width = max(12, len(label) + 2)
    strip = Table.grid(padding=0)
    strip.add_column(width=width, no_wrap=True)
    for _ in rules.ranks:
        strip.add_column(width=5, justify="right", no_wrap=True)
    cells = [sheet.cells.get(r) for r in rules.ranks]
    strip.add_row(
        Text(f"  {label}", style="muted"),
        *[Text(RANK_LABELS[r], style="heading") for r in rules.ranks],
    )
    strip.add_row(Text("  play", style="muted"), *[_sheet_letter(c, ui) for c in cells])
    strip.add_row(
        Text("  survive", style="muted"),
        *[fmt.pct(c.survive, 0) if c else ui.g.dot for c in cells],
    )
    strip.add_row(
        Text("  continue", style="muted"),
        *[fmt.ret(c.continue_value) if c else ui.g.dot for c in cells],
    )
    return strip


def _sheet_grid(sheet: SheetStage, rules: Rules, ui: Ui) -> Table:
    a, b = sheet.stage.refs
    grid = Table.grid(padding=0)
    grid.add_column(width=10, no_wrap=True)
    for _ in rules.ranks:
        grid.add_column(width=4, justify="right", no_wrap=True)
    grid.add_row(
        Text(f"  {_ordinal(a + 1)}\\{_ordinal(b + 1)}", style="muted"),
        *[Text(RANK_LABELS[r], style="heading") for r in rules.ranks],
    )
    for r1 in rules.ranks:
        grid.add_row(
            Text(f"  {RANK_LABELS[r1]:>3}", style="heading"),
            *[_sheet_letter(sheet.cells.get((r1, r2)), ui) for r2 in rules.ranks],
        )
    return grid


def _sheet_patterns(sheet: SheetStage, ui: Ui) -> Table:
    t = _table(ui)
    seen_label = "Colours seen" if sheet.stage.kind == "colour" else "Suits seen"
    t.add_column(seen_label, no_wrap=True)
    t.add_column("Best guess", no_wrap=True)
    t.add_column("Wins", justify="right", no_wrap=True)
    t.add_column("Continue", justify="right", no_wrap=True)
    t.add_column("Cash out", justify="right", no_wrap=True)
    t.add_column("Play", no_wrap=True)
    for feature in sorted(sheet.cells, reverse=True):
        cell = sheet.cells[feature]
        guess = cell.guess  # shown even when cashing out: the guess if you went on anyway
        cash = ui.g.dash if cell.cash_value is None else fmt.ret(cell.cash_value)
        play = "CONTINUE" if cell.should_continue else "CASH OUT"
        if cell.cash_value is None:
            play = "PLAY"
        counts = tuple(feature)
        label = (
            f"{counts[0]} and {counts[1]}"
            if sheet.stage.kind == "colour"
            else f" {ui.g.dot} ".join(map(str, counts))
        )
        t.add_row(
            label,
            _RELATIVE.get(guess, guess) + ("" if cell.unanimous else "*"),
            fmt.pct(cell.survive),
            fmt.ret(cell.continue_value),
            cash,
            Text(play, style=cell.grade),
        )
    return t


def policy(rules: Rules, rtp: float, sheet: Sequence[SheetStage], ui: Ui) -> Group:
    if rules.ladder_captured:
        banner = _rtp_banner(
            rtp,
            ui,
            f"Play by this sheet and you get back about {fmt.count(rtp * 100)} of every 100 "
            "you bet. No strategy does better.",
        )
    else:
        banner = verdict(
            "warn",
            "PAYOUT LADDER NOT CAPTURED",
            "With every return at 0, the policy cashes out everywhere. "
            "Run `busride init` or pass --ladder.",
            ui,
        )
    rows: list[RenderableType] = [heading(title("policy", ui), ui, rules.name), banner]
    marked = False
    for s in sheet:
        rows.append(
            heading(f"Stage {s.index} {ui.g.dot} {s.stage.question.lower()}", ui, _cash_note(s))
        )
        if s.layout == "first":
            rows.append(_indent(_sheet_first(s, rtp)))
        elif s.layout == "strip":
            rows.append(_sheet_strip(s, rules, ui))
        elif s.layout == "grid":
            rows.append(_sheet_grid(s, rules, ui))
        else:
            rows.append(_indent(_sheet_patterns(s, ui)))
        marked = marked or any(not c.unanimous for c in s.cells.values())
        rows.append(GAP)
    if marked:
        rows += [
            _indent(
                Text(
                    "* the best play also depends on earlier cards; shown: the most likely case",
                    style="muted",
                )
            ),
            GAP,
        ]

    legend = Text.assemble(
        ("H", "heading"),
        (" higher  ", "muted"),
        ("L", "heading"),
        (" lower  ", "muted"),
        ("I", "heading"),
        (" inside  ", "muted"),
        ("O", "heading"),
        (" outside  ", "muted"),
        ("$", "heading"),
        (" cash out  ", "muted"),
        (ui.g.dot, "heading"),
        (" can't happen\n", "muted"),
        ("green", "good"),
        (" going on beats cashing by >2%  ", "muted"),
        ("amber", "warn"),
        (" within 2%  ", "muted"),
        ("red", "bad"),
        (" going on loses", "muted"),
    )
    rows += [_indent(legend), GAP, footer(rules, ui)]
    return Group(*rows)


def _indent(renderable: RenderableType, by: int = 2) -> Padding:
    """Indent a block so wrapped lines keep the indent."""
    return Padding(renderable, (0, 0, 0, by))


# ── sim ──────────────────────────────────────────────────────────────────────────────────


def sim_live(res: SimResult, target: int, ui: Ui) -> Panel:
    done = res.rounds / target if target else 1.0
    lo, hi = res.ci95
    body = Group(
        Text.assemble(
            bar(done, 30, "accent", ui),
            (f"  {fmt.count(res.rounds)} / {fmt.count(target)} rounds", "muted"),
        ),
        Text.assemble(
            ("RTP so far ", "muted"),
            (fmt.ret(res.mean, 4), "heading"),
            (f"  (95% {fmt.ret(lo, 4)} to {fmt.ret(hi, 4)})", "muted"),
        ),
        Text.assemble(("bankroll  ", "muted"), sparkline(res.bankroll, 50, ui)),
    )
    return Panel(
        body,
        title=title("simulating", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 80),
    )


def sim_report(
    res: SimResult,
    rules: Rules,
    ui: Ui,
    strategy: str,
    exact: float | None,
    plan: FixedPlan | None = None,
    seed: int | None = None,
    timing: bool = True,
) -> Group:
    lo, hi = res.ci95
    headline = f"SIMULATED RTP {fmt.ret(res.mean, 4)}  (95% {fmt.ret(lo, 4)} to {fmt.ret(hi, 4)})"
    detail = Text()
    if exact is not None:
        inside = lo <= exact <= hi
        z = (res.mean - exact) / res.se if res.se else 0.0
        detail.append(f"{ui.g.check if inside else ui.g.cross} ", style="good" if inside else "bad")
        where = "inside" if inside else "outside"
        detail.append(
            f"The exact answer {fmt.ret(exact, 4)} is {where} the interval "
            f"({fmt.stat(abs(z))} standard errors away)."
        )
    if res.mean > 1.02:
        kind = "good"
    elif res.mean >= 0.98:
        kind = "warn"
    else:
        kind = "bad"
    rows: list[RenderableType] = [
        heading(title("simulation", ui), ui, f"strategy: {strategy}"),
        verdict(kind, headline, detail, ui),
    ]

    pushes = "push" in (rules.tie_higher_lower, rules.tie_range_edge)
    t = _table(ui)
    t.add_column("Stage", no_wrap=True)
    t.add_column("Lost here", justify="right")
    if pushes:
        t.add_column("Pushed", justify="right")
    t.add_column("Cashed out\nafter it", justify="right")
    t.add_column("Survived\nthrough", justify="right")
    if plan is not None:
        t.add_column("Exact", justify="right")
    n = max(res.rounds, 1)
    last = rules.guess_count
    for k, st in enumerate(rules.guess_stages, start=1):
        p, _ = res.reach_rate(k)
        cells = [f"{k} {st.question}", fmt.pct(res.lost_at[k] / n)]
        if pushes:
            cells.append(fmt.pct(res.pushed_at[k] / n))
        cells += [fmt.pct(res.cashed_after[k] / n) if k < last else ui.g.dash, fmt.pct(p, 2)]
        if plan is not None:
            cells.append(fmt.pct(plan.reach[k - 1], 2) if k <= len(plan.reach) else ui.g.dash)
        t.add_row(*cells)
    rows.append(t)
    if res.declined:
        rows.append(
            Text(
                f"Walked away before betting in {fmt.pct(res.declined / n)} of rounds.",
                style="muted",
            )
        )

    spark_w = max(20, min(ui.width - 24, 60))
    rows.append(
        Text.assemble(
            ("Bankroll  ", "muted"),
            sparkline(res.bankroll, spark_w, ui, "bad.soft" if res.net < 0 else "good.soft"),
        )
    )
    rows.append(
        Text(
            f"          net {fmt.signed_money(res.net)} after {fmt.count(res.rounds)} rounds at "
            f"stake {fmt.money(res.stake)}",
            style="muted",
        )
    )
    if not rules.ladder_captured:
        rows += [GAP, _ladder_missing(ui)]
    extra = []
    if seed is not None:
        extra.append(f"seed {seed}")
    if timing:
        extra.append(f"{fmt.count(res.rounds)} rounds in {fmt.duration(res.seconds)}")
    rows += [GAP, footer(rules, ui, f" {ui.g.dot} ".join(extra))]
    return Group(*rows)


# ── verify ───────────────────────────────────────────────────────────────────────────────


def _test_cells(t: TestResult, ui: Ui) -> tuple[str, str]:
    if t.key in ("ranks", "suits"):
        if t.statistic is None:
            return ui.g.dash, ui.g.dash
        return f"chi2 {fmt.stat(t.statistic)}", f"{int(t.expected or 0)} df"
    if t.key == "colour":
        if not t.n:
            return ui.g.dash, ui.g.dash
        return f"{fmt.pct(t.observed / t.n)} red", "50.0%"
    exp = fmt.stat(t.expected) if t.expected is not None else ui.g.dash
    return fmt.count(t.observed), exp


def verify_report(
    rep: VerifyReport,
    rules: Rules,
    ui: Ui,
    payouts: PayoutCheck | None = None,
    source: str = "rounds.db",
) -> Group:
    rows: list[RenderableType] = [
        heading(title("verify", ui), ui, f"{fmt.count(rep.rounds)} rounds from {source}")
    ]
    if rep.rounds == 0:
        rows.append(
            verdict(
                "warn",
                "NO ROUNDS LOGGED YET",
                "Log rounds as you play with `busride log`, then run this again.",
                ui,
            )
        )
        rows += [GAP, footer(rules, ui)]
        return Group(*rows)

    if rep.flagged:
        names = "; ".join(
            f"{t.name} ({fmt.pval(t.p_adjusted or 0)} after Holm)" for t in rep.flagged
        )
        ran = sum(1 for t in rep.tests if t.p_value is not None)
        banner = verdict("bad", f"{len(rep.flagged)} OF {ran} TESTS FLAGGED", names, ui)
    else:
        ran = sum(1 for t in rep.tests if t.p_value is not None)
        banner = verdict(
            "good" if ran == len(rep.tests) else "warn",
            f"NO EVIDENCE OF BIAS IN {fmt.count(rep.rounds)} ROUNDS",
            f"{ran} of {len(rep.tests)} tests had enough data. "
            "Passing cannot certify the game fair.",
            ui,
        )
    rows.append(banner)

    # the deck-model line (the leading model against its main rival), then the evidence for all
    in_rules = [
        f for f in rep.models if (f.model, f.decks) == (rules.deck_model, rules.effective_decks)
    ]
    lead = rep.best or (in_rules[0] if in_rules else rep.models[0])
    rival_model = "fresh_52" if lead.model == "with_replacement" else "with_replacement"
    rival = next(f for f in rep.models if f.model == rival_model)
    parts = []
    for i, f in enumerate((lead, rival)):
        name = f.label if i == 0 else f.label.lower()
        if f.consistent:
            parts.append(f"{name}: consistent with {fmt.count(rep.rounds)} rounds")
        else:
            parts.append(f"{name}: rejected ({fmt.pval(f.p_value)})")
    rows.append(Text("; ".join(parts) + ".", style="heading"))
    m = _table(ui)
    m.add_column("Deck model", no_wrap=True)
    m.add_column("Rounds with a\nrepeated card", justify="right")
    m.add_column("Expected", justify="right")
    m.add_column("p", justify="right")
    m.add_column("Verdict", no_wrap=True)
    for f in rep.models:
        is_best = rep.best is not None and f == rep.best
        verdict_txt = Text(
            "best fit" if is_best else ("consistent" if f.consistent else "rejected"),
            style="good" if is_best else ("muted" if f.consistent else "bad.soft"),
        )
        m.add_row(
            Text(f.label, style="heading" if is_best else ""),
            fmt.count(f.duplicate_rounds),
            fmt.stat(f.expected_duplicates),
            fmt.pnum(f.p_value),
            verdict_txt,
        )
    rows.append(m)
    if rep.best is not None and (rep.best.model, rep.best.decks) != (
        rules.deck_model,
        rules.effective_decks,
    ):
        rows.append(
            Text(
                f"! rules.toml says {rep.rules_model.lower()}, but the best fit is "
                f"{rep.best.label.lower()}. Consider updating deck.model and re-running "
                "`busride analyze`.",
                style="warn.soft",
            )
        )
    rows.append(GAP)

    t = _table(ui, title=f"Tests against rules.toml ({rep.rules_model.lower()})")
    t.add_column("Test", no_wrap=True)
    t.add_column("Observed", justify="right", no_wrap=True)
    t.add_column("Expected", justify="right", no_wrap=True)
    t.add_column("p (Holm)", justify="right", no_wrap=True)
    t.add_column("Verdict", no_wrap=True)
    for test in rep.tests:
        obs, exp = _test_cells(test, ui)
        if test.p_value is None:
            p_txt, v = ui.g.dash, Text("need data", style="warn.soft")
        else:
            p_txt = fmt.pnum(test.p_adjusted if test.p_adjusted is not None else test.p_value)
            v = Text("FLAG", style="bad") if test.flagged else Text("pass", style="good.soft")
        t.add_row(test.name, obs, exp, p_txt, v)
    rows.append(t)

    for test in rep.tests:
        iv = test.interval
        if iv is None or test.p_value is None:
            continue
        what = {"ranks": "Rank most off", "suits": "Suit most off", "colour": "First card red"}[
            test.key
        ]
        label = ui.g.suits.get(iv.label, iv.label) if test.key == "suits" else iv.label
        prefix = "" if test.key == "colour" else f"{label} at "
        rows.append(
            _indent(
                Text(
                    f"{what}: {prefix}{fmt.pct(iv.observed)} (95% CI {fmt.pct(iv.low)} to "
                    f"{fmt.pct(iv.high)}), expected {fmt.pct(iv.expected)}",
                    style="muted",
                )
            )
        )
    for test in rep.tests:
        if test.p_value is None:
            rows.append(_indent(Text(f"{test.name}: {test.note}.", style="muted")))
    rows.append(GAP)
    rows.append(_payout_lines(payouts, rules, ui))
    rows.append(
        Text(
            "These tests can reject a model but never certify the game fair: a game that changed "
            "its odds with your streak or stake would pass them.",
            style="muted",
        )
    )
    rows += [GAP, footer(rules, ui)]
    return Group(*rows)


# ── init and log ─────────────────────────────────────────────────────────────────────────


def stage_summary(rules: Rules, ui: Ui) -> str:
    """'card shown → higher or lower ×5': the stages in order, repeats folded."""
    runs: list[tuple[str, int]] = []
    for s in rules.stages:
        if runs and runs[-1][0] == s.question:
            runs[-1] = (s.question, runs[-1][1] + 1)
        else:
            runs.append((s.question, 1))
    times = "x" if ui.ascii else "×"
    parts = [q.lower() + (f" {times}{n}" if n > 1 else "") for q, n in runs]
    return f" {ui.g.arrow} ".join(parts)


@dataclass(frozen=True)
class GameRow:
    name: str
    description: str
    rtp: float | None  # None when the game can't be loaded or solved
    current: bool = False
    yours: bool = False


def games_list(games: Sequence[GameRow], ui: Ui) -> Group:
    t = _table(ui)
    t.add_column("", no_wrap=True, style="accent")
    t.add_column("Name", no_wrap=True, style="heading")
    t.add_column("What you do")
    t.add_column("Perfect play\nreturns", justify="right", no_wrap=True)
    built_in = [g for g in games if not g.yours]
    yours = [g for g in games if g.yours]
    for group in (built_in, yours):
        if group is yours and yours:
            t.add_row("", Text("your games", style="muted"), "", "")
        for g in group:
            rtp = fmt.pct(g.rtp) if g.rtp is not None else Text(ui.g.dash, style="muted")
            t.add_row(ui.g.arrow if g.current else "", g.name, g.description, rtp)
    rows: list[RenderableType] = [
        heading(
            f"RIDE THE BUS {ui.g.dot} games", ui, f"{len(built_in)} built in, {len(yours)} yours"
        ),
        t,
        GAP,
        _indent(
            Text(
                f"{ui.g.arrow} marks your current game. Switch with `busride games use NAME`, see "
                "a game's rules with `busride games NAME`, or make your own with "
                "`busride games new`. To try one without switching: "
                "`busride odds --game hi-lo-5`.",
                style="muted",
            )
        ),
    ]
    return Group(*rows)


# ── the home menu, settings and setup check ──────────────────────────────────────────────


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    command: str  # what to type next time: busride <command>


MENU_ITEMS = (
    MenuItem("1", "Tutorial (start here!)", "tutorial"),
    MenuItem("2", "Play a few rounds, with a coach", "play"),
    MenuItem("3", "I'm playing now: what should I do?", "advise"),
    MenuItem("4", "Show the cheat sheet", "cheatsheet"),
    MenuItem("5", "How fair is this game?", "odds"),
    MenuItem("6", "Arena: watch bots play, graded against perfect play", "arena run"),
    MenuItem("7", "Train a learning AI and watch it improve", "train"),
    MenuItem("8", "Choose a game", "games"),
    MenuItem("9", "Settings: payouts, chips, coach, AI model", "settings"),
    MenuItem("10", "Pretend rounds: double-check the maths", "simulate"),
    MenuItem("11", "Record real rounds", "log"),
    MenuItem("12", "Is the dealing fair?", "verify"),
    MenuItem("13", "Check my setup", "doctor"),
)


def home_menu(game_line: str, rtp: float | None, items: Sequence[MenuItem], ui: Ui) -> Group:
    body: list[RenderableType] = [Text(game_line, style="heading")]
    if rtp is not None:
        body.append(Text(per_hundred(rtp), style="muted"))
    body.append(GAP)
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="accent", no_wrap=True)
    grid.add_column()
    for item in items:
        grid.add_row(item.key, item.label)
    grid.add_row("q", Text("Quit", style="muted"))
    body.append(grid)
    panel = Panel(
        Group(*body),
        title=f"busride {ui.g.dot} Ride the Bus, solved",
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 64),
    )
    return Group(panel)


def settings_panel(
    rows: Sequence[tuple[str, str]], folders: Sequence[tuple[str, str]], ui: Ui
) -> Group:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()
    for key, value in rows:
        grid.add_row(key, value)
    panel = Panel(
        grid,
        title=title("settings", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 72),
    )
    out: list[RenderableType] = [panel]
    for label, path in folders:
        out.append(Text(f"{label}: {path}", style="muted", overflow="fold"))
    return Group(*out)


def doctor_report(
    checks: Sequence[tuple[str, str, str]], folders: Sequence[tuple[str, str]], ui: Ui
) -> Group:
    """checks: (level, what, detail); level is 'good', 'warn', 'bad' or 'muted' (just a note)."""
    marks = {"good": ui.g.check, "warn": "!", "bad": ui.g.cross, "muted": ui.g.dot}
    soft = {"good": "good.soft", "warn": "warn.soft", "bad": "bad.soft", "muted": "muted"}
    t = _table(ui)
    t.add_column("", no_wrap=True)
    t.add_column("Check", no_wrap=True)
    t.add_column("Result")
    for level, what, detail in checks:
        t.add_row(Text(marks[level], style=level), what, Text(detail, style=soft[level]))
    worst = (
        "bad"
        if any(c[0] == "bad" for c in checks)
        else ("warn" if any(c[0] == "warn" for c in checks) else "good")
    )
    headline = {
        "good": "EVERYTHING LOOKS GOOD",
        "warn": "WORKS, WITH NOTES",
        "bad": "SOMETHING NEEDS FIXING",
    }[worst]
    out: list[RenderableType] = [
        heading(title("doctor", ui), ui, "checking your setup"),
        verdict(worst, headline, "Each line below says what was checked and what to do.", ui),
        t,
        GAP,
    ]
    for label, path in folders:
        out.append(Text(f"{label}: {path}", style="muted", overflow="fold"))
    return Group(*out)


def rules_panel(rules: Rules, notes: Sequence[str], ui: Ui, written_to: str | None = None) -> Group:
    d = ui.g.dot
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="muted", no_wrap=True)
    grid.add_column()
    model = rules.deck_model + (f" ({rules.decks} decks)" if rules.deck_model == "shoe" else "")
    stakes = (
        f"{fmt.money(rules.min_stake)} to {fmt.money(rules.max_stake)}"
        if rules.min_stake and rules.max_stake
        else "not recorded"
    )
    fields = [("Game", rules.name)]
    if rules.stages != RIDE_THE_BUS:
        fields.append(("Stages", stage_summary(rules, ui)))
    if not rules.forced_first_bet:
        fields.append(("First bet", "optional: you may walk away before it"))
    built_in = rules.game_version == BUILT_IN_VERSION
    if not built_in:
        fields += [("Version", rules.game_version), ("Captured on", rules.captured_on or "?")]
    fields += [
        ("Deck", model),
        ("Ace", rules.ace),
        ("Tie, higher/lower", rules.tie_higher_lower),
        ("Tie, range edge", rules.tie_range_edge),
        ("Ladder", f" {d} ".join(fmt.mult(r) for r in rules.returns)),
    ]
    if not built_in:  # a built-in game has no table limits or timer to record
        fields += [("Stakes", stakes), ("Timeout", rules.timeout)]
    for k, v in fields:
        grid.add_row(k, v)
    panel = Panel(
        grid,
        title=title("rules", ui),
        title_align="left",
        box=ui.g.panel,
        padding=(0, 2),
        width=min(ui.width, 72),
    )
    where = f"Written to {written_to}." if written_to else f"From {rules.source}."
    rows: list[RenderableType] = [panel, Text(where, style="muted")]
    if notes:
        rows.append(warnings(list(notes), ui))
    else:
        rows.append(Text.assemble((f"{ui.g.check} ", "good"), ("No odd values spotted.", "muted")))
    return Group(*rows)


def log_line(
    number: int, cards: Sequence[str], stake: float, paid: float | None, total: int, ui: Ui
) -> Text:
    shown = cards_inline([parse_card(c) for c in cards], ui)
    out = Text(f"  #{number:<4} ", style="muted")
    out.append_text(shown)
    out.append(" " * max(1, 18 - shown.cell_len))
    if paid is None:
        out.append(f"lost at stage {len(cards)}", style="bad.soft")
        plain_len = len(f"lost at stage {len(cards)}")
    else:
        msg = f"paid {fmt.money(paid)} ({fmt.mult(paid / stake)})"
        out.append(msg, style="good.soft")
        plain_len = len(msg)
    out.append(" " * max(2, 28 - plain_len))
    out.append(f"{fmt.count(total)} logged", style="muted")
    return out
