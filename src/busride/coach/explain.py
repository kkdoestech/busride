"""What the coach says. Every number comes from the solver; these functions only put it in words.

(An AI model may rephrase these sentences later, but it never computes the numbers.)
"""

from __future__ import annotations

from dataclasses import dataclass

from busride.engine.game import GameSpec
from busride.engine.solver import Decision
from busride.play import CASH, CLOSE, Graded
from busride.ui import fmt

_SAME = 0.005  # values this near print the same at two decimals


@dataclass(frozen=True)
class Review:
    kind: str  # "good", "warn" or "bad", for colour
    text: str


def move_name(move: str, walk_away: bool = False) -> str:
    """'CASH OUT', 'WALK AWAY' or the guess in capitals."""
    if move == CASH:
        return "WALK AWAY" if walk_away else "CASH OUT"
    return move.upper()


def is_close(graded: Graded) -> bool:
    return not graded.optimal and graded.regret <= CLOSE * max(graded.value, 1e-9)


def review(graded: Graded, stake: float) -> Review:
    """How good the move was, in one line."""
    walk = graded.stage == 1 and not graded.forced
    best = move_name(graded.best, walk)
    if graded.trivial:
        return Review("good", "every choice was worth the same here.")
    if graded.optimal:
        return Review("good", "best move.")
    lost = graded.regret
    if lost < _SAME:
        return Review("good", f"fine: {best} was worth almost exactly the same.")
    if is_close(graded):
        return Review("warn", f"close: {best} was a little better ({fmt.ret(lost)} per 1 staked).")
    return Review(
        "bad",
        f"better was {best}: that move gave up {fmt.ret(lost)} per 1 staked, about "
        f"{fmt.money(lost * stake)} chips on average.",
    )


def _values(a: float, b: float) -> tuple[str, str]:
    """Two values to compare, with a third decimal when two would make them look equal."""
    digits = 3 if abs(a - b) < _SAME else 2
    return fmt.ret(a, digits), fmt.ret(b, digits)


def why(decision: Decision, rules: GameSpec) -> str:
    """The reason for the best move, with the numbers behind it."""
    best = decision.best
    k = len(decision.seen)
    survived = rules.guesses_before(k)
    after = ", counting the best play after" if rules.guess_count - survived > 1 else ""
    odds = f"wins with {fmt.frac(best.wins, best.total)} cards ({fmt.pct(best.win_chance)})"
    forced = survived == 0 and rules.forced_first_bet
    if forced and all(abs(o.ev - best.ev) < 1e-9 for o in decision.options):
        names = " and ".join(o.guess for o in decision.options)
        return f"Your stake is in and {names} are equally good: nothing to get wrong here."
    if forced:
        return (
            f"Your stake is in, so you must guess. {best.guess.capitalize()} {odds}, the best "
            f"of the choices: worth {fmt.ret(best.ev)} on average{after}."
        )
    go, stop = _values(decision.continue_value, decision.cash_out)
    stopping = "keeping your stake" if survived == 0 else "cashing out now"
    if decision.should_continue:
        return (
            f"Going on with {best.guess}, which {odds}, is worth {go} on average{after}, "
            f"against {stop} for {stopping}."
        )
    return (
        f"{stopping.capitalize()} pays {stop} for sure. Going on, the best guess is "
        f"{best.guess}: it {odds} and is worth only {go} on average{after}."
    )
