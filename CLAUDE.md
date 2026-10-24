# Ride the Bus analyzer

`docs/SPEC.md` is the source of truth: goals, the game model, commands, solver, arena,
agents and acceptance tests. `docs/ROADMAP.md` lists the milestones and their status. Read both
before changing behaviour. The main user is a first-time player who only knows the card game:
every screen must make sense to them.

## Rules of the project

- One milestone per session. Stop and show the result at its acceptance line.
- Tests before engine code. The four known survival values in the spec are the first
  regression test; never loosen them to make a change pass.
- No input or output inside `src/busride/engine/` (and none in `stats/`). Screens live in `ui/`,
  terminal I/O in `cli.py`.
- `src/busride/sim.py` must not import the solver or stage logic: it is the independent check.
- Format every number through `src/busride/ui/fmt.py`.
- Colour carries meaning only: green = positive expected value, amber = within 2%, red = losing.
- Before finishing: `uv run pytest`, `uv run ruff check src tests`, `uv run mypy`.
- Screen changes: rerun with `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_screens.py` and read
  the diff of `tests/snapshots/` before accepting it.
