"""SQLite access. The rounds table is the only state in the project that changes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from busride.engine.cards import parse_card

SCHEMA = """
CREATE TABLE IF NOT EXISTS rounds (
    id           INTEGER PRIMARY KEY,
    played_at    TEXT NOT NULL,
    game_version TEXT,
    stake        REAL,
    card1        TEXT,
    card2        TEXT,
    card3        TEXT,
    card4        TEXT,
    return_paid  REAL
)
"""
_COLUMNS = "id, played_at, game_version, stake, card1, card2, card3, card4, return_paid"


@dataclass(frozen=True)
class LoggedRound:
    id: int
    played_at: str
    game_version: str | None
    stake: float | None
    cards: tuple[str, ...]  # in the order shown; cards never shown are left out
    return_paid: float | None  # None if the round was lost


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalise(cards: Sequence[str]) -> list[str]:
    if not 1 <= len(cards) <= 4:
        raise ValueError(f"a round shows 1 to 4 cards, got {len(cards)}")
    return [str(parse_card(c)) for c in cards]


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)  # your data folder, on first use
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def add(
        self,
        cards: Sequence[str],
        stake: float,
        return_paid: float | None,
        game_version: str | None = None,
        played_at: str | None = None,
    ) -> LoggedRound:
        shown = _normalise(cards)
        padded = [*shown, None, None, None][:4]
        when = played_at or _now()
        cur = self.conn.execute(
            "INSERT INTO rounds (played_at, game_version, stake, card1, card2, card3, card4,"
            " return_paid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (when, game_version, stake, *padded, return_paid),
        )
        self.conn.commit()
        assert cur.lastrowid is not None
        return LoggedRound(cur.lastrowid, when, game_version, stake, tuple(shown), return_paid)

    def add_many(
        self,
        rows: Iterable[tuple[Sequence[str], float, float | None]],
        game_version: str | None = None,
    ) -> int:
        when = _now()
        data = [
            (when, game_version, stake, *[*_normalise(cards), None, None, None][:4], paid)
            for cards, stake, paid in rows
        ]
        self.conn.executemany(
            "INSERT INTO rounds (played_at, game_version, stake, card1, card2, card3, card4,"
            " return_paid) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            data,
        )
        self.conn.commit()
        return len(data)

    def undo(self) -> LoggedRound | None:
        """Remove and return the most recent round."""
        last = self.conn.execute(
            f"SELECT {_COLUMNS} FROM rounds ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is None:
            return None
        self.conn.execute("DELETE FROM rounds WHERE id = ?", (last[0],))
        self.conn.commit()
        return _row(last)

    def rounds(self) -> list[LoggedRound]:
        return [_row(r) for r in self.conn.execute(f"SELECT {_COLUMNS} FROM rounds ORDER BY id")]

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0])

    def versions(self) -> set[str | None]:
        return {r[0] for r in self.conn.execute("SELECT DISTINCT game_version FROM rounds")}


def _row(r: tuple[Any, ...]) -> LoggedRound:
    cards = tuple(str(c) for c in r[4:8] if c)
    stake = float(r[3]) if r[3] is not None else None
    paid = float(r[8]) if r[8] is not None else None
    return LoggedRound(int(r[0]), str(r[1]), r[2], stake, cards, paid)
