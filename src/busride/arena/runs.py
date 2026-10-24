"""Arena runs on disk: one JSON object per line, appended as the run goes.

The first line describes the run (game, rules, seed and every deal), then each finished
(agent, deal) adds its decisions followed by one "deal" line. A pair counts as done only once its
deal line is written, so a run stopped halfway resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from busride.engine.game import GameSpec
from busride.engine.rules import parse_rules

FORMAT = 1


def fingerprint(rules: GameSpec) -> str:
    """What makes two runs comparable: everything that shapes play and pay, not the name."""
    shape = repr((rules.structure, rules.returns, rules.forced_first_bet))
    return hashlib.sha256(shape.encode()).hexdigest()[:12]


class RunFile:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @property
    def name(self) -> str:
        return self.path.stem

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def records(self) -> list[dict[str, Any]]:
        """Every complete line. A line cut short (the run was stopped mid-write) is skipped."""
        out = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    out.append(record)
        return out

    def header(self) -> dict[str, Any]:
        records = self.records() if self.exists() else []
        if not records or records[0].get("type") != "run":
            raise ValueError(f"{self.path} is not an arena run")
        if records[0].get("format", 0) > FORMAT:
            raise ValueError(f"{self.path} was written by a newer busride: update to read it")
        return records[0]

    def rules(self) -> GameSpec:
        h = self.header()
        rules = parse_rules(tomllib.loads(h["rules"]), source=h.get("source", self.name))
        return rules.with_returns(h["returns"])  # exact floats, as played

    def finished(self) -> list[dict[str, Any]]:
        """The "deal" lines: one per (agent, deal) played to the end."""
        return [r for r in self.records() if r.get("type") == "deal"]

    def done(self) -> set[tuple[str, int]]:
        return {(r["agent"], r["deal"]) for r in self.finished()}

    def decisions(self) -> Iterator[dict[str, Any]]:
        """The decisions of finished (agent, deal) pairs, in order. If a pair was started,
        stopped and replayed, only the replay counts."""
        pending: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for r in self.records():
            pair = (r.get("agent", ""), r.get("deal", 0))
            if r.get("type") == "decision":
                lines = pending.setdefault(pair, [])
                if lines and r["position"] <= lines[-1]["position"]:
                    lines.clear()  # the deal started over
                lines.append(r)
            elif r.get("type") == "deal":
                yield from pending.pop(pair, [])

    def agents(self) -> list[str]:
        """Agents in the order they first finished a deal."""
        seen: dict[str, None] = {}
        for r in self.finished():
            seen.setdefault(r["agent"], None)
        return list(seen)

    def start(self, header: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(_line(header), encoding="utf-8")

    @contextmanager
    def writer(self) -> Iterator[Callable[[Iterable[dict[str, Any]]], None]]:
        """Appends records; each call is written and flushed in one piece."""
        with self.path.open("rb+") as f:
            f.seek(0, 2)
            if f.tell():
                f.seek(-1, 2)
                if f.read(1) != b"\n":  # a line cut short: start on a fresh one
                    f.seek(0, 2)
                    f.write(b"\n")
            f.seek(0, 2)

            def write(records: Iterable[dict[str, Any]]) -> None:
                f.write("".join(_line(r) for r in records).encode("utf-8"))
                f.flush()

            yield write


def _line(record: dict[str, Any]) -> str:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"


def runs_in(folder: Path) -> list[RunFile]:
    """The runs in a folder, newest first."""
    if not folder.exists():
        return []
    files = [RunFile(p) for p in folder.glob("*.jsonl")]
    return sorted(files, key=lambda r: r.path.stat().st_mtime, reverse=True)
