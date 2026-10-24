"""The `busride` command: reads input, calls the engine and prints screens.

Every command has an action, `_do_<name>(ui, ...)`, which the home menu calls too, and a thin
Typer wrapper that builds the UI from the command-line flags. Run with no command, busride opens
the menu (or prints help when it isn't attached to a terminal, so scripts never hang).
"""

import errno
import importlib.metadata
import io
import json
import os
import platform
import random
import re
import sys
import time
import tomllib
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.live import Live
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.text import Text

from busride import __version__, config
from busride.agents.base import Action, AgentUnavailable, Observation
from busride.agents.baselines import AI_AGENTS, BASELINES, agent_names_help, is_ai, make_agent
from busride.agents.oracle import oracle_for
from busride.arena.runner import DEFAULT_DEALS, DEFAULT_SEED, Arena
from busride.arena.runs import RunFile, fingerprint, runs_in
from busride.arena.scoring import score
from busride.coach.explain import review, why
from busride.coach.llm import Rewording
from busride.engine import solver
from busride.engine.builtins import (
    BUILTIN_GAMES,
    load_game,
    resolve_ladder,
    slug,
    your_games,
)
from busride.engine.cards import DECK_MODELS, Card, CardError, parse_card, parse_cards
from busride.engine.game import PLACEHOLDER_VERSION, STAGE_KINDS, GameSpec, Stage, make_stages
from busride.engine.policy import AdviceError, SolverStrategy, cheatsheet
from busride.engine.policy import advise as advise_cards
from busride.engine.rules import (
    ACE_RULES,
    TIE_RULES,
    TIMEOUT_RULES,
    Rules,
    RulesError,
    dump_rules,
    load_rules,
    parse_ladder,
    parse_rules,
    static_warnings,
)
from busride.engine.stages import STAGES, survival_problem
from busride.play import CASH, Session, parse_choice
from busride.sim import Greedy, SimResult, Strategy, simulate
from busride.stats.report import PayoutCheck, check_payouts
from busride.stats.report import verify as verify_rounds
from busride.store import Store
from busride.ui import arena as arena_ui
from busride.ui import fmt, screens
from busride.ui import play as play_ui
from busride.ui.banner import footer, heading
from busride.ui.theme import Ui, make_ui
from busride.ui.tutorial import pages as tutorial_pages

app = typer.Typer(
    name="busride",
    help="busride: Ride the Bus, solved. Run it with no command for the menu. Exact odds and "
    "the play that loses least, a coach, an arena that grades bots and AI models against "
    "perfect play, and an AI that teaches itself.",
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)

Plain = Annotated[bool, typer.Option("--plain", help="No colour (NO_COLOR works too).")]
Ascii = Annotated[bool, typer.Option("--ascii", help="ASCII only: H D S C suits, # and - bars.")]
Ladder = Annotated[
    str | None,
    typer.Option(
        "--ladder",
        help="Try another payout ladder for this run: numbers (2,2.7,4.1,15) or a preset "
        "(house, classic, fair).",
    ),
]
Game = Annotated[
    str | None,
    typer.Option(
        "--game",
        "-g",
        help="Use another game for this run: a built-in (ride-the-bus, hi-lo-5, in-between, "
        "colour-run-5), one of your games, or a .toml file. Default: your current game.",
    ),
]
RulesPath = Annotated[
    Path | None, typer.Option("--rules", "-r", help="Use the rules in this game file.")
]
DbPath = Annotated[
    Path | None, typer.Option("--db", help="SQLite file of logged rounds (default: yours).")
]

# --plain / --ascii given before the command (busride --plain odds) apply to every screen.
_GLOBAL = {"plain": False, "ascii": False}
_SAVED_GAME = "my-ride-the-bus"  # where `busride init` keeps your rules


def _ui(plain: bool = False, ascii: bool = False) -> Ui:
    return make_ui(plain or _GLOBAL["plain"], ascii or _GLOBAL["ascii"])


def _fail(ui: Ui, message: str) -> NoReturn:
    ui.console.print(Text.assemble(("error: ", "bad"), (message, "")))
    raise typer.Exit(1)


def _note(ui: Ui, message: str) -> None:
    ui.console.print(Text(f"! {message}", style="warn.soft"))


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


# ── which game ───────────────────────────────────────────────────────────────────────────


def _find_game(name: str) -> GameSpec:
    return load_game(name, search=[config.games_dir()])


def _game(
    ui: Ui, game: str | None = None, rules_path: Path | None = None, ladder: str | None = None
) -> Rules:
    """The game for this run: --game, else --rules, else your current game (with your payouts).
    --ladder swaps the payouts for this run only."""
    settings = config.load_settings()
    try:
        name: str | None
        if game:
            rules, name = _find_game(game), game
        elif rules_path is not None:
            rules, name = load_rules(rules_path), None
        else:
            name = settings.game
            rules = _find_game(name)
        if ladder:
            rules = replace(
                rules.with_returns(resolve_ladder(ladder, rules)),
                source=f"{rules.source} + --ladder",
            )
        elif name in settings.payouts and len(settings.payouts[name]) == rules.guess_count:
            rules = replace(
                rules.with_returns(settings.payouts[name]),
                source=f"{rules.source} + your payouts",
            )
        solver.game_tree(rules)  # fail here, with a plain message, if it's too big to solve
    except (RulesError, solver.GameTooBig) as exc:
        _fail(ui, str(exc))
    return rules


def _ride_the_bus_only(ui: Ui, rules: Rules, what: str) -> None:
    if rules.stages != STAGES:
        _fail(
            ui,
            f"{what} works with Ride the Bus only, and your game is {rules.name}. Switch with "
            "`busride games use ride-the-bus`, or pass --game ride-the-bus.",
        )


def _fair_warnings(rules: Rules) -> list[str]:
    if not rules.ladder_captured:
        return []
    out = []
    pairs = zip(rules.returns, solver.survival(rules), strict=True)
    for number, (offered, s) in enumerate(pairs, start=1):
        if offered > 1 / s + 1e-9:
            out.append(
                f"Stage {number} pays {fmt.mult(offered)}, above the fair {fmt.mult(1 / s)} "
                "for always playing to it: double-check the payouts."
            )
    return out


def _payouts(db: Path, rules: Rules) -> PayoutCheck | None:
    if not db.exists():
        return None
    with Store(db) as store:
        paid = [
            (len(r.cards), r.stake or 1.0, r.return_paid)
            for r in store.rounds()
            if r.return_paid is not None
        ]
    return check_payouts(paid, rules.returns)


@app.callback()
def _home(ctx: typer.Context, plain: Plain = False, ascii: Ascii = False) -> None:
    _GLOBAL.update(plain=plain, ascii=ascii)
    if ctx.invoked_subcommand is not None:
        return
    if _interactive():
        run_menu(_ui())
    else:
        typer.echo(ctx.get_help())


# ── odds, advise, cheat sheet ────────────────────────────────────────────────────────────


def _do_odds(
    ui: Ui,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
    db: Path | None = None,
) -> None:
    rules = _game(ui, game, rules_path, ladder)
    result = solver.analyze(rules)
    notes = static_warnings(rules, include_ladder=False) + _fair_warnings(rules)
    payouts = _payouts(db or config.rounds_db(), rules) if rules.stages == STAGES else None
    ui.console.print(screens.analysis(result, ui, payouts, notes))


@app.command()
def odds(
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    db: DbPath = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """How fair the game is: what you get back with perfect play, stage by stage."""
    _do_odds(_ui(plain, ascii), game, rules_path, ladder, db)


app.command("analyze", hidden=True)(odds)


ADVISE_HELP = (
    "Type the cards as they appear (9h, Ks, 10d, Ad; several at once is fine).  "
    "n = new round  u = undo last card  q = quit"
)


def _do_advise(
    ui: Ui,
    cards: list[str] | None = None,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
) -> None:
    rules = _game(ui, game, rules_path, ladder)
    sol = solver.solve(rules)
    length = len(rules.stages)

    def show(seen: list[Card]) -> None:
        if len(seen) == length:
            ui.console.print(screens.round_over(seen, rules, ui))
            return
        if not rules.stages[len(seen)].is_guess:
            ui.console.print(screens.reveal_wait(seen, rules, ui))
            return
        started = time.perf_counter()
        try:
            decision = advise_cards(sol, seen)
        except AdviceError as exc:
            _note(ui, str(exc))
            return
        ui.console.print(screens.advisor(decision, rules, ui, time.perf_counter() - started))

    if cards:
        try:
            seen = parse_cards(" ".join(cards))
        except CardError as exc:
            _fail(ui, str(exc))
        problem = survival_problem(seen, rules)
        if problem:
            _fail(ui, problem)
        show(seen)
        return

    seen = []
    ui.console.print(Text(ADVISE_HELP, style="muted"))
    show(seen)
    prompt = "› " if not ui.ascii else "> "
    while True:
        try:
            line = ui.console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            ui.console.print()
            return
        word = line.lower()
        if not word:
            continue
        if word in ("q", "quit", "exit"):
            return
        if word in ("?", "h", "help"):
            ui.console.print(Text(ADVISE_HELP, style="muted"))
            continue
        if word in ("n", "new"):
            seen = []
        elif word in ("u", "undo"):
            if not seen:
                _note(ui, "Nothing to undo.")
                continue
            seen.pop()
        else:
            try:
                new = parse_cards(line)
            except CardError as exc:
                _note(ui, str(exc))
                continue
            if len(seen) == length:
                seen = []  # the last round finished; this card starts the next one
            candidate = seen + new
            problem = survival_problem(candidate, rules)
            if problem:
                _note(ui, f"{problem}. Type n to start a new round.")
                continue
            seen = candidate
        show(seen)


@app.command()
def advise(
    cards: Annotated[
        list[str] | None,
        typer.Argument(
            help="Cards seen this round, in order (9h Ks). Leave out for the live helper."
        ),
    ] = None,
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Best guess and cash-out decision for the cards on the table."""
    _do_advise(_ui(plain, ascii), cards, game, rules_path, ladder)


def _do_cheatsheet(
    ui: Ui, game: str | None = None, rules_path: Path | None = None, ladder: str | None = None
) -> None:
    rules = _game(ui, game, rules_path, ladder)
    sol = solver.solve(rules)
    ui.console.print(screens.policy(rules, sol.rtp, cheatsheet(sol), ui))


@app.command("cheatsheet")
def cheatsheet_cmd(
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """The whole strategy on one screen: the best play for every situation."""
    _do_cheatsheet(_ui(plain, ascii), game, rules_path, ladder)


app.command("policy", hidden=True)(cheatsheet_cmd)


# ── games ────────────────────────────────────────────────────────────────────────────────


def _do_games_list(ui: Ui) -> None:
    settings = config.load_settings()
    rows = [
        screens.GameRow(name, spec.description, solver.solve(spec).rtp, name == settings.game)
        for name, spec in BUILTIN_GAMES.items()
    ]
    for name, spec in your_games(config.games_dir()).items():
        if isinstance(spec, RulesError):
            rows.append(
                screens.GameRow(name, f"can't be loaded: {spec}", None, name == settings.game, True)
            )
            continue
        try:
            rtp: float | None = solver.solve(spec).rtp
        except solver.GameTooBig:
            rtp = None
        description = spec.description or screens.stage_summary(spec, ui)
        rows.append(screens.GameRow(name, description, rtp, name == settings.game, True))
    ui.console.print(screens.games_list(rows, ui))


def _do_games_show(ui: Ui, name: str) -> None:
    rules = _game(ui, name)
    ui.console.print(screens.rules_panel(rules, static_warnings(rules), ui))
    if rules.description:
        ui.console.print(Text(rules.description, style="muted"))
    ui.console.print(Text(f"Make it your game:  busride games use {name}", style="muted"))
    ui.console.print(Text(f"Try it just once:   busride odds --game {name}", style="muted"))


def _do_games_use(ui: Ui, name: str) -> None:
    try:
        spec = _find_game(name)
        solver.game_tree(spec)
    except (RulesError, solver.GameTooBig) as exc:
        _fail(ui, str(exc))
    config.save_settings(replace(config.load_settings(), game=name))
    ui.console.print(
        Text.assemble(
            (f"{ui.g.check} ", "good"),
            (f"{spec.name} is now your game. ", "heading"),
            ("Every command uses it until you switch again.", "muted"),
        )
    )


def _suggested_ladder(spec: GameSpec) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(fair, suggested): the fair ladder, and one about 5% under it, rounded."""
    fair = tuple(1.0 / s for s in solver.survival(spec))
    return fair, tuple(round(f * 0.95, 2) for f in fair)


def _do_games_new(
    ui: Ui,
    title: str | None,
    stages_text: str | None,
    ladder: str | None,
    use: bool,
    deck: str | None,
    ace: str | None,
    tie_higher_lower: str | None,
    tie_range_edge: str | None,
) -> None:
    c = ui.console
    from_flags = bool(title and stages_text)
    try:
        if from_flags:
            assert title is not None and stages_text is not None
            kinds = [k.strip() for k in stages_text.split(",") if k.strip()]
        else:
            c.print(heading(f"RIDE THE BUS {ui.g.dot} new game", ui))
            c.print(
                Text(
                    "Build a card game from the same questions as Ride the Bus. Each card in a "
                    "round is a question (or is just shown). Enter keeps the value in brackets.",
                    style="muted",
                )
            )
            title = Prompt.ask("Name of the game", default=title or "My Game", console=c)
            count = IntPrompt.ask("How many cards are dealt in a round (1-8)", default=4, console=c)
            count = max(1, min(8, count))
            kinds = []
            for i in range(1, count + 1):
                allowed = [
                    k
                    for k in STAGE_KINDS
                    if not (k == "higher_lower" and i < 2) and not (k == "inside_outside" and i < 3)
                ]
                kinds.append(
                    Prompt.ask(
                        f"Card {i}: what happens", choices=allowed, default=allowed[0], console=c
                    )
                )
        stages = make_stages(kinds)
        has = {s.kind for s in stages}
        model = deck or "fresh_52"
        decks = 1
        ace_rule = ace or "high"
        tie_hl = tie_higher_lower or "lose"
        tie_edge = tie_range_edge or "lose"
        if not from_flags:
            model = Prompt.ask("Deck", choices=list(DECK_MODELS), default=model, console=c)
            if model == "shoe":
                decks = IntPrompt.ask("Decks in the shoe", default=6, console=c)
            if has & {"higher_lower", "inside_outside"}:
                ace_rule = Prompt.ask(
                    "An ace counts", choices=list(ACE_RULES), default=ace_rule, console=c
                )
            if "higher_lower" in has:
                tie_hl = Prompt.ask(
                    "A tie on higher/lower", choices=list(TIE_RULES), default=tie_hl, console=c
                )
            if "inside_outside" in has:
                tie_edge = Prompt.ask(
                    "A card on the edge of the range",
                    choices=list(TIE_RULES),
                    default=tie_edge,
                    console=c,
                )
        guesses = sum(1 for s in stages if s.is_guess)
        spec = GameSpec(
            name=title or "My Game",
            game_version="1",
            captured_on=date.today().isoformat(),
            deck_model=model,
            decks=decks,
            ace=ace_rule,
            tie_higher_lower=tie_hl,
            tie_range_edge=tie_edge,
            returns=(0.0,) * guesses,
            stages=stages,
        )
        solver.game_tree(spec)
        fair, suggested = _suggested_ladder(spec)
        if ladder:
            returns = resolve_ladder(ladder, spec)
        elif from_flags:
            returns = suggested
        else:
            d = f" {ui.g.dot} "
            c.print(
                Text(
                    f"Fair would be {d.join(fmt.ret(f) for f in fair)} (no house edge for always "
                    f"playing to that stage). Suggested, a little under fair: "
                    f"{d.join(fmt.ret(s) for s in suggested)}.",
                    style="muted",
                )
            )
            returns = tuple(
                FloatPrompt.ask(f"Return after guess {i}", default=s, console=c)
                for i, s in enumerate(suggested, start=1)
            )
        spec = spec.with_returns(returns)
    except (EOFError, KeyboardInterrupt):
        c.print(Text("\nNothing saved.", style="muted"))
        raise typer.Exit(1) from None
    except (RulesError, solver.GameTooBig) as exc:
        _fail(ui, str(exc))

    name = slug(spec.name)
    path = config.games_dir() / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_rules(spec), encoding="utf-8")
    saved = replace(load_rules(path), source=f"your game {name}")
    c.print(screens.rules_panel(saved, static_warnings(saved), ui, written_to=str(path)))
    c.print(Text(f"Saved as `{name}`. Edit the file to fine-tune it.", style="muted"))
    if use or (
        not from_flags and Confirm.ask("Make it your current game?", default=True, console=c)
    ):
        _do_games_use(ui, name)


@app.command()
def games(
    target: Annotated[
        str | None,
        typer.Argument(help="A game to show, or: use NAME (make it your game), new (make one)."),
    ] = None,
    extra: Annotated[
        str | None, typer.Argument(help="The game for `use`.", show_default=False)
    ] = None,
    title: Annotated[str | None, typer.Option("--name", help="games new: the game's name.")] = None,
    stages: Annotated[
        str | None,
        typer.Option("--stages", help="games new: card types, e.g. reveal,higher_lower,suit."),
    ] = None,
    ladder: Ladder = None,
    use: Annotated[bool, typer.Option("--use", help="games new: make it your game.")] = False,
    deck: Annotated[str | None, typer.Option("--deck", help="games new: the deck model.")] = None,
    ace: Annotated[
        str | None, typer.Option("--ace", help="games new: high | low | either.")
    ] = None,
    tie_higher_lower: Annotated[str | None, typer.Option("--tie-higher-lower")] = None,
    tie_range_edge: Annotated[str | None, typer.Option("--tie-range-edge")] = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """The games: list them, show one, switch with `games use NAME`, make one with `games new`."""
    ui = _ui(plain, ascii)
    if target is None:
        _do_games_list(ui)
    elif target == "use":
        if not extra:
            _fail(ui, "say which game: busride games use hi-lo-5")
        _do_games_use(ui, extra)
    elif target == "new":
        _do_games_new(ui, title, stages, ladder, use, deck, ace, tie_higher_lower, tie_range_edge)
    else:
        _do_games_show(ui, target)


# ── settings and init ────────────────────────────────────────────────────────────────────


def _settings_rows(ui: Ui, settings: config.Settings) -> list[tuple[str, str]]:
    d = f" {ui.g.dot} "
    try:
        spec = _find_game(settings.game)
        game_text = f"{spec.name} ({settings.game})"
        ladder = settings.payouts.get(settings.game)
        if ladder is not None and len(ladder) == spec.guess_count:
            payouts = d.join(fmt.mult(r) for r in ladder) + "  (yours)"
        else:
            payouts = d.join(fmt.mult(r) for r in spec.returns) + "  (the game's own)"
    except RulesError as exc:
        game_text, payouts = f"{settings.game} (can't be loaded: {exc})", ui.g.dash
    return [
        ("Your game", game_text),
        ("Payouts", payouts),
        ("Coach", settings.coach),
        ("Play money", f"{fmt.count(settings.chips)} chips, stake {fmt.money(settings.stake)}"),
        ("AI model", f"{settings.ai}  (Claude's effort: {settings.effort})"),
        ("Coach wording", settings.coach_ai or "busride's own (no AI)"),
    ]


def _check_ai(ui: Ui, name: str) -> str:
    """An AI agent name, checked without calling anything."""
    try:
        agent = make_agent(name, BUILTIN_GAMES["ride-the-bus"])
    except ValueError as exc:
        _fail(ui, str(exc))
    if not getattr(agent, "paid", None) and not hasattr(agent, "model"):
        _fail(ui, f"{name!r} isn't an AI model: try claude, or ollama:MODEL")
    return name.strip()


def _show_settings(ui: Ui) -> None:
    settings = config.load_settings()
    folders = [
        ("Settings file", str(config.settings_file())),
        ("Your games", str(config.games_dir())),
        ("Your data", str(config.data_dir())),
    ]
    ui.console.print(screens.settings_panel(_settings_rows(ui, settings), folders, ui))
    if settings.problem:
        _note(ui, settings.problem)


def _set_payouts(ui: Ui, text: str | None) -> None:
    settings = config.load_settings()
    if text is None:
        config.save_settings(settings.with_payouts(settings.game, None))
        ui.console.print(Text("Payouts are back to the game's own.", style="muted"))
        return
    try:
        spec = _find_game(settings.game)  # the game's own payouts, so "house" means them
        ladder = resolve_ladder(text, spec)
    except RulesError as exc:
        _fail(ui, str(exc))
    config.save_settings(settings.with_payouts(settings.game, ladder))
    ui.console.print(
        Text(
            f"Payouts for {spec.name} are now {' '.join(fmt.mult(r) for r in ladder)}.",
            style="muted",
        )
    )


def _do_settings(
    ui: Ui,
    ladder: str | None = None,
    reset_payouts: bool = False,
    chips: int | None = None,
    stake: float | None = None,
    coach: str | None = None,
    game: str | None = None,
    ai: str | None = None,
    effort: str | None = None,
    coach_ai: str | None = None,
) -> None:
    changed = False
    if ai is not None or effort is not None or coach_ai is not None:
        if effort is not None and effort not in config.EFFORTS:
            _fail(ui, f"effort must be one of {', '.join(config.EFFORTS)}")
        current = config.load_settings()
        wording = coach_ai
        if wording is not None and wording.strip().lower() in ("", "off", "none"):
            wording = ""
        config.save_settings(
            replace(
                current,
                ai=_check_ai(ui, ai) if ai is not None else current.ai,
                effort=effort or current.effort,
                coach_ai=(_check_ai(ui, wording) if wording else "")
                if wording is not None
                else current.coach_ai,
            )
        )
        changed = True
    if game:
        _do_games_use(ui, game)
        changed = True
    if reset_payouts:
        _set_payouts(ui, None)
        changed = True
    if ladder:
        _set_payouts(ui, ladder)
        changed = True
    if chips is not None or stake is not None or coach is not None:
        if coach is not None and coach not in config.COACH_LEVELS:
            _fail(ui, f"coach must be one of {', '.join(config.COACH_LEVELS)}")
        settings = config.load_settings()
        config.save_settings(
            replace(
                settings,
                chips=chips if chips is not None else settings.chips,
                stake=stake if stake is not None else settings.stake,
                coach=coach if coach is not None else settings.coach,
            )
        )
        changed = True
    _show_settings(ui)
    if changed or not _interactive():
        return
    c = ui.console
    options = {
        "1": "Choose your game",
        "2": "Change the payouts",
        "3": "Go back to the game's own payouts",
        "4": "Chips and stake for play",
        "5": "How much the coach says",
        "6": "Your AI model, for the arena",
        "7": "An AI model to word the coach's explanations",
    }
    while True:
        for key, label in options.items():
            c.print(Text.assemble((f"  {key}  ", "accent"), label))
        try:
            choice = Prompt.ask("Change what? (q to go back)", default="q", console=c).lower()
            if choice in ("q", ""):
                return
            if choice == "1":
                _do_games_list(ui)
                _do_games_use(ui, Prompt.ask("Game name", console=c))
            elif choice == "2":
                _set_payouts(
                    ui, Prompt.ask("New payouts (numbers, or house / classic / fair)", console=c)
                )
            elif choice == "3":
                _set_payouts(ui, None)
            elif choice == "4":
                current = config.load_settings()
                new_chips = IntPrompt.ask("Chips to start with", default=current.chips, console=c)
                new_stake = FloatPrompt.ask("Stake per round", default=current.stake, console=c)
                config.save_settings(
                    replace(current, chips=max(1, new_chips), stake=max(0.01, new_stake))
                )
            elif choice == "5":
                current = config.load_settings()
                level = Prompt.ask(
                    "Coach", choices=list(config.COACH_LEVELS), default=current.coach, console=c
                )
                config.save_settings(replace(current, coach=level))
            elif choice == "6":
                current = config.load_settings()
                name = Prompt.ask(
                    "AI model (claude, claude:MODEL, ollama:MODEL, openai:MODEL...)",
                    default=current.ai,
                    console=c,
                )
                config.save_settings(replace(current, ai=_check_ai(ui, name)))
            elif choice == "7":
                current = config.load_settings()
                name = Prompt.ask(
                    "AI model for the coach's wording (off for busride's own)",
                    default=current.coach_ai or "off",
                    console=c,
                )
                off = name.strip().lower() in ("", "off", "none")
                config.save_settings(replace(current, coach_ai="" if off else _check_ai(ui, name)))
            else:
                _note(ui, "Choose 1-7, or q to go back.")
                continue
        except typer.Exit:
            pass  # the action already said what went wrong
        except (EOFError, KeyboardInterrupt):
            return
        _show_settings(ui)


@app.command()
def settings(
    game: Annotated[str | None, typer.Option("--game", "-g", help="Make this your game.")] = None,
    ladder: Annotated[
        str | None,
        typer.Option(
            "--ladder", help="Your payouts for your game: numbers, or house/classic/fair."
        ),
    ] = None,
    reset_payouts: Annotated[
        bool, typer.Option("--reset-payouts", help="Go back to the game's own payouts.")
    ] = False,
    chips: Annotated[int | None, typer.Option("--chips", min=1, help="Chips to play with.")] = None,
    stake: Annotated[
        float | None, typer.Option("--stake", min=0.01, help="Stake per round.")
    ] = None,
    coach: Annotated[
        str | None, typer.Option("--coach", help="off | hints | review | explain")
    ] = None,
    ai: Annotated[
        str | None,
        typer.Option("--ai", help="Your AI model for the arena: claude, ollama:MODEL, ..."),
    ] = None,
    effort: Annotated[
        str | None, typer.Option("--effort", help="How hard Claude thinks: low ... max.")
    ] = None,
    coach_ai: Annotated[
        str | None,
        typer.Option("--coach-ai", help="An AI model to word the coach's explanations, or off."),
    ] = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Your game, payouts, play money and AI model. With no options it asks what to change."""
    _do_settings(
        _ui(plain, ascii), ladder, reset_payouts, chips, stake, coach, game, ai, effort, coach_ai
    )


def _do_init(
    ui: Ui,
    rules_path: Path | None,
    yes: bool,
    ladder: str | None,
    flags: dict[str, Any],
) -> None:
    c = ui.console
    target = rules_path or config.games_dir() / f"{_SAVED_GAME}.toml"
    base = replace(BUILTIN_GAMES["ride-the-bus"], game_version=PLACEHOLDER_VERSION)
    if target.exists():
        try:
            base = load_rules(target)
        except RulesError as exc:
            _note(ui, f"{exc}. Starting from the defaults.")
    if base.stages != STAGES:
        _fail(ui, f"{target} is not a Ride the Bus game; edit it, or use `busride games new`")
    # Work on the TOML shape directly; parse_rules validates everything at the end.
    data = tomllib.loads(dump_rules(base))
    game, deck_t, ties, payout = data["game"], data["deck"], data["ties"], data["payout"]
    for table, key, name in (
        (game, "game_version", "game_version"),
        (deck_t, "model", "deck"),
        (deck_t, "decks", "decks"),
        (deck_t, "ace", "ace"),
        (ties, "higher_lower", "tie_higher_lower"),
        (ties, "range_edge", "tie_range_edge"),
    ):
        if flags.get(name) is not None:
            table[key] = flags[name]
    if ladder:
        try:
            payout["return_after_stage"] = list(parse_ladder(ladder))
        except RulesError as exc:
            _fail(ui, str(exc))

    if not yes:
        c.print(heading(f"RIDE THE BUS {ui.g.dot} rules wizard", ui))
        c.print(
            Text(
                "Answer from what the game you play shows you; Enter keeps the value in "
                "brackets. Returns are the total paid per 1 staked, stake included.",
                style="muted",
            )
        )

        def choose(text: str, table: dict[str, Any], key: str, options: tuple[str, ...]) -> None:
            table[key] = Prompt.ask(text, choices=list(options), default=str(table[key]), console=c)

        try:
            game["game_version"] = Prompt.ask(
                "Game version", default=str(game["game_version"]), console=c
            )
            choose("Deck model", deck_t, "model", DECK_MODELS)
            if deck_t["model"] == "shoe":
                deck_t["decks"] = IntPrompt.ask(
                    "Decks in the shoe", default=max(2, int(deck_t["decks"])), console=c
                )
            choose("An ace counts", deck_t, "ace", ACE_RULES)
            choose("A tie on higher/lower", ties, "higher_lower", TIE_RULES)
            choose("A card on the edge of the range", ties, "range_edge", TIE_RULES)
            payout["return_after_stage"] = [
                FloatPrompt.ask(
                    f"Return after stage {stage.number} ({stage.question.lower()})",
                    default=float(current),
                    console=c,
                )
                for stage, current in zip(STAGES, payout["return_after_stage"], strict=True)
            ]
            for key, text in (("min_stake", "Minimum"), ("max_stake", "Maximum")):
                game[key] = FloatPrompt.ask(
                    f"{text} stake (0 if unknown)", default=float(game[key]), console=c
                )
            choose("A draw that times out", game, "timeout", TIMEOUT_RULES)
        except (EOFError, KeyboardInterrupt):
            c.print(Text("\nNothing written.", style="muted"))
            raise typer.Exit(1) from None

    game["captured_on"] = date.today().isoformat()
    try:
        rules = parse_rules(data, source=str(target))
    except RulesError as exc:
        _fail(ui, str(exc))
    if not yes and target.exists() and not Confirm.ask(f"Write {target}?", default=True, console=c):
        c.print(Text("Nothing written.", style="muted"))
        raise typer.Exit(0)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump_rules(rules), encoding="utf-8")
    notes = static_warnings(rules) + _fair_warnings(rules)
    c.print(screens.rules_panel(rules, notes, ui, written_to=str(target)))
    if rules_path is None:
        config.save_settings(replace(config.load_settings(), game=_SAVED_GAME))
        c.print(
            Text(
                f"These are now your game's rules ({_SAVED_GAME}). Next: busride odds",
                style="muted",
            )
        )
    else:
        c.print(Text(f"Next: busride odds --rules {target}", style="muted"))


@app.command()
def init(
    rules_path: RulesPath = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Don't ask: keep current values, apply flags, write."),
    ] = False,
    ladder: Ladder = None,
    game_version: Annotated[str | None, typer.Option("--game-version")] = None,
    deck: Annotated[
        str | None, typer.Option("--deck", help="fresh_52 | with_replacement | shoe")
    ] = None,
    decks: Annotated[int | None, typer.Option("--decks", help="Decks in a shoe.")] = None,
    ace: Annotated[str | None, typer.Option("--ace", help="high | low | either")] = None,
    tie_higher_lower: Annotated[
        str | None, typer.Option("--tie-higher-lower", help="lose | push | win")
    ] = None,
    tie_range_edge: Annotated[
        str | None, typer.Option("--tie-range-edge", help="lose | push | win")
    ] = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Wizard for the rules of the Ride the Bus game you play; saved as your game."""
    flags = {
        "game_version": game_version,
        "deck": deck,
        "decks": decks,
        "ace": ace,
        "tie_higher_lower": tie_higher_lower,
        "tie_range_edge": tie_range_edge,
    }
    _do_init(_ui(plain, ascii), rules_path, yes, ladder, flags)


# ── simulate ─────────────────────────────────────────────────────────────────────────────


def _do_simulate(
    ui: Ui,
    rounds: int = 100_000,
    strategy: str = "optimal",
    seed: int | None = None,
    stake: float = 1.0,
    record: Path | None = None,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
) -> None:
    rules = _game(ui, game, rules_path, ladder)
    g = rules.guess_count
    plan = None
    play: Strategy
    if strategy == "optimal":
        sol = solver.solve(rules)
        play, exact = SolverStrategy(sol), sol.rtp
    else:
        m = re.fullmatch(r"greedy|stop:(\d+)", strategy)
        stop = int(m.group(1)) if m and m.group(1) else g
        if not m or not 1 <= stop <= g:
            _fail(ui, f"unknown strategy '{strategy}': use optimal, greedy or stop:1 to stop:{g}")
        plan = solver.fixed_plan(rules, stop)
        play, exact = Greedy(rules, stop), plan.value

    store = None
    if record is not None:
        _ride_the_bus_only(ui, rules, "Recording rounds for busride verify")
        store = Store(record)
        real = {v for v in store.versions() if v != "simulated"}
        if real:
            store.close()
            _fail(
                ui,
                f"{record} holds rounds you logged by hand; record simulations to a separate file",
            )
    rows: list[tuple[list[str], float, float | None]] = []

    def keep_round(cards: list[str], paid: float | None) -> None:
        rows.append((cards, stake, paid * stake if paid else None))  # a 0 payout is a loss

    keep = keep_round if store else None

    if seed is None:
        seed = random.randrange(1_000_000)
    every = max(1000, rounds // 100)
    with Live(
        screens.sim_live(SimResult(), rounds, ui),
        console=ui.console,
        transient=True,
        refresh_per_second=10,
    ) as live:

        def progress(res: SimResult) -> None:
            live.update(screens.sim_live(res, rounds, ui))

        res = simulate(
            rules,
            play,
            rounds,
            seed=seed,
            stake=stake,
            on_progress=progress,
            progress_every=every,
            record=keep,
        )
    ui.console.print(screens.sim_report(res, rules, ui, strategy, exact, plan, seed))
    if store is not None:
        n = store.add_many(rows, game_version="simulated")
        store.close()
        ui.console.print(
            Text(
                f"Saved {fmt.count(n)} simulated rounds to {record}: "
                f"try busride verify --db {record}",
                style="muted",
            )
        )


@app.command("simulate")
def simulate_cmd(
    rounds: Annotated[int, typer.Option("--rounds", "-n", min=1, help="Rounds to play.")] = 100_000,
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy", "-s", help="optimal | greedy | stop:K (greedy, cash out after K)"
        ),
    ] = "optimal",
    seed: Annotated[int | None, typer.Option("--seed", help="Fix the random seed.")] = None,
    stake: Annotated[float, typer.Option("--stake", help="Stake per round.")] = 1.0,
    record: Annotated[
        Path | None,
        typer.Option(
            "--record",
            help="Also save the simulated rounds to this SQLite file (try busride verify on it).",
        ),
    ] = None,
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Pretend rounds with random cards, to double-check the exact maths."""
    _do_simulate(_ui(plain, ascii), rounds, strategy, seed, stake, record, game, rules_path, ladder)


app.command("sim", hidden=True)(simulate_cmd)


# ── log and verify ───────────────────────────────────────────────────────────────────────

_PAYOUT = re.compile(r"^(x)?(\d+(?:\.\d+)?)(x)?$", re.IGNORECASE)
LOG_HELP = (
    "One round per line: the cards in order, then what you were paid if you cashed out.  "
    "9h Ks 3d 42  (42 paid)   9h Ks 3d x4.2  (4.2 times the stake)   2c 5h  (lost)\n"
    "u = undo last round   s 20 = set stake   q = quit"
)


def parse_entry(text: str, stake: float) -> tuple[list[str], float | None]:
    """Cards in order, then an optional payout: an amount (42) or a multiple (x4.2 / 4.2x)."""
    tokens = text.replace(",", " ").split()
    paid = None
    if tokens:
        m = _PAYOUT.match(tokens[-1])
        if m:
            amount = float(m.group(2))
            paid = amount * stake if (m.group(1) or m.group(3)) else amount
            tokens = tokens[:-1]
            if paid == 0:
                paid = None
    if not tokens:
        raise ValueError("type the cards first, like 9h Ks 3d")
    cards = [str(parse_card(t)) for t in tokens]
    if len(cards) > 4:
        raise ValueError(f"a round shows at most 4 cards, got {len(cards)}")
    return cards, paid


def _ladder_note(paid: float | None, stake: float, n: int, rules: Rules | None) -> str | None:
    if paid is None or rules is None or not rules.ladder_captured or stake <= 0:
        return None
    check = check_payouts([(n, stake, paid)], rules.returns)
    if check.mismatches:
        ladder = " ".join(fmt.mult(r) for r in rules.returns)
        return f"{fmt.mult(paid / stake)} is not on the ladder of your game ({ladder})"
    return None


def _do_log(
    ui: Ui,
    db: Path | None = None,
    stake: float | None = None,
    entry: list[str] | None = None,
    rules_path: Path | None = None,
) -> None:
    c = ui.console
    rules = _game(ui, None, rules_path)
    _ride_the_bus_only(ui, rules, "busride log")
    db = db or config.rounds_db()
    version = rules.game_version
    current_stake = stake if stake is not None else (rules.min_stake or 1.0)

    with Store(db) as store:

        def record(cards: list[str], paid: float | None) -> None:
            saved = store.add(cards, current_stake, paid, version)
            c.print(screens.log_line(saved.id, saved.cards, current_stake, paid, store.count(), ui))
            note = _ladder_note(paid, current_stake, len(cards), rules)
            if note:
                c.print(Text(f"  ! {note}", style="warn.soft"))

        if entry:
            for text in entry:
                try:
                    cards, paid = parse_entry(text, current_stake)
                except (ValueError, CardError) as exc:
                    _fail(ui, f"{text!r}: {exc}")
                record(cards, paid)
                if len(set(cards)) < len(cards):
                    c.print(
                        Text(
                            "  ! a card repeats inside this round: evidence that cards can repeat",
                            style="warn.soft",
                        )
                    )
            return

        d = ui.g.dot
        status = f"{db} {d} stake {fmt.money(current_stake)} {d} {fmt.count(store.count())} logged"
        c.print(heading(f"RIDE THE BUS {d} log", ui, status))
        c.print(Text(LOG_HELP, style="muted"))
        prompt = "› " if not ui.ascii else "> "
        while True:
            try:
                line = c.input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                c.print()
                break
            word = line.lower()
            if not word:
                continue
            if word in ("q", "quit", "exit"):
                break
            if word in ("?", "h", "help"):
                c.print(Text(LOG_HELP, style="muted"))
                continue
            if word in ("u", "undo"):
                gone = store.undo()
                if gone is None:
                    c.print(Text("  Nothing to undo.", style="warn.soft"))
                else:
                    left = fmt.count(store.count())
                    shown = " ".join(gone.cards)
                    c.print(Text(f"  removed #{gone.id} ({shown}); {left} logged", style="muted"))
                continue
            m = re.fullmatch(r"(?:s|stake)\s+(\d+(?:\.\d+)?)", word)
            if m:
                current_stake = float(m.group(1))
                c.print(Text(f"  stake is now {fmt.money(current_stake)}", style="muted"))
                continue
            try:
                cards, paid = parse_entry(line, current_stake)
            except (ValueError, CardError) as exc:
                c.print(Text(f"  ! {exc}", style="warn.soft"))
                continue
            if len(set(cards)) < len(cards) and not Confirm.ask(
                "  A card repeats inside this round, which proves cards can repeat. Record it?",
                default=False,
                console=c,
            ):
                continue
            record(cards, paid)


@app.command()
def log(
    db: DbPath = None,
    stake: Annotated[
        float | None, typer.Option("--stake", help="Stake per round (default 1).")
    ] = None,
    entry: Annotated[
        list[str] | None,
        typer.Option("--entry", "-e", help='Log a round without prompting, e.g. -e "9h Ks 3d 42".'),
    ] = None,
    rules_path: RulesPath = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Record real Ride the Bus rounds, one line each (u to undo)."""
    _do_log(_ui(plain, ascii), db, stake, entry, rules_path)


def _do_verify(
    ui: Ui, db: Path | None = None, alpha: float = 0.05, rules_path: Path | None = None
) -> None:
    rules = _game(ui, None, rules_path)
    _ride_the_bus_only(ui, rules, "busride verify")
    db = db or config.rounds_db()
    logged = []
    if db.exists():
        with Store(db) as store:
            logged = store.rounds()
    try:
        rounds = [[parse_card(x) for x in r.cards] for r in logged]
    except CardError as exc:
        _fail(ui, f"{db} holds a card that cannot be read: {exc}")
    report = verify_rounds(rounds, rules, alpha)
    paid = [
        (len(r.cards), r.stake or 1.0, r.return_paid) for r in logged if r.return_paid is not None
    ]
    payouts = check_payouts(paid, rules.returns) if paid else None
    ui.console.print(screens.verify_report(report, rules, ui, payouts, source=str(db)))


@app.command()
def verify(
    db: DbPath = None,
    alpha: Annotated[
        float, typer.Option("--alpha", min=0.0001, max=0.5, help="Family-wise error rate.")
    ] = 0.05,
    rules_path: RulesPath = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Is the dealing fair? Tests your logged rounds and names the deck model that fits."""
    _do_verify(_ui(plain, ascii), db, alpha, rules_path)


# ── play ─────────────────────────────────────────────────────────────────────────────────


def _do_play(
    ui: Ui,
    rounds: int | None = None,
    coach: str | None = None,
    chips: int | None = None,
    stake: float | None = None,
    seed: int | None = None,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
) -> None:
    rules = _game(ui, game, rules_path, ladder)
    settings = config.load_settings()
    level = coach or settings.coach
    if level not in config.COACH_LEVELS:
        _fail(ui, f"coach must be one of {', '.join(config.COACH_LEVELS)}")
    stake_size = stake or settings.stake
    session = Session(rules, chips or settings.chips, stake_size, seed)
    c = ui.console
    c.print(play_ui.welcome(session.chips, stake_size, level, ui))
    reword = None
    if level == "explain" and settings.coach_ai:
        try:
            reword = Rewording(settings.coach_ai, rules)
        except ValueError as exc:
            _note(ui, f"The coach uses its own wording: {exc}.")
        else:
            c.print(
                Text(
                    f"The coach's explanations are reworded by {settings.coach_ai} (one call "
                    "each; busride still works out every number).",
                    style="muted",
                )
            )
    hints = level != "off"
    stopping = False

    def ask(prompt: str) -> str | None:
        try:
            return c.input(prompt)
        except (EOFError, KeyboardInterrupt):
            c.print()
            return None

    while not stopping and (rounds is None or len(session.rounds) < rounds):
        if not session.can_play():
            c.print(play_ui.out_of_chips(ui))
            break
        answer = ask(play_ui.deal_prompt(len(session.rounds) + 1, ui))
        if answer is None or answer.strip().lower() in ("q", "quit", "exit"):
            break
        rnd = session.new_round()
        while not rnd.over:
            stage = rnd.next_stage
            assert stage is not None
            if not stage.is_guess:
                c.print(play_ui.shown(rnd.reveal(), ui))
                continue
            decision = rnd.decision()
            c.print(play_ui.table(rnd, decision, hints, ui))
            typed = ask("Your move: ")
            if typed is None:
                stopping = True
                if not rnd.can_stop:
                    break  # leave the round unfinished: the stake stays on the table
                typed = "$"
            choice = parse_choice(typed, stage, rnd.can_stop)
            if choice == "quit":
                stopping = True
                if not rnd.can_stop:
                    _note(ui, "Your stake is in: make this guess first, then you can stop.")
                    stopping = False
                    continue
                choice = CASH
            if choice is None:
                options = ", ".join(f"{i} {g}" for i, g in enumerate(stage.guesses, start=1))
                cash = ", $ to stop" if rnd.can_stop else ""
                _note(ui, f"Type {options}{cash} (or q to quit).")
                continue
            step = rnd.act(choice)
            c.print(play_ui.after(step, rnd, ui))
            if level in ("review", "explain") and step.graded is not None:
                c.print(play_ui.coach_line(review(step.graded, stake_size), ui))
            if level == "explain":
                text = why(decision, rules)
                if reword is not None:
                    text = reword(text)
                    if reword.problem is not None:
                        _note(ui, f"The coach went back to its own wording: {reword.problem}.")
                        reword = None
                c.print(play_ui.why_line(text))
        c.print(play_ui.round_line(rnd, session.chips, stake_size, ui))
        c.print()
    c.print(play_ui.summary(session.summary(), stake_size, footer(rules, ui), ui))


@app.command()
def play(
    rounds: Annotated[
        int | None, typer.Option("--rounds", "-n", min=1, help="Stop after this many rounds.")
    ] = None,
    coach: Annotated[
        str | None,
        typer.Option("--coach", help="off | hints | review | explain (default: your setting)"),
    ] = None,
    chips: Annotated[
        int | None, typer.Option("--chips", min=1, help="Chips to start with.")
    ] = None,
    stake: Annotated[
        float | None, typer.Option("--stake", min=0.01, help="Stake per round.")
    ] = None,
    seed: Annotated[
        int | None, typer.Option("--seed", help="Deal the same cards every time.")
    ] = None,
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Play rounds with fake chips while a coach reviews every move."""
    _do_play(_ui(plain, ascii), rounds, coach, chips, stake, seed, game, rules_path, ladder)


# ── arena ────────────────────────────────────────────────────────────────────────────────

arena_app = typer.Typer(
    help="The arena: agents play the same deals, and every move is graded against perfect play.",
    no_args_is_help=True,
)
app.add_typer(arena_app, name="arena")

DEFAULT_AGENTS = "optimal,greedy,stop:2,random"
RunName = Annotated[
    str | None,
    typer.Argument(help="A run's name (see busride arena runs) or a .jsonl file. Default: latest."),
]


class _StopRun(Exception):
    """You chose to stop while playing in the arena, or the cost limit was reached."""

    def __init__(self, why: str = "Stopped.") -> None:
        super().__init__(why)


class _PilotDone(Exception):
    """The first deal, played to measure what the AI calls cost, is done."""


def _run_path(ui: Ui, name: str) -> Path:
    if name.lower().endswith(".jsonl"):
        return Path(name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        _fail(ui, f"a run name uses letters, digits, '.', '-' and '_' only, not {name!r}")
    return config.runs_dir() / f"{name}.jsonl"


def _open_run(ui: Ui, name: str | None) -> RunFile:
    if name is None:
        runs = runs_in(config.runs_dir())
        if not runs:
            ui.console.print(arena_ui.no_runs(ui))
            raise typer.Exit(0)
        return runs[0]
    run = RunFile(_run_path(ui, name))
    if not run.exists():
        _fail(ui, f"there is no arena run called {name!r}: see them with `busride arena runs`")
    try:
        run.header()
    except ValueError as exc:
        _fail(ui, str(exc))
    return run


def _default_run(rules: Rules, seed: int, deals: int) -> Path:
    """'ride-the-bus-seed7-2000', so running the same command again resumes it."""
    path = config.runs_dir() / f"{slug(rules.name)}-seed{seed}-{deals}.jsonl"
    run = RunFile(path)
    with suppress(ValueError, KeyError):
        if run.exists() and run.header()["fingerprint"] != fingerprint(rules):
            path = path.with_name(f"{path.stem}-{fingerprint(rules)[:6]}.jsonl")
    return path


def _ask_human(ui: Ui) -> Callable[[Observation], Action]:
    c = ui.console

    def ask(obs: Observation) -> Action:
        c.print(arena_ui.human_table(obs, ui))
        while True:
            try:
                typed = c.input("Your move: ")
            except (EOFError, KeyboardInterrupt):
                c.print()
                raise _StopRun from None
            choice = parse_choice(typed, Stage(obs.kind, obs.stage), obs.can_cash_out)
            if choice == "quit":
                raise _StopRun
            if choice is not None:
                return Action(choice, reason="typed by you")
            options = ", ".join(f"{i} {g}" for i, g in enumerate(obs.options, start=1))
            cash = ", $ to stop" if obs.can_cash_out else ""
            _note(ui, f"Type {options}{cash} (or q to stop).")

    return ask


def _show_leaderboard(ui: Ui, run: RunFile) -> None:
    header, rules = run.header(), run.rules()
    boards = list(score(run).values())
    if not boards:
        _note(ui, f"No deals finished yet in {run.name}.")
        return
    rtp = oracle_for(rules).rtp
    ui.console.print(arena_ui.leaderboard(run.name, header, rules, boards, rtp, ui))


def _spent(lines: list[dict[str, Any]]) -> float:
    return sum(
        float(d.get("meta", {}).get("cost", 0.0)) for d in lines if d.get("type") == "decision"
    )


def _measured(run: RunFile, agent: str) -> tuple[float | None, int]:
    """(cost per deal, deals played) from what an agent has played in a run so far."""
    if not run.exists():
        return None, 0
    deals = sum(1 for r in run.finished() if r["agent"] == agent)
    cost, unknown = 0.0, False
    for d in run.decisions():
        if d["agent"] == agent:
            meta = d.get("meta", {})
            unknown = unknown or bool(meta.get("cost_unknown"))
            cost += float(meta.get("cost", 0.0))
    return (None if unknown or not deals else cost / deals), deals


def _estimates(run: RunFile, paid: list[Any], total: int, rules: Rules) -> list[arena_ui.CostRow]:
    rows = []
    for agent in paid:
        per_deal, done = _measured(run, agent.name)
        left = max(0, total - done)
        if per_deal is not None:
            rows.append(arena_ui.CostRow(agent.name, left, per_deal * left, per_deal))
        else:  # nothing measured yet: a guess, counting every stage as a decision
            rows.append(
                arena_ui.CostRow(agent.name, left, agent.rough_cost(left * rules.guess_count))
            )
    return rows


def _play_arena(
    ui: Ui,
    arena: Arena,
    players: list[Any],
    human: bool,
    budget: dict[str, float],
    max_cost: float | None,
    pilot: bool = False,
) -> RunFile:
    """Play, with a progress line (or the human's results), counting what AI calls cost."""
    c = ui.console
    paid = {p.name for p in players if getattr(p, "paid", False)}
    played = {"paid": False}

    def on_play(agent: str, lines: list[dict[str, Any]]) -> None:
        budget["spent"] += _spent(lines)
        played["paid"] = played["paid"] or agent in paid
        if agent == "human":
            moves = [d for d in lines if d["type"] == "decision"]
            good = sum(1 for d in moves if d.get("regret") is not None and d["regret"] <= 1e-9)
            c.print(arena_ui.human_result(lines[-1]["deal"], lines[-1], good, len(moves), ui))
            c.print()
        if max_cost is not None and budget["spent"] >= max_cost:
            raise _StopRun(
                f"Stopped at the cost limit: {fmt.dollars(budget['spent'])} spent "
                f"(--max-cost {fmt.dollars(max_cost)})."
            )

    if human:
        return arena.run(players, on_play=on_play)
    with Live(Text(""), console=c, transient=True, refresh_per_second=10) as live:

        def on_deal(n: int, total: int) -> None:
            if pilot and played["paid"]:
                raise _PilotDone
            if paid or n % 50 == 0 or n == total:
                money = f" {ui.g.dot} spent {fmt.dollars(budget['spent'])}" if paid else ""
                live.update(
                    Text(f"Dealing {fmt.count(n)} of {fmt.count(total)}{money}", style="muted")
                )

        return arena.run(players, on_deal=on_deal, on_play=on_play)


def _price_line(ui: Ui) -> str:
    from busride.agents.llm.prices import load_prices

    table = load_prices()
    return f"Prices: {table.source}, checked {table.as_of}. See or edit them: busride arena prices"


def _ok_to_spend(
    ui: Ui,
    arena: Arena,
    players: list[Any],
    rules: Rules,
    total: int,
    budget: dict[str, float],
    max_cost: float | None,
) -> bool:
    """Show what the paid agents will cost and ask. With nothing measured yet, one deal is
    played first to measure it, then you're asked again."""
    c = ui.console
    paid = [p for p in players if getattr(p, "paid", False)]
    rows = _estimates(arena.file, paid, total, rules)
    c.print(arena_ui.cost_estimate(rows, _price_line(ui), max_cost, measured=False, ui=ui))
    guesses = [r for r in rows if r.per_deal is None and r.deals > 1]
    if not guesses:
        return Confirm.ask("Go ahead?", default=True, console=c)
    if not Confirm.ask("Play 1 deal first, to measure the real cost?", default=True, console=c):
        return False
    with suppress(_PilotDone):
        _play_arena(ui, arena, players, False, budget, max_cost, pilot=True)
    rows = _estimates(arena.file, paid, total, rules)
    c.print(arena_ui.cost_estimate(rows, "", max_cost, measured=True, ui=ui))
    if all(r.deals == 0 for r in rows):
        return True
    return Confirm.ask("Play the rest?", default=True, console=c)


def _do_arena_run(
    ui: Ui,
    agents: str = DEFAULT_AGENTS,
    deals: int | None = None,
    seed: int | None = None,
    name: str | None = None,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
    effort: str | None = None,
    fallback: bool = True,
    max_cost: float | None = None,
    yes: bool = False,
) -> None:
    names = [a.strip() for a in agents.split(",") if a.strip()]
    if not names:
        _fail(ui, f"name at least one agent: {agent_names_help()}")
    path = _run_path(ui, name) if name else None
    saved = path is not None and RunFile(path).exists()
    if path is not None and saved and not (game or rules_path or ladder):
        try:
            rules = RunFile(path).rules()  # carry on with the run's own game
        except (ValueError, KeyError, RulesError) as exc:
            _fail(ui, f"{path} can't be read as an arena run: {exc}")
    else:
        rules = _game(ui, game, rules_path, ladder)
    human = "human" in (n.lower() for n in names)
    ai = [n for n in names if is_ai(n)]
    if not saved and deals is None:
        deals = 20 if human or ai else DEFAULT_DEALS
    if human and not saved and seed is None:
        seed = random.randrange(1, 1_000_000)  # new cards each time you sit down
    if path is None:
        assert deals is not None
        path = _default_run(rules, DEFAULT_SEED if seed is None else seed, deals)
    llm = None
    if ai:
        from busride.agents.llm import LLMOptions  # the AI SDKs load only when needed

        settings = config.load_settings()
        llm = LLMOptions(
            effort=effort or settings.effort, fallback=fallback, default_ai=settings.ai
        )
    try:
        players = [
            make_agent(n, rules, ask=_ask_human(ui) if human else None, llm=llm) for n in names
        ]
    except ValueError as exc:
        _fail(ui, str(exc))
    paid = [p for p in players if getattr(p, "paid", False)]
    arena = Arena(rules, path, seed=seed, deals=deals)
    c = ui.console
    if paid and not yes and not _interactive():
        who = ", ".join(p.name for p in paid)
        _fail(
            ui,
            f"{who} cost{'s' if len(paid) == 1 else ''} money for every decision, so busride "
            "asks before it starts. Run this in a terminal to see the estimate first, or add "
            "--yes (with --max-cost DOLLARS for a limit) to go ahead without asking.",
        )
    budget = {"spent": 0.0}
    unavailable = False
    try:
        total = len(arena.file.header()["deals"]) if saved else deals or DEFAULT_DEALS
        if (
            paid
            and not yes
            and not _ok_to_spend(ui, arena, players, rules, total, budget, max_cost)
        ):
            _note(ui, "Nothing more was played.")
        else:
            if human:
                c.print(
                    Text(
                        "You play the same deals as the other agents. Type the number of your "
                        "choice, $ to stop, q to quit (finished deals are kept).",
                        style="muted",
                    )
                )
            _play_arena(ui, arena, players, human, budget, max_cost)
    except _StopRun as stop:
        _note(ui, f"{stop} Finished deals are saved: carry on with --name {path.stem}.")
    except AgentUnavailable as exc:
        unavailable = True
        _note(
            ui,
            f"Stopped: {exc}. Finished deals are saved; run the same command again to carry on.",
        )
    except ValueError as exc:
        _fail(ui, str(exc))
    run = arena.file
    if paid:
        c.print(Text(f"AI calls this time: {fmt.dollars(budget['spent'])}", style="muted"))
    if run.exists() and run.finished():
        _show_leaderboard(ui, run)
        c.print(Text(f"Replay a deal: busride arena replay {run.name} --deal 1", style="accent"))
        c.print(Text(f"This table again: busride arena leaderboard {run.name}", style="accent"))
        if not ai and not human:
            c.print(
                Text(
                    "Add an AI model: busride arena run --agents optimal,claude --deals 20 "
                    "(or ollama:MODEL, free on your computer)",
                    style="muted",
                )
            )
    if unavailable:
        raise typer.Exit(1)


@arena_app.command("run")
def arena_run(
    agents: Annotated[
        str,
        typer.Option(
            "--agents",
            "-a",
            help="Who plays, separated by commas: optimal, greedy, stop:K, random, human, or "
            "an AI model like claude or ollama:llama3.1:8b (see busride arena agents).",
        ),
    ] = DEFAULT_AGENTS,
    deals: Annotated[
        int | None,
        typer.Option(
            "--deals",
            "-n",
            min=1,
            help="Deals to play (default 2,000; 20 with a human or an AI model).",
        ),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option(
            "--seed",
            help="Which deals: the same seed, the same cards (default 7; random with a human).",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Save the run under this name; an existing run carries on."),
    ] = None,
    effort: Annotated[
        str | None,
        typer.Option("--effort", help="How hard Claude thinks: low, medium, high, xhigh, max."),
    ] = None,
    no_fallback: Annotated[
        bool,
        typer.Option(
            "--no-fallback",
            help="If Claude declines a request, don't let a fallback model answer instead.",
        ),
    ] = False,
    max_cost: Annotated[
        float | None,
        typer.Option("--max-cost", min=0.0, help="Stop once AI calls have cost this many dollars."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Don't ask before spending money on AI calls.")
    ] = False,
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Agents play the same deals; every move is graded against perfect play."""
    _do_arena_run(
        _ui(plain, ascii),
        agents,
        deals,
        seed,
        name,
        game,
        rules_path,
        ladder,
        effort,
        not no_fallback,
        max_cost,
        yes,
    )


@arena_app.command("leaderboard")
def arena_leaderboard(run: RunName = None, plain: Plain = False, ascii: Ascii = False) -> None:
    """The ranking for one run (the latest unless you name one)."""
    ui = _ui(plain, ascii)
    _show_leaderboard(ui, _open_run(ui, run))


def _do_arena_replay(
    ui: Ui, run_name: str | None, deal: int, agent: str | None, worst: bool
) -> None:
    run = _open_run(ui, run_name)
    header, rules = run.header(), run.rules()
    agents = run.agents()
    if agent is not None and agent not in agents:
        _fail(ui, f"{agent!r} didn't play in {run.name}: try {', '.join(agents) or 'none yet'}")
    decisions = list(run.decisions())
    c = ui.console
    if worst:
        if agent is None:
            others = [a for a in agents if a != "optimal"]
            if len(others) != 1:
                _fail(ui, f"say whose moves to show: --agent, one of {', '.join(agents)}")
            agent = others[0]
        mine = [d for d in decisions if d["agent"] == agent]
        costly = sorted(
            (d for d in mine if (d.get("regret") or 0.0) > 1e-9),
            key=lambda d: (-d["regret"], d["deal"]),
        )[:10]
        c.print(arena_ui.mistakes(run.name, agent, costly, len(mine), ui))
        return
    count = len(header["deals"])
    if not 1 <= deal <= count:
        _fail(ui, f"{run.name} has deals 1 to {count}")
    finished = {(r["agent"], r["deal"]): r for r in run.finished()}
    plays = []
    for a in [agent] if agent else agents:
        if (a, deal) in finished:
            moves = [d for d in decisions if d["agent"] == a and d["deal"] == deal]
            plays.append((a, moves, finished[a, deal]))
    if not plays:
        _fail(ui, f"nobody has played deal {deal} of {run.name} yet")
    c.print(arena_ui.replay(run.name, deal, count, header["deals"][deal - 1], plays, rules, ui))


@arena_app.command("replay")
def arena_replay(
    run: RunName = None,
    deal: Annotated[int, typer.Option("--deal", "-d", help="Which deal, from 1.")] = 1,
    agent: Annotated[
        str | None, typer.Option("--agent", "-a", help="Show only this agent.")
    ] = None,
    worst: Annotated[
        bool, typer.Option("--worst", help="Instead, the agent's 10 costliest moves.")
    ] = False,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Step through a deal, move by move, with the exact answer beside each move."""
    _do_arena_replay(_ui(plain, ascii), run, deal, agent, worst)


@arena_app.command("runs")
def arena_runs(plain: Plain = False, ascii: Ascii = False) -> None:
    """The saved arena runs, newest first."""
    ui = _ui(plain, ascii)
    folder = config.runs_dir()
    runs = runs_in(folder)
    if not runs:
        ui.console.print(arena_ui.no_runs(ui))
        return
    rows = []
    for run in runs:
        try:
            h = run.header()
            rows.append(
                arena_ui.RunRow(
                    run.name, h["game"], len(h["deals"]), tuple(run.agents()), h["created"]
                )
            )
        except (ValueError, KeyError) as exc:
            rows.append(arena_ui.RunRow(run.name, "", 0, (), "", problem=str(exc)))
    ui.console.print(arena_ui.runs_list(rows, str(folder), ui))


@arena_app.command("agents")
def arena_agents(plain: Plain = False, ascii: Ascii = False) -> None:
    """The agents you can put in the arena."""
    ui = _ui(plain, ascii)
    ui.console.print(arena_ui.agents_list(BASELINES, AI_AGENTS, ui))


@arena_app.command("prices")
def arena_prices(plain: Plain = False, ascii: Ascii = False) -> None:
    """What AI model calls cost, from a table you can edit (made on first use)."""
    from busride.agents.llm.prices import dump_prices, load_prices, prices_file

    ui = _ui(plain, ascii)
    path = prices_file()
    table = load_prices(path)
    rows = [(name, p.input, p.output, p.cache_read) for name, p in table.prices.items()]
    ui.console.print(arena_ui.prices_table(rows, table.source, table.as_of, ui))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_prices(table), encoding="utf-8")
        ui.console.print(
            Text(f"Saved a copy you can edit: {path}", style="accent", overflow="fold")
        )
    else:
        ui.console.print(Text(f"Edit them in {path}", style="accent", overflow="fold"))


# ── train ────────────────────────────────────────────────────────────────────────────────


def default_episodes(rules: Rules) -> int:
    """Enough practice for the game's size: about 70 rounds per situation, 300,000 at least."""
    return max(300_000, min(3_000_000, 70 * solver.game_tree(rules).size))


def _do_train(
    ui: Ui,
    algorithm: str = "q-learning",
    episodes: int | None = None,
    seed: int = 1,
    name: str | None = None,
    save: bool = True,
    game: str | None = None,
    rules_path: Path | None = None,
    ladder: str | None = None,
) -> None:
    from busride.agents.rl import agent as rl_agent
    from busride.agents.rl.qlearning import ALGORITHMS, Checkpoint, train
    from busride.ui import train as train_ui

    algorithm = {"q": "q-learning", "qlearning": "q-learning"}.get(algorithm.lower(), algorithm)
    if algorithm not in ALGORITHMS:
        _fail(ui, f"the method is one of {', '.join(ALGORITHMS)} (or q for short)")
    rules = _game(ui, game, rules_path, ladder)
    total = episodes or default_episodes(rules)
    short = "q" if algorithm == "q-learning" else "sarsa"
    name = name or f"{short}-{slug(rules.name)}"
    if save and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        _fail(ui, f"a name uses letters, digits, '.', '-' and '_' only, not {name!r}")
    c = ui.console
    c.print(train_ui.intro(rules, algorithm, total, ui))
    points: list[Checkpoint] = []
    with Live(Text(""), console=c, transient=True, refresh_per_second=10) as live:

        def on_checkpoint(point: Checkpoint, optimal: float) -> None:
            points.append(point)
            live.update(train_ui.live(points, optimal, total, ui))

        result = train(rules, total, algorithm, seed, on_checkpoint=on_checkpoint)
    saved = str(rl_agent.save(result, name)) if save else None
    c.print(train_ui.report(result, rules, name if save else None, saved, ui))


@app.command("train")
def train_cmd(
    algorithm: Annotated[
        str,
        typer.Option("--method", "-m", help="q-learning (or q) or sarsa: how the agent learns."),
    ] = "q-learning",
    episodes: Annotated[
        int | None,
        typer.Option(
            "--episodes",
            "-n",
            min=1,
            help="Practice rounds (default: enough for the game, 300,000 for Ride the Bus).",
        ),
    ] = None,
    seed: Annotated[
        int, typer.Option("--seed", help="Its random choices: same seed, same agent.")
    ] = 1,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Save it under this name, for the arena as rl:NAME."),
    ] = None,
    no_save: Annotated[bool, typer.Option("--no-save", help="Train, but don't keep it.")] = False,
    game: Game = None,
    rules_path: RulesPath = None,
    ladder: Ladder = None,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """Train a learning agent from scratch and watch it approach perfect play."""
    _do_train(
        _ui(plain, ascii), algorithm, episodes, seed, name, not no_save, game, rules_path, ladder
    )


# ── tutorial and doctor ──────────────────────────────────────────────────────────────────


def _do_tutorial(ui: Ui, pause: bool) -> None:
    rtb = BUILTIN_GAMES["ride-the-bus"]
    sol = solver.solve(rtb)
    example = solver.decide(sol, parse_cards("9h Ks"))
    pages = tutorial_pages(rtb, example, sol.rtp, ui)
    for i, page in enumerate(pages, start=1):
        ui.console.print(page)
        ui.console.print()
        if pause and i < len(pages):
            try:
                answer = ui.console.input("Press Enter for the next page (q to stop) ")
            except (EOFError, KeyboardInterrupt):
                return
            if answer.strip().lower() == "q":
                return


@app.command()
def tutorial(
    no_pause: Annotated[bool, typer.Option("--no-pause", help="Print every page at once.")] = False,
    plain: Plain = False,
    ascii: Ascii = False,
) -> None:
    """A 2-minute guided intro: start here."""
    _do_tutorial(_ui(plain, ascii), pause=_interactive() and not no_pause)


API_KEYS = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
)


def _ollama_models(url: str) -> list[str] | None:
    """The models a local Ollama has, or None when it isn't running (asked with a 1 s limit)."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=1.0) as reply:
            data = json.load(reply)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return [str(m.get("name", "?")) for m in data.get("models", []) if isinstance(m, dict)]


def _do_doctor(ui: Ui) -> None:
    checks: list[tuple[str, str, str]] = []
    py = sys.version_info
    checks.append(
        (
            "good" if py >= (3, 11) else "bad",
            "Python",
            f"{platform.python_version()}" + ("" if py >= (3, 11) else ": busride needs 3.11+"),
        )
    )
    checks.append(("good", "busride", __version__))
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    if encoding == "utf8":
        checks.append(("good", "Card symbols", "your terminal can show ♥ ♦ ♣ ♠"))
    else:
        checks.append(
            ("warn", "Card symbols", "not sure they show here: add --ascii if you see boxes")
        )
    colours = ui.console.color_system or "none"
    checks.append(("good", "Colours", f"{colours} (use --plain to switch them off)"))

    settings = config.load_settings()
    if settings.problem:
        checks.append(("warn", "Settings", settings.problem + " (fix it, or run busride settings)"))
    elif config.settings_file().exists():
        checks.append(("good", "Settings", "saved"))
    else:
        checks.append(("good", "Settings", "none saved yet: using the defaults"))

    try:
        started = time.perf_counter()
        spec = _find_game(settings.game)
        solver.solve(spec)
        took = fmt.duration(time.perf_counter() - started)
        checks.append(("good", "Your game", f"{spec.name}: solved exactly in {took}"))
    except (RulesError, solver.GameTooBig) as exc:
        checks.append(("bad", "Your game", f"{exc} (try: busride games use ride-the-bus)"))

    mine = your_games(config.games_dir())
    broken = [name for name, g in mine.items() if isinstance(g, RulesError)]
    if broken:
        checks.append(
            ("warn", "Your games", f"{len(mine)}, but these don't load: {', '.join(broken)}")
        )
    else:
        checks.append(("good", "Your games", f"{len(mine)} saved" if mine else "none yet"))

    db = config.rounds_db()
    if db.exists():
        with Store(db) as store:
            checks.append(("good", "Logged rounds", f"{fmt.count(store.count())} in {db}"))
    else:
        checks.append(("muted", "Logged rounds", "none yet (busride log records them)"))

    versions = []
    for package in ("anthropic", "openai"):
        try:
            versions.append(f"{package} {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            versions.append(f"{package} missing")
    missing = any("missing" in v for v in versions)
    checks.append(
        (
            "warn" if missing else "good",
            "AI packages",
            ", ".join(versions) + (" (reinstall busride to get them)" if missing else ""),
        )
    )
    for key in API_KEYS:
        found = bool(os.environ.get(key))  # only whether it's there: never its value
        hint = " (or `ant auth login`)" if key == "ANTHROPIC_API_KEY" else ""
        where = f" (from {config.ENV_FROM[key]})" if key in config.ENV_FROM else ""
        checks.append(
            (
                "good" if found else "muted",
                key,
                f"found{where}" if found else f"not set{hint}: only needed for AI players",
            )
        )
    url = config.ollama_url()
    models = _ollama_models(url)
    if models is None:
        checks.append(("muted", "Ollama", f"not running at {url}: only needed for ollama: players"))
    elif not models:
        checks.append(
            ("warn", "Ollama", "running, with no models yet: try `ollama pull llama3.1:8b`")
        )
    else:
        shown = ", ".join(models[:3]) + (", ..." if len(models) > 3 else "")
        checks.append(("good", "Ollama", f"running, {len(models)} models: {shown}"))

    folders = [
        ("Settings folder", str(config.config_dir())),
        ("Data folder", str(config.data_dir())),
    ]
    ui.console.print(screens.doctor_report(checks, folders, ui))


@app.command()
def doctor(plain: Plain = False, ascii: Ascii = False) -> None:
    """Check your setup: folders, settings, your game, API keys (only their presence)."""
    _do_doctor(_ui(plain, ascii))


# ── the home menu ────────────────────────────────────────────────────────────────────────


def _menu_actions(ui: Ui) -> dict[str, Callable[[], None]]:
    return {
        "tutorial": lambda: _do_tutorial(ui, pause=_interactive()),
        "play": lambda: _do_play(ui),
        "advise": lambda: _do_advise(ui),
        "cheatsheet": lambda: _do_cheatsheet(ui),
        "odds": lambda: _do_odds(ui),
        "arena run": lambda: _do_arena_run(ui),
        "train": lambda: _do_train(ui),
        "games": lambda: _do_choose_game(ui),
        "settings": lambda: _do_settings(ui),
        "simulate": lambda: _do_simulate(ui, rounds=20_000),
        "log": lambda: _do_log(ui),
        "verify": lambda: _do_verify(ui),
        "doctor": lambda: _do_doctor(ui),
    }


def _do_choose_game(ui: Ui) -> None:
    """Choose a game from the menu: the list, then a name."""
    _do_games_list(ui)
    if not _interactive():
        return
    name = Prompt.ask(
        "Type a game's name to make it yours (Enter keeps yours)", default="", console=ui.console
    )
    if name.strip():
        _do_games_use(ui, name.strip())


def _menu_header(ui: Ui) -> tuple[str, float | None]:
    settings = config.load_settings()
    d = ui.g.dot
    try:
        spec = _find_game(settings.game)
        ladder = settings.payouts.get(settings.game)
        if ladder and len(ladder) == spec.guess_count:
            spec = spec.with_returns(ladder)
        payouts = " ".join(fmt.ret(r) for r in spec.returns)
        line = f"Your game: {spec.name} {d} payouts {payouts}"
        rtp = solver.solve(spec).rtp if spec.ladder_captured else None
    except (RulesError, solver.GameTooBig) as exc:
        line, rtp = f"Your game: {settings.game} (can't be loaded: {exc})", None
    return line, rtp


def run_menu(ui: Ui, read: Callable[[str], str] | None = None) -> None:
    """The home menu. `read` asks for a line (tests pass a script)."""
    ask = read or (lambda prompt: ui.console.input(prompt))
    actions = _menu_actions(ui)
    items = screens.MENU_ITEMS
    keys = {item.key: item for item in items}
    while True:
        line, rtp = _menu_header(ui)
        ui.console.print(screens.home_menu(line, rtp, items, ui))
        try:
            choice = ask(f"Choose 1-{len(items)} (or q): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ui.console.print()
            return
        if choice in ("q", "quit", "exit"):
            return
        item = keys.get(choice)
        if item is None:
            _note(ui, f"Choose one of 1-{len(items)}, or q to quit.")
            continue
        ui.console.print(Text(item.label, style="heading"))
        with suppress(typer.Exit):  # a failed action has already said why; back to the menu
            actions[item.command]()
        ui.console.print(Text(f"Next time, type: busride {item.command}", style="accent"))
        try:
            ask("Press Enter for the menu ")
        except (EOFError, KeyboardInterrupt):
            ui.console.print()
            return


def main() -> None:
    # Box and card glyphs need UTF-8 even when output is piped on Windows.
    for stream in (sys.stdout, sys.stderr):
        if (
            isinstance(stream, io.TextIOWrapper)
            and (stream.encoding or "").lower().replace("-", "") != "utf8"
        ):
            with suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8")
    # Piped input (PowerShell, scripts) may start with a byte-order mark; utf-8-sig drops it.
    if isinstance(sys.stdin, io.TextIOWrapper) and not sys.stdin.isatty():
        with suppress(ValueError, OSError):
            sys.stdin.reconfigure(encoding="utf-8-sig")
    config.load_env_files()  # API keys kept in a .env file
    try:
        app()
    except OSError as exc:
        # the reader went away (`busride --help | head`): stop quietly, as other tools do
        closed = isinstance(exc, BrokenPipeError) or exc.errno == errno.EINVAL
        if not closed or sys.stdout.isatty():
            raise
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)


if __name__ == "__main__":
    main()
