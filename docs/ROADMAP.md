# busride roadmap

Each milestone ends with every test passing and something you can run. Details are in
[`SPEC.md`](SPEC.md).

| # | Milestone | Acceptance | Status |
| --- | --- | --- | --- |
| M0 | **Specs + rename**: SPEC and ROADMAP written; material tied to the original video-game version removed; package renamed `bus` → `busride` (`bus` kept as an alias); no logic change | All existing tests pass; no references to that video game left in the repo | done |
| M1 | **Generic engine, Ride the Bus only**: GameSpec, projected-cell state key, cell loop, state budget, variable ladder, forced-first-bet flag | Known values unchanged; the old key used as an oracle (equal values, exactly 329 states); known-value tests untouched | done |
| M2 | **Stage library and built-in games**: reveal stages; hi-lo-5, in-between, colour-run-5; TOML game files; `--game`; generic cheat sheet; a simulator that interprets specs independently | Per game: brute force (reduced deck and sampled full deck), sim within 4 SE, state-count guards, Hypothesis key soundness | done |
| M3 | **Beginner shell**: user folders, home menu, `tutorial`, `doctor` (offline checks), commands renamed `odds` / `cheatsheet` / `simulate`, plain-language screens; switching the current game (`games` remembers it) and the `games new` wizard | Menu snapshots (unicode and ascii); a non-terminal run prints help | done |
| M4 | **Play and coach**: `play` with fake chips; coach off / hints / review / explain (template); session summary | A scripted 3-round game; snapshots at width 80 | done |
| M5 | **Arena (offline)**: agent protocol, baselines, duplicate deals, scoring, JSONL, resume, leaderboard, replay | Optimal regret = 0; greedy regret ≈ rtp − fixed plan; resume works | done |
| M6 | **LLM agents**: Claude and OpenAI-compatible (Ollama, OpenAI, OpenRouter, Groq, LM Studio); cost guard; LLM coach phrasing; `doctor` checks keys and Ollama | Tests with mocked transports; live smoke tests skipped without keys | done |
| M7 | **Reinforcement learning**: tabular Q-learning and SARSA, an exact-evaluation learning curve, saved agents in the arena, an optional Gymnasium env | Under 1% regret on Ride the Bus within a fixed episode budget | done |
| M8 | **GitHub polish**: beginner README, demo SVGs, example leaderboard, GUIDE rewrite, MIT licence, CONTRIBUTING, CI on 3 operating systems, examples | Fresh clone to the home menu in 2 commands | done |

## Ideas for later (not in v0.2)

- The full party version of Ride the Bus (pyramid and bus phases) with AI players.
- A small web UI over the same engine.
- Publishing to PyPI (`pipx install busride`).
- More stage types (an exact-rank guess, a pair guess) and spread-based payouts (the real
  Acey-Deucey).
