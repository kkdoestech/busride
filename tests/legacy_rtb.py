"""Frozen copy of the original Ride the Bus solver, kept as an oracle.

It uses the hand-written state key and loops over every card for every transition. The generic
engine must reproduce its values exactly, state by state. Do not "improve" this file.
"""

from collections import Counter
from collections.abc import Sequence

from busride.engine.cards import Card, remaining
from busride.engine.rules import Rules
from busride.engine.stages import Result, judge

GUESSES = (
    ("red", "black"),
    ("higher", "lower"),
    ("inside", "outside"),
    ("hearts", "diamonds", "clubs", "spades"),
)
END = ("end",)


def legacy_key(seen: Sequence[Card]) -> tuple[object, ...]:
    k = len(seen)
    if k == 0:
        return ()
    if k == 1:
        return (seen[0].rank,)
    if k == 2:
        return (seen[0].rank, seen[1].rank, seen[0].suit == seen[1].suit)
    if k == 3:
        return tuple(sorted(Counter(c.suit for c in seen).values(), reverse=True))
    return END


def legacy_solve(
    rules: Rules,
) -> tuple[list[dict[tuple[object, ...], float]], list[dict[tuple[object, ...], tuple[Card, ...]]]]:
    """Values per level (k cards seen) and one representative card sequence per state."""
    reps: list[dict[tuple[object, ...], tuple[Card, ...]]] = [{(): ()}, {}, {}, {}, {}]
    branches: list[
        dict[tuple[object, ...], list[tuple[dict[tuple[object, ...], int], int, int]]]
    ] = [{} for _ in range(4)]
    for k in range(4):
        for key, seen in reps[k].items():
            pool = remaining(seen, rules.deck_model, rules.effective_decks)
            total = sum(w for _, w in pool)
            out = []
            for guess in GUESSES[k]:
                to: dict[tuple[object, ...], int] = {}
                push = 0
                for card, w in pool:
                    result = judge(k + 1, guess, seen, card, rules)[1]
                    if result is Result.WIN:
                        nxt = (*seen, card)
                        nk = legacy_key(nxt)
                        to[nk] = to.get(nk, 0) + w
                        reps[k + 1].setdefault(nk, nxt)
                    elif result is Result.PUSH:
                        push += w
                out.append((to, push, total))
            branches[k][key] = out

    values: list[dict[tuple[object, ...], float]] = [{} for _ in range(5)]
    values[4][END] = rules.returns[3]
    for k in range(3, -1, -1):
        cash = 1.0 if k == 0 else rules.returns[k - 1]
        for key, options in branches[k].items():
            best = max(
                (sum(w * values[k + 1][nk] for nk, w in to.items()) + push * cash) / total
                for to, push, total in options
            )
            values[k][key] = best if k == 0 else max(cash, best)
    return values, reps
