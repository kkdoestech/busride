# Contributing to busride

Thanks for helping. busride is small enough to read in an afternoon, and every number it shows
can be checked, so the bar is: the maths stays exact, and every screen makes sense to someone
who only knows the card game.

## Set up

```sh
git clone https://github.com/<you>/busride.git && cd busride   # your fork
uv sync --all-extras        # Python 3.11+, the dev tools, and the optional Gymnasium extra
uv run busride doctor       # checks your setup
```

No API key is needed for anything except AI agents. Never commit one: put keys in `.env`
(copy `.env.example`), which git ignores.

## Before you open a pull request

```sh
uv run pytest                     # about a minute and a half; live AI tests are skipped
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy                       # strict
```

CI runs the same on Linux, macOS and Windows, with Python 3.11 and 3.13.

**Screen changes:** run `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_screens.py`, then read the
diff of `tests/snapshots/` before committing. Screens are checked at width 80, with no text cut
short, no escape codes under `--plain`, and pure ASCII under `--ascii`.

## The rules of the project

- [`docs/SPEC.md`](docs/SPEC.md) is the source of truth; [`docs/ROADMAP.md`](docs/ROADMAP.md)
  lists what is done and what's next. Change the spec in the same pull request as the behaviour.
- **Tests before engine code.** The four known survival odds (0.50000, 0.36199, 0.23771,
  0.06307) and the fair-ladder RTP (1.146) are regression tests: never loosen them to make a
  change pass.
- `src/busride/engine/` and `stats/` do no input or output. Screens live in `ui/`, terminal I/O
  in `cli.py`.
- `src/busride/sim.py` must not import the solver or the stage logic: it is the independent check.
- Every number on screen goes through `src/busride/ui/fmt.py`.
- Colour carries meaning only: green is positive expected value, amber is within 2%, red is
  losing. Numbers that include luck get no colour.
- Write for a first-time player: plain words first, jargon only with its meaning beside it.
- AI calls happen only in `agents/llm/` and `coach/`. Tests use fake clients; anything that
  costs money is opt-in (`tests/test_live.py`) and shows an estimate first.
- Fake chips only: no real-money features.

## Common changes

**A new game:** a TOML file is often enough (see [`examples/`](examples/)). A new built-in goes in
`src/busride/engine/builtins.py`, with a brute-force check and a simulator check in
`tests/test_builtin_games.py`, and a state-count guard.

**A new stage type:** `engine/game.py` (the stage), `engine/stages.py` (judging and what the key
keeps), the simulator's own interpreter in `sim.py`, and the brute-force tests.

**A new AI provider:** if it speaks the OpenAI chat API, add a `Preset` in
`agents/llm/openai_agent.py`, its key in `cli.API_KEYS`, a row in `baselines.AI_AGENTS`, and
tests with a fake client in `tests/test_llm.py`. Add its prices to `agents/llm/prices.py` only
with a source and a date.

**A new learning method:** `agents/rl/qlearning.py` trains on `TreeGame` and is scored exactly
with `engine.solver.policy_value`; keep its acceptance test in `tests/test_rl.py`.
