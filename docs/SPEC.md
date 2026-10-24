# busride: specification

Version 0.2 (draft) · 2026-10-23 · status: approved plan, building milestone by milestone
(see [`ROADMAP.md`](ROADMAP.md)).

## 1. Summary

**busride** is a terminal app built around the card game **Ride the Bus**. You can do three
things with it:

1. **Play and learn.** Play rounds with fake chips while a coach shows the odds and explains
   every decision in plain words.
2. **Benchmark AI.** Watch AI models (Claude, GPT, local Llama via Ollama, and others) play.
   An exact solver grades every decision.
3. **Train AI.** Train a reinforcement-learning agent and watch it converge on perfect play.

**Why this game?** Ride the Bus is small enough that perfect play can be computed *exactly*.
Every decision in every situation has a provably correct answer and an exact value. That
turns a party card game into a teaching tool, and into a rare AI benchmark that has a perfect
answer key.

## 2. Who it is for

| Person | Wants | Gets |
| --- | --- | --- |
| **First-time player** (knows the card game, nothing else) | To play, and learn when to stop | `busride` opens a menu: play with a coach, ask for advice, print a cheat sheet |
| **AI tinkerer** | To compare how models reason about probability and risk | `busride arena`: the same deals for every model, graded exactly, on a leaderboard |
| **RL learner** | A small environment with a known optimum | `busride train`: a learning curve measured against the exact optimum |
| **Game designer** | To test payout ladders and rule variants | `busride odds` and custom game files |

**The main user is the first-time player.** Every feature must be usable by someone who has
never opened a terminal tool before, without reading documentation first.

## 3. Principles

1. **Zero setup.**
   - `busride` alone opens a numbered home menu, from any folder.
   - Settings and data live in the user's own folders, so there is nothing to configure.
   - A sensible default game is ready to play.
2. **Plain language first.** Screens say "you get back 96 for every 100 you bet, on average",
   not "RTP 0.963". A technical term appears only with its meaning beside it.
3. **Teach the shortcut.** After every menu action, the screen shows the direct command
   ("Next time, type: `busride advise 9h Ks`").
4. **Offline by default.** Only the LLM agents and the LLM coach need an API key or a local
   model server. Everything else works with no network.
5. **Forgiving input.** A typo gets a one-line explanation and a "Try: ..." suggestion, never a
   stack trace.
6. **Colour carries meaning.**
   - Green = good expected value; amber = marginal (within 2%); red = losing play.
   - `--plain`, `--ascii` and `NO_COLOR` work everywhere.
   - Screens fit an 80-column terminal.
7. **Honest numbers.**
   - Exact values are labelled exact; estimates come with their uncertainty.
   - Every screen footer names the game and rules used.

## 4. Non-goals

- No real-money gambling features. busride uses fake chips only. It measures house edges; it
  does not help beat real casinos.
- No graphical or web interface. CLI only. A web UI could come later; it is not in v0.2.
- No connection to, reading of, or automation of any other game or app.
- `log`/`verify` (tracking real games) support Ride the Bus only. Other games are not covered.

## 5. The game

### 5.1 Ride the Bus (the default game)

You bet a **stake**. Cards come from a shuffled 52-card deck, one per stage:

| Stage | Question | You win if... |
| --- | --- | --- |
| 1 | Red or black? | the card has the colour you named |
| 2 | Higher or lower? | the card is higher or lower than card 1, as you said |
| 3 | Inside or outside? | the card is strictly between cards 1 and 2 (inside), or not between them (outside), as you said |
| 4 | Which suit? | the card has the suit you named |

- After winning a stage you can **cash out** for that stage's **return** (the total paid per 1
  staked, stake included), or carry on.
- Losing a stage loses the stake. There is no cash-out before stage 1.
- The four returns form the **ladder**.

### 5.2 Rule options

| Option | Values | Default |
| --- | --- | --- |
| Deck | `fresh_52` (new shuffled deck each round), `with_replacement` (each card from a full deck, so repeats are possible), `shoe` (N decks mixed) | `fresh_52` |
| Ace | `high`, `low`, `either` (whichever helps the player) | `high` |
| Tie on higher/lower | `lose`, `push` (round ends, pays the current cash-out), `win` | `lose` |
| Tie on the range edge | `lose`, `push`, `win` | `lose` |
| Ladder | one return per guessing stage | game-specific |

### 5.3 Built-in games

Each built-in ships with a default ladder. The state counts are the exact solver's (fresh deck,
measured during design).

| Game | Stages | Default ladder | Perfect-play return | States |
| --- | --- | --- | --- | --- |
| `ride-the-bus` (default) | colour, higher/lower, inside/outside, suit | 1.8 · 2.3 · 3.2 · 12 | 0.963 (house edge 3.7%) | 329 |
| `hi-lo-5` | reveal, then 5 × higher/lower against the previous card | 1.2 · 1.6 · 2.2 · 3.0 · 4.2 | 0.962 (3.8%) | 28,237 |
| `in-between` | reveal, reveal, inside/outside (a simplified Acey-Deucey; the real game pays by spread, which a ladder can't express) | 1.4 | 0.975 (2.5%) | 183 |
| `colour-run-5` | 5 × red/black | 1.9 · 3.8 · 7.5 · 15 · 29 | 0.975 (2.5%) | 9 |

Ride the Bus also gets two presets that are useful for teaching:

- `classic`: 2 · 3 · 4 · 20. These round numbers look fair, but perfect play returns **1.31**,
  a 31% player edge.
- `fair`: each step's fair payout, i.e. 1 ÷ the chance of surviving to it. Perfect play returns
  1.146, because cashing out at the right moment beats any fixed plan.

### 5.4 Game files

Custom games are TOML files:

```toml
[game]
name = "My Hi-Lo"
forced_first_bet = false     # true: stage 1 must be played (Ride the Bus)

[deck]
model = "fresh_52"
ace = "high"

[ties]
higher_lower = "lose"
range_edge = "lose"

[[stage]]
type = "reveal"

[[stage]]
type = "higher_lower"        # compares with the previous card

[[stage]]
type = "inside_outside"
between = [1, 2]             # 1-based stage numbers of the reference cards

[payout]
ladder = [1.4, 2.6]          # one return per guessing stage (reveals don't count)
```

**Stage types:** `colour`, `higher_lower`, `inside_outside`, `suit`, `reveal`.

- `higher_lower` compares with the previous card unless given `against = N`.
- `inside_outside` compares with the two previous cards unless given `between = [A, B]`.
- `[deck] ranks = [7, 8, 9, 10, 11, 12, 13, 14]` makes a short deck.
- A file with no `[[stage]]` tables is Ride the Bus, so the original `rules.toml` format still
  works, with `return_after_stage` in place of `ladder`.

**Validation.** Files are checked when loaded:
- the ladder has one entry per guessing stage;
- references point at earlier stages;
- the game fits the solver's state budget (§8).

Errors name the line to fix.

## 6. Commands

| Command | What it does |
| --- | --- |
| `busride` | Home menu. Shows the help text instead when not run in a terminal (pipes, CI) |
| `busride tutorial` | A 2-minute guided intro: what the tool does, a demo round, where to go next |
| `busride play` | Play rounds with fake chips. `--coach off\|hints\|review\|explain`, `--chips N` |
| `busride advise [cards]` | The best move for the cards on the table. With no cards, a live mode where you type cards as they appear |
| `busride cheatsheet` | The whole strategy on one screen, to keep open while playing |
| `busride odds` | How fair the game is: your return with perfect play, stage by stage, fair vs offered payouts, where the game takes its edge |
| `busride games` | List and switch games. `games new` is a wizard for a custom game; `games show NAME` |
| `busride settings` | Change payouts, rules, coach level, the default AI model (`--ai`), Claude's effort (`--effort`) and the coach's AI wording (`--coach-ai`) |
| `busride arena run` | Run agents on the same seeded deals and grade every decision. `--agents`, `--deals`, `--seed`, `--name` |
| `busride arena leaderboard [RUN]` | The ranking for one run (the latest unless named) |
| `busride arena replay [RUN]` | One deal (`--deal N`), each agent's moves beside the exact answer; `--worst` lists an agent's 10 costliest moves |
| `busride arena runs` | The saved runs, newest first |
| `busride arena agents` | List the agents you can use, built in and AI |
| `busride arena prices` | What AI calls cost per million tokens; writes an editable `prices.toml` |
| `busride train` | Train a learning agent (`--method q-learning\|sarsa`, `--episodes`, `--seed`, `--name`) with a live, exact learning curve; it is saved for the arena as `rl:NAME` |
| `busride simulate` | Pretend rounds to double-check the maths |
| `busride log` / `verify` | Record real Ride the Bus rounds, then test the dealing for fairness |
| `busride doctor` | Check the setup: data folders, API keys found, Ollama reachable, terminal capabilities |

- **Global options:** `--game NAME`, `--plain`, `--ascii`. Each command also has `--help`.
- **Agent names**, used by the arena and by `train` output:

  | Name | Plays |
  | --- | --- |
  | `optimal` | the exact solver |
  | `greedy` | always takes the most likely guess, never cashes out |
  | `random` | random legal moves |
  | `stop:K` | the most likely guess, cashing out after stage K |
  | `rl:FILE` | a trained RL agent |
  | `claude:MODEL` | Claude through the Anthropic API |
  | `openai:MODEL` | OpenAI |
  | `ollama:MODEL` | a local model through Ollama |
  | `openrouter:MODEL`, `groq:MODEL`, `lmstudio:MODEL` | other OpenAI-compatible providers |

### 6.1 Home menu

```
╭─ busride · Ride the Bus, solved ─────────────────────────────╮
│  Your game: Ride the Bus · payouts 1.80 2.30 3.20 12.00      │
│  Even playing perfectly, you get back about 96 of every 100  │
│  you bet.                                                    │
│                                                              │
│   1  Tutorial (start here!)                                  │
│   2  Play a few rounds, with a coach                         │
│   3  I'm playing now: what should I do?                      │
│   4  Show the cheat sheet                                    │
│   5  How fair is this game?                                  │
│   6  Arena: watch bots play, graded against perfect play     │
│   7  Train a learning AI and watch it improve                │
│   8  Choose a game                                           │
│   9  Settings: payouts, chips, coach, AI model               │
│  10  Pretend rounds: double-check the maths                  │
│  11  Record real rounds                                      │
│  12  Is the dealing fair?                                    │
│  13  Check my setup                                          │
│   q  Quit                                                    │
╰──────────────────────────────────────────────────────────────╯
Choose 1-13 (or q): _
```

After an action finishes, the screen shows `Next time, type: busride cheatsheet`, then returns
to the menu.

### 6.2 Play screen (illustrative)

The advisor panel already in the project, plus:
- a chips line;
- single-key choices, e.g. `[h] higher  [l] lower  [$] cash out`;
- coach feedback after each choice, e.g. "Good call: higher wins 44/51 (86%)", or "Cashing out
  was worth 2.30; continuing was worth 2.11 on average. You gave up 0.19."

At the end of a session: rounds, chips won or lost, your decisions graded against perfect play
(% optimal, chips given up), and your biggest mistake.

## 7. Agents

**The protocol.** Every agent implements `decide(observation) -> action`.

- **Observation:** the game, stage number and question, legal options (and whether cashing
  out is one), cards seen and the cards this guess is judged against, the current cash-out
  value, the ladder, a rules summary in plain words, and, when asked again, why the last answer
  was rejected.
- **Action:** a guess or `cash`, plus an optional stated `win_probability` (0–1), a short
  `reason`, the model's raw reply and metadata (model that answered, tokens, cost).
- **`reset(seed)`** starts each deal; agents that use randomness seed it from there.

**Baselines:** `optimal` (states the exact odds), `greedy` and `stop:K` (count cards, so they
state exact odds too, but stop badly), `random`, and `human` (you, typing moves at the arena
table; `play` has its own loop). A tie between equally likely guesses goes to the one the game
lists first, as in `fixed_plan`.

**LLM agents** (`agents/llm/`) share one prompt builder (`prompt.py`). Each decision is one
stateless request: a system prompt (the game's rules in plain words, card notation, how to
answer), two tools, and a user message with the situation (stage, cards in order with their
names, the cards the guess is judged against, cards left, the legal moves, what cashing out pays
now and after a win, and, on a retry, why the last answer was rejected). Names: `claude`,
`claude:MODEL`, `PROVIDER:MODEL`, each with an optional `@EFFORT`; `ai` means your default from
settings. The SDKs load only when an AI agent is used.

- **Claude** (official `anthropic` SDK, `client.beta.messages.create`):
  - Default model `claude-opus-5-5`, `output_config.effort` `medium` (`--effort` or `@high`
    changes it). Thinking can't be disabled on that model, so no `thinking` field is sent, and
    no sampling parameters. `max_tokens` 16,000.
  - Two strict tools, `make_guess(choice, win_probability, reason)` and `cash_out(reason)`,
    with `tool_choice` left at auto and an instruction (forced tool choice is a 400 there).
  - **Caching:** the tools and the system prompt (with `cache_control` on it) are
    byte-identical for every decision of a run; the `choice` enum lists every guess in the
    game, and the legal subset goes in the user message, checked client-side. The prefix is
    about 600 tokens, above the 512-token minimum. The leaderboard shows the cache share.
  - **Fallback:** `fallbacks: "default"` with beta `server-side-fallback-2026-07-01` on models
    that take it (on by default; `--no-fallback`). A decision answered by a fallback model
    (a `fallback_message` in `usage.iterations`) is recorded and counted on the leaderboard,
    and each attempt is priced at the rates of the model that ran it.
  - A `refusal` stop reason, no tool call, two tool calls or a cut-off answer is an invalid
    answer (below). No credentials, a bad key, an unknown model, a rejected request, a rate
    limit, a server error or no connection (caught most specific first) stop the run with a
    plain reason instead: they are not the model's fault, and the run resumes.
- **OpenAI-compatible** (official `openai` SDK, `chat.completions.create`):
  - Presets: `openai` (`OPENAI_API_KEY`, strict tool schemas), `deepseek`
    (`https://api.deepseek.com`, `DEEPSEEK_API_KEY`; `deepseek` alone means `deepseek-flash`,
    and `@EFFORT` also turns on its thinking mode), `ollama` (`OLLAMA_HOST`, default
    `http://localhost:11434`, plus `/v1`), `openrouter`, `groq`, `lmstudio`
    (`http://localhost:1234/v1`).
  - Free, so never asked about: local presets, OpenRouter `:free` models, and any model priced
    at 0 in the table. Cache hits are read from `prompt_tokens_details.cached_tokens` (OpenAI)
    or `prompt_cache_hit_tokens` (DeepSeek).
  - Function calling with `tool_choice: auto`. When the server says the model has no tools,
    the agent switches to a JSON reply (`{"move", "win_probability", "reason"}`) for the rest
    of the run; a JSON object in a plain reply is accepted either way.
  - `@EFFORT` becomes `reasoning_effort`.
- **Invalid output** (no move, unreadable, illegal move, a probability outside 0-1, refusal):
  the raw reply is logged and the agent is asked once more with the error. If it fails again,
  the decision is a forfeit: value 0, and the round ends. Every attempt's tokens and cost count.

**RL agents** (`agents/rl/`): tabular Q-learning and SARSA over the solver's canonical states,
in pure Python.

- **Training ground:** rounds are played on the exact game tree (`TreeGame`): in each state the
  moves are the tree's branches (in the labels of the state's representative cards) plus
  cash-out, and each outcome is drawn with its true card weight. Nothing is dealt or judged, so
  300,000 rounds take about a second, and the agent sees only payouts, never the counts or the
  solver's values.
- **Learning:** every move starts at the state's cash-out value (which the rules show any
  player), then keeps the running average of its targets (step 1/n). Q-learning's target is the
  best next value; SARSA's is the next move it actually makes. Exploration is epsilon-greedy,
  from 30% down to 2% over the first 60% of training.
- **Exact learning curve:** at each checkpoint (50 by default) `policy_value` evaluates the
  current greedy policy on the tree by backward induction, with no sampling. Regret is
  V*(root) - V(policy). Defaults: 70 rounds per state, at least 300,000.
- **Saved agents** are JSON in the data folder's `agents/`: the game and its fingerprint, the
  method, rounds, seed, exact value, the curve, the move for every state and the Q-table.
  `rl:NAME` plays only the game and payouts it learned.
- **Real cards:** a state's key gives the learned move in the representative's labels; the real
  guess with the same outcomes (`branch_of` / `same_move`: the same next states with the same
  card weights) is played, so a move learned for "two hearts seen" plays "two clubs seen".
- **Gymnasium** (`[rl]` extra): `BusRideEnv(game)`, observation `{stage, cards}` (cards 1..52,
  0 for not dealt), one discrete action per move in the game plus cash, `info["action_mask"]`,
  reward = payout - 1 when the round ends; an illegal move ends the round as a forfeit.

## 8. Exact solver

- **Backward induction** over every state the game can reach:

  ```
  V(s) = max( cash value of s,  max over guesses g of  Σ_c P(c | s) · [g wins on c] · V(s + c) )
  ```

  - A push contributes `P × cash value`.
  - Reveal stages are chance nodes: no action, no cash-out.
  - With `forced_first_bet`, the first guess cannot be declined.
- **Ladder mapping:** returns are indexed by *guessing* stages survived. Reveal stages do not
  move the ladder.
- **Projected-cell state key:** each seen card is reduced to what the remaining stages can use:
  its rank if a rank stage remains, else its suit if a suit stage remains, else its colour.
  - Key = (stage, ranks of cards referenced later, per-cell counts).
  - The counts are canonicalized under the symmetries the remaining stages allow: 24 suit
    permutations, 8 colour-preserving ones, or a red↔black swap.
  - With `with_replacement`, the counts are dropped.
  - Keys store ranks, not ace values, so ace `either` stays exact.
- **Speed:** the tree is built over distinct cells (one representative card plus the summed
  weight), not all 52 cards. The tree depends only on the rules, not the ladder, so it is
  cached; re-solving for a new ladder takes milliseconds.
- **State budget:** 250,000 states by default. Bigger games get a plain message, and the
  arena falls back to lazy solves rooted at the actual state (§9.3).
- **Exported views:**
  - `decide(state)`: the counts and expected value of every guess, plus cash vs continue.
  - Survival odds per stage.
  - `fixed_plan` values: the greedy plan that stops at stage K.
  - Odds analysis: fair vs offered payouts, break-even ladder, step and plan edges.

## 9. Arena

### 9.1 Format

- **Duplicate deals:**
  - Each deal's seed is `hash(run_seed, game, i)`, and the whole card sequence is drawn up front.
  - Every agent plays the same sequence; agents that stop early just see a prefix.
  - Agent randomness (`random`, exploration) uses a separate stream.
  - The deals are saved inside the run, so a run reproduces on any Python version.
- **Defaults:** seed 7; 2,000 deals for offline agents, 20 when a human or an LLM agent
  plays (`--deals N`).
- **Names:** `--name NAME`, else `GAME-seedS-N` (with a short rules hash added when another
  ladder already uses that name), so running the same command again resumes the same run.
  Runs live in the data folder's `runs/`.
- **Resume:** naming an existing run carries on with its own game, seed and deals; giving a
  different game, ladder, seed or deal count is refused as a different run. Finished
  (agent, deal) pairs are skipped.
- **The run file** is append-only JSONL:
  - a header line: game, rules (TOML text plus the exact ladder floats), a fingerprint of
    everything that shapes play and pay, the seed, and every deal's cards;
  - for each (agent, deal): one line per decision (cards seen, move, stated and exact win
    chance, Q, V, best move, regret, trivial, result, retries, rejected answers, raw reply,
    seconds), then one `deal` line (payout, how it ended).
  - A pair counts as done once its `deal` line is written, all in one write. A line cut short
    by a crash is skipped and the pair is played again.

### 9.2 Metrics (all exact unless stated)

For each decision at state s:
- Q(s, cash out) = the cash value; Q(s, guess) = that guess's expected value from the solver.
- V(s) = the maximum over legal actions.

| Metric | Definition | Why |
| --- | --- | --- |
| **Chips given up** (headline) | Σ regret, where regret = V(s) − Q(s, action) ≥ 0; mean per deal | Its expectation is exactly V*(root) − V^agent(root): decision quality without luck |
| Best moves | Share of decisions within 1e-9 of V, counting only decisions where the moves weren't all worth the same (red or black on a fresh deck doesn't count) | Easy-to-read accuracy |
| Calibration | Mean \|stated − exact\| win probability, plus a Brier score. A push counts as not-win | Does the model know the odds? |
| Risk profile | "Kept going when it should stop" vs "stopped when it should go on", counted when the move was worse by more than 2% of V | Reckless or timid? |
| Realized return | Mean payout per 1 staked, with a paired 95% CI against `optimal` | What actually happened (luck included) |
| Validity | Invalid outputs, retries, forfeits, fallback-served decisions | Robustness |
| Cost and speed | Tokens in and out, cache hits, $, seconds per decision | Practicality |

**On screen** everything is per 100 bet ("gives up 20.6"). The realized return is shown
without colour, because colour means expected value and this number includes luck.

**Self-tests:** the `optimal` agent's regret is exactly 0, and `greedy`'s mean regret matches
`rtp − fixed_plan().value`.

### 9.3 Games over the state budget

The arena solves exactly from the actual state each decision is made in (`solve_from`): the
part of the game that can follow it, under the same state budget. Solved parts are cached and
shared by every agent (the last 8 are kept), and so are the parts found too big. Decisions that
still don't fit get `regret = none`, and the leaderboard shows the coverage %. Win chances need
no solving, so calibration is always exact. Estimates never appear in the exact columns.

### 9.4 Cost guard

- **Prices** live in a dated table (US dollars per million tokens: input, output, cache read,
  cache write). The built-in one holds Anthropic's list prices on 2026-10-06; `busride arena
  prices` writes it to `prices.toml` in the config folder, where it can be corrected or extended
  (`[models."openai:MODEL"]`). Missing cache prices are taken as 0.1x (read) and 1.25x (write)
  the input price. A model not in the table has an unknown cost, shown as `?`, never as 0.
  Local models are free.
- **Before a paid run** (any agent that isn't local), in a terminal:
  1. a rough estimate with no calls (the prompt's size, a typical answer length per effort,
     every stage counted as a decision), and the question "Play 1 deal first, to measure the
     real cost?";
  2. that pilot deal is played and kept as deal 1 of the run;
  3. the measured cost per deal times the deals left, and "Play the rest?".

  An agent that already played in the run is estimated from what it spent there. Not in a
  terminal, a paid run refuses to start without `--yes`, before sending anything.
- `--max-cost DOLLARS` stops the run once this invocation's calls reach it (the run resumes).
- `--yes` skips the questions, for scripts.
- The run ends with "AI calls this time: $X", and the leaderboard has a Cost column.

### 9.5 Leaderboard

The offline baselines on the house ladder (`busride arena run`, real output):

```
RIDE THE BUS · arena   ride-the-bus-seed7-2000
Ride the Bus · 2,000 duplicate deals · seed 7 · payouts 1.80 2.30 3.20 12.00
Perfect play gets back 96.3 of every 100 bet, on average. Closest to it here:
stop:2, giving up 13.6.

            Gives  Best   Odds                   vs
#  Agent       up  move  error  Return      optimal
───────────────────────────────────────────────────
1  optimal    0.0  100%  exact    99.2            —
2  stop:2    13.6   51%  exact    85.2   -14.0 ±3.1
3  greedy    21.7   33%  exact    84.0  -15.2 ±12.7
4  random    41.1   33%      —    55.8   -43.4 ±7.7
```

Under the table: a plain-words legend for each column, then each agent's habits (too bold,
too timid, retries, forfeits, coverage). With AI agents a Cost column appears ($, `free` for a
local model, `?` for an unknown price), and an "AI models" section gives seconds and output
tokens per decision, the share of prompts read from the cache, and how many answers came from
a fallback model.

## 10. Play and coach

| Coach level | Before you choose | After you choose |
| --- | --- | --- |
| `off` | nothing | nothing |
| `hints` | odds bars for each option | nothing |
| `review` (default) | odds bars | whether it was the best move, and how much you gave up |
| `explain` | odds bars | a short plain-English explanation |

- **`explain`:** code fills in every number. A deterministic template writes the
  explanation. With `coach_ai` set (`busride settings --coach-ai claude`, or a local
  `ollama:MODEL`), that model rewords it at low effort; a rewording that adds or changes a
  number is thrown away, and any failure (no key, no server, a refusal) falls back to the
  template for the rest of the session. The model never computes odds itself.
- **Chips:** play starts with 1,000 fake chips and a stake of 10, both configurable. A session
  summary is shown at the end.

## 11. Simulation and verification

- **`simulate`:** a Monte Carlo of any agent. It deals and judges cards with its *own* code,
  reading only the game spec data and never importing the solver or stage logic. Results come
  with a 95% CI and a comparison against the exact answer.
- **`log` and `verify`** (Ride the Bus only):
  - Rounds are stored in SQLite.
  - Tests: a repeated card within a round, chi-square on rank and suit counts, a binomial test
    on the first card's colour, and repeats between consecutive rounds.
  - Multiple testing is Holm-corrected, and the report names the deck model that fits best.

## 12. Data and configuration

- **Folders** come from `platformdirs`:
  - config folder: `config.toml`, `prices.toml`, `games/*.toml`;
  - data folder: `runs/`, `agents/`, `rounds.db`.
- **Which game a command uses:** `--game NAME` (a built-in, one of your games, or a `.toml`
  path), else `--rules FILE`, else your current game from `config.toml` (default
  `ride-the-bus`), with your own payouts for it if you set any.
- **Which rounds file:** `--db FILE`, else `./rounds.db` if it exists, so older logs keep
  working, else `rounds.db` in your data folder.
- `busride doctor` shows the resolved paths. `BUSRIDE_HOME` keeps everything in one folder.
- **`config.toml`:** current game, ladder overrides, coach level, default chips and stake,
  `ai` (the default AI agent, `claude`), `effort` (Claude's, `medium`) and `coach_ai` (an AI
  agent that rewords the coach's explanations; empty for busride's own wording).
- **Keys:**
  - `ANTHROPIC_API_KEY` (or an `ant auth login` profile);
  - `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`;
  - `OLLAMA_HOST` (default `http://localhost:11434`).

  Keys come from the environment, or from a `.env` file (`KEY=VALUE` lines) in the current
  folder or the config folder, read at startup; a variable already set wins. `.env` is in
  `.gitignore`, and `.env.example` lists the names. Keys are never written to disk or printed
  by busride: `doctor` reports only whether each is set, and from which file.

## 13. Architecture

```
src/busride/
  engine/     cards, game (Stage, GameSpec, built-ins), rules (TOML), stages, solver, policy   (pure)
  sim.py      independent simulator: reads spec data only
  agents/     base (protocol), oracle (exact answers, cached), baselines,
              llm/{prompt, anthropic_agent, openai_agent, prices}, rl/{qlearning, agent, env}
  arena/      runner (duplicate deals), scoring, runs (JSONL, resume, leaderboard)
  coach/      explain (templates; LLM phrasing)
  stats/      verify tests
  store.py    rounds DB
  config.py   folders, settings, keys from env
  ui/         theme, fmt (the only number formatter), cards, bars, banner, screens, menu, play, arena, train
  cli.py      Typer app; no-args callback → home menu when attached to a terminal
```

**Dependency rules:**
- `engine/` and `stats/` do no input or output.
- `sim.py` never imports `engine.solver` or `engine.stages`.
- Only `cli.py` and `ui/` touch the terminal.
- LLM calls happen only in `agents/llm/` and `coach/`.

**Packages:**
- core: `typer`, `rich`, `scipy`, `platformdirs`, `anthropic`, `openai`;
- extra `[rl]`: `gymnasium`;
- dev: `pytest`, `hypothesis`, `ruff`, `mypy`.

**Commands:** `busride` (`bus` remains as an alias for one release).

## 14. Quality and testing

| Layer | Pass condition |
| --- | --- |
| Known values | Fresh deck, ace high, ties lose: survival 0.50000 · 0.36199 · 0.23771 · 0.06307 (±1e-5). Cards repeat: 0.35503 · 0.22417 · 0.05604. Fair-ladder RTP 1.146 ±0.002 |
| Key equivalence | The generic key reproduces the old hand-written key: equal value tables, exactly 329 states for Ride the Bus |
| Brute force | Per built-in: a full brute force on a reduced deck, plus sampled deep states on the full deck |
| Key soundness (Hypothesis) | Random specs of up to 4 stages: two prefixes with the same key have equal brute-force Q for every action |
| Properties | Win/lose/tie partition the deck; V ≥ cash value; raising a payout never lowers the RTP; RTP scales with the ladder (1,000 random rule sets) |
| Simulation | Each built-in's simulated RTP lies within 4 SE of exact, with a fixed seed |
| Arena | Optimal regret = 0; greedy regret ≈ rtp − fixed_plan; resume skips completed pairs; mocked LLM transports cover tool calls, JSON fallback, invalid output, refusal and the cost guard |
| RL | Tabular Q-learning reaches under 1% regret on Ride the Bus within a fixed episode budget, with a fixed seed |
| Screens | Snapshots at width 80 with no truncation; `--plain` has no escape codes; `--ascii` is pure ASCII; the menu prints help (not a prompt) when not in a terminal |
| Live (optional) | One Claude decision (`BUSRIDE_LIVE=1`, about $0.02) and one Ollama decision (`BUSRIDE_LIVE_OLLAMA=MODEL`, free); skipped otherwise |

**Performance budgets:**
- Ride the Bus full solve < 1 s; every built-in < 2 s.
- An advise answer < 100 ms.
- `verify` on 5,000 rounds < 2 s.
- An offline arena run of 2,000 deals × 4 baselines < 10 s.

## 15. Risks and honesty limits

| Risk | Mitigation |
| --- | --- |
| LLM results vary run to run | Report CIs. Store every raw response. Never claim determinism |
| A fallback model answers instead of the one being tested | Recorded per decision, flagged on the leaderboard, `--no-fallback` |
| Cost surprises | Pilot estimate, confirmation, `--max-cost`, cheap defaults (20 deals) |
| Too much for beginners | The menu is the front door. Advanced options live behind `--help` and Settings. A tutorial |
| Scope creep | `log`/`verify` stay Ride-the-Bus-only. No web UI in v0.2. Milestones ship one at a time |
| Gambling framing | Fake chips only. Every odds screen states the house edge plainly. No real-money features |
