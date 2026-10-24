# busride: the complete beginner's guide

This guide assumes you have **never** used busride, and maybe never used a terminal. It explains
every feature, every screen and every number, with the maths behind them in plain words. If a
word is new, it is explained where it first appears, and again in the [Glossary](#19-glossary).

**How to read it**

- First time? Read Parts 1 to 5 in order. Part 5 is a 20-minute tour of every feature.
- Want to play or get advice? Parts 6 and 7.
- Curious about AI? Parts 8 (the arena), 9 (AI models like Claude and DeepSeek) and 10 (an AI
  that teaches itself).
- Playing a real game for money? Part 13 first, and Part 1.3.

## Contents

1. [What busride is](#1-what-busride-is)
2. [Five ideas you need first](#2-five-ideas-you-need-first)
3. [Getting set up](#3-getting-set-up)
4. [The home menu](#4-the-home-menu)
5. [A 20-minute tour](#5-a-20-minute-tour)
6. [Playing with a coach](#6-playing-with-a-coach)
7. [Advice, the cheat sheet and the odds](#7-advice-the-cheat-sheet-and-the-odds)
8. [The arena: agents graded against perfect play](#8-the-arena)
9. [AI models in the arena](#9-ai-models-in-the-arena)
10. [A learning AI that teaches itself](#10-a-learning-ai-that-teaches-itself)
11. [Games: built-in, yours, and making one](#11-games)
12. [Settings, and where your files live](#12-settings-and-where-your-files-live)
13. [Using it with a real game](#13-using-it-with-a-real-game)
14. [The statistics behind `busride verify`](#14-the-statistics-behind-busride-verify)
15. [Under the hood](#15-under-the-hood)
16. [Running the project's own tests](#16-running-the-projects-own-tests)
17. [Problems and fixes](#17-problems-and-fixes)
18. [Quick summary card](#18-quick-summary-card)
19. [Glossary](#19-glossary)

---

## 1. What busride is

### 1.1 The game in 60 seconds

**Ride the Bus** is a card game played at parties with a real deck, and found in many apps. You
place a bet (your **stake**), and the game asks up to four questions, one card at a time:

| Stage | Question | You win if... |
| --- | --- | --- |
| 1 | **Red or black?** | the first card has the colour you picked |
| 2 | **Higher or lower?** | the second card is higher or lower than the first, as you said |
| 3 | **Inside or outside?** | the third card falls between the first two cards (inside) or outside them |
| 4 | **Which suit?** | the fourth card has the suit you picked (hearts, diamonds, clubs or spades) |

Each stage you win, the amount you could take home grows. You can then **cash out** (take it
and stop) or **continue**. Lose a stage and the round's bet is gone.

### 1.2 What busride does

The game is small enough that a computer can work out **perfect play exactly**: for every
possible situation, the move that gets back the most on average. busride uses that answer key
in three ways, all in your terminal:

1. **Learn and play.** Play with fake chips while a coach grades every move, ask what to do with
   the cards in front of you, or print the whole strategy as a cheat sheet.
2. **Test AI models.** Bots and AI models (Claude, DeepSeek, GPT, or a free model on your own
   computer) play the same cards, and every decision is graded against perfect play.
3. **Train a learning AI.** Watch a program that starts knowing nothing teach itself the game,
   while busride measures exactly how close it gets.

| Command | In one sentence |
| --- | --- |
| `busride` | Opens the home menu: start here |
| `busride tutorial` | A 2-minute guided intro |
| `busride play` | Play rounds with fake chips and a coach |
| `busride advise` | The best move for the cards on the table |
| `busride cheatsheet` | The whole best strategy on one screen |
| `busride odds` | How fair the game is, stage by stage |
| `busride games` | See, switch or make games |
| `busride settings` | Your game, payouts, chips, coach and AI model |
| `busride arena ...` | Bots and AI models play the same deals, graded exactly |
| `busride train` | Train a learning AI and watch it improve |
| `busride simulate` | Play pretend rounds to double-check the maths |
| `busride log` / `verify` | Record real rounds, then test whether the dealing looks fair |
| `busride doctor` | Check that everything is set up |

### 1.3 What it cannot do

- **It cannot make you win.** If a game pays less than it should, you lose in the long run
  whatever you do. busride finds the way to lose **as little as possible**, and says how much.
- **It does not touch the game.** It doesn't read any app's memory or press keys for you. It
  only knows the rules you give it and the cards you type.
- **It cannot prove a game is fair.** It can catch some kinds of unfair dealing (Part 14).
- **It uses fake chips.** There are no real-money features.

---

## 2. Five ideas you need first

These five ideas explain every number busride prints.

### Idea 1: probability is "good cards ÷ cards left"

A normal deck has **52 cards**: 13 **ranks** (2, 3, 4, 5, 6, 7, 8, 9, 10, J, Q, K, A) in each of
4 **suits** (♥ hearts and ♦ diamonds are red; ♣ clubs and ♠ spades are black).

Say the first two cards were **7♥** and **Q♠**, and you must guess inside or outside. There are
**50** cards left. The cards **inside** (strictly between 7 and Q) are 8, 9, 10 and J: 4 ranks ×
4 suits = **16 cards**. busride writes this as `16/50`, which is **32%**. It always shows both, so
you can check its maths by counting.

### Idea 2: a "return" counts your stake too

Payouts are a **return per 1 bet, stake included**.

- Return **1.90** (or `1.90x`) means: bet 100, get back 190 in total (your 100 plus 90 profit).
- Return **1.00** means you get exactly your bet back.
- Return **0** means you lost your bet.

The **ladder** is the list of returns, one for cashing out after each stage. Classic Ride the
Bus in busride uses `1.8, 2.3, 3.2, 12` (the "house" ladder).

### Idea 3: expected value is "what a decision is worth on average"

Imagine making the same decision thousands of times. The **expected value** (EV) is the average
return you'd get.

**Worked example.** Your cards are 7♥ and Q♠ and you've won 2 stages, so cashing out now pays
**2.30**. If you guess **outside**, you win with 28 of the 50 cards (56%), and winning lets you
cash out at stage 3 for **3.20**:

```
continue  =  56% × 3.20  =  1.79
cash out  =  2.30 (guaranteed)
```

2.30 is more than 1.79, so the best move is **cash out**. (When more stages come after, the
value of continuing also counts the best moves you'd make later. busride does that for you.)

### Idea 4: a "fair" multiplier is 1 ÷ probability

A bet is **fair** if, on average, you get back exactly what you put in. Red or black wins **50%**
of the time, so a fair payout is 1 ÷ 0.5 = **2.00x**. If the game pays **1.80x**, you get back
0.5 × 1.80 = **0.90** per 1 bet on average: that bet loses 10%, the game's **edge** on it.

### Idea 5: RTP and house edge

**RTP** (return to player) is the average you get back per 1 bet over many rounds. busride
reports it for **perfect play**.

- RTP **0.963** means you get back about 96 of every 100 you bet: a **house edge** of 3.7%.
- RTP **1.05** would be a 5% **player edge**.

"On average" matters. In a short session luck dominates. The edge shows over hundreds of rounds.

---

## 3. Getting set up

### 3.1 What a terminal is

A **terminal** is a window where you type commands instead of clicking. busride has no buttons:
you type, it answers.

- **Windows:** press the Windows key, type `PowerShell` and press Enter.
- **macOS:** open **Terminal** (in Applications, Utilities).
- **Linux:** open your terminal app.

The line ending in `>` or `$` is the **prompt**: the terminal waits for you there.

### 3.2 Install uv (once)

busride is a Python program. **uv** is a small tool that runs Python projects with everything
they need, so you don't have to install Python yourself.

- **Windows (PowerShell):**
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS or Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

Close the terminal and open a new one afterwards, so it finds `uv`.

### 3.3 Get busride and start it

With git: `git clone https://github.com/kkdoestech/busride.git`. Without git: download the ZIP from
[the project page](https://github.com/kkdoestech/busride) (the green **Code** button, then **Download ZIP**) and unzip it. Then go into the folder and start it:

```
cd busride
uv run busride
```

`cd` means "change directory" (a directory is a folder). The first `uv run` spends a minute
downloading what busride needs; after that it starts in a second or two. You should see the
**home menu** (Part 4).

### 3.4 How commands are built

```
uv run busride odds --game hi-lo-5
└─┬──┘ └──┬──┘ └┬─┘ └──────┬─────┘
  │       │     │          └─ an option (a "flag"): changes how the command behaves
  │       │     └──────────── the command: what you want to do
  │       └────────────────── the program
  └────────────────────────── uv starts it with everything it needs
```

- Options start with `--`. Some take a value, like `--ladder 1.9,2.5,3.8,14` (no spaces inside).
- Every command has `--help`, which lists its options: `uv run busride play --help`.
- `--plain` turns colours off; `--ascii` uses plain letters instead of card symbols. Use them if
  your screen shows boxes or is hard to read.

**Optional, a shorter command:** run `uv tool install .` once in the busride folder. After that,
type `busride` from any folder, without `uv run`. This guide writes `busride ...` for short.

### 3.5 Handy keys

| Key | What it does |
| --- | --- |
| **Up arrow** | Brings back your last command (press again for older ones) |
| **Ctrl + C** | Stops whatever is running |
| **Enter** on a question | Keeps the value shown in `( )` brackets |
| **Tab** | Completes a file or folder name you've started typing |
| `cls` (Windows) or `clear` | Clears the screen |

### 3.6 Check your setup

```
busride doctor
```

It checks the program, your terminal, your settings, your game, and (only whether they are
there, never their values) your AI keys. Each line says what to do if something is off.

---

## 4. The home menu

Type `busride` with nothing after it:

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
```

Type a number and press Enter. When the action finishes, busride shows the command that does
the same thing directly (`Next time, type: busride cheatsheet`), then takes you back to the menu.
`q` (or Ctrl + C) leaves.

---

## 5. A 20-minute tour

Nothing here costs money or changes anything important. Type each command and look at the
screen; Parts 6 to 12 explain what you see.

1. **`busride tutorial`**: four short pages: the game, how to read advice, an example round,
   where to go next. Press Enter between pages.
2. **`busride play --rounds 3`**: play three rounds with fake chips. Type `1` or `2` to choose,
   `$` to cash out. The coach tells you after each move whether it was the best one.
3. **`busride advise 9h Ks`**: you've seen the nine of hearts, then the king of spades. What
   now? (Part 7.1.)
4. **`busride cheatsheet`**: the whole strategy on one screen.
5. **`busride odds`**: how fair the game is, and where it takes its edge.
6. **`busride games`**: the four built-in games. Try `busride odds --game colour-run-5`.
7. **`busride arena run`**: four bots play 2,000 identical deals in about a second; the
   leaderboard ranks them by how much they give up against perfect play (Part 8).
8. **`busride arena replay --deal 2`**: one of those deals, move by move.
9. **`busride train`**: an AI teaches itself the game in about a second (Part 10).
10. **`busride arena run --agents optimal,rl:q-ride-the-bus,greedy`**: the AI you just trained,
    in the arena.

---

## 6. Playing with a coach

```
busride play
```

You start with 1,000 fake chips; each round costs 10 (change them in Settings, or with `--chips`
and `--stake`). Press Enter to deal, then for each stage:

- type the **number** of your choice, a letter (`r`/`b`, `h`/`l`, `i`/`o`, or a suit letter),
  or the word itself;
- `$` to **cash out** (before your first guess, if the game allows it, `$` walks away);
- `q` to stop. Your stake must be played first if the game says so.

**The table** shows your cards, and (with the coach on) one bar per guess with its chance, like
`HIGHER ████████░░ 84.3%  43/51`. These are odds, not advice: the coach tells you afterwards
whether you picked the best move.

**Coach levels** (`--coach`, or Settings):

| Level | Before you choose | After you choose |
| --- | --- | --- |
| `off` | nothing | nothing |
| `hints` | the odds bars | nothing |
| `review` (default) | the odds bars | whether it was the best move, and how much you gave up |
| `explain` | the odds bars | a short explanation in plain words |

**What "gave up" means.** Every move has a value: what it is worth on average if you play
perfectly afterwards. The best move's value minus your move's value is what you **gave up**. It
measures the decision, not the luck: you can make the best move and still lose the round.

**The session summary** at the end shows your chips, how often you made the best move, what you
gave up in total, and how much was luck: "Your play: worth -12.40 chips on average; luck added
30.00" means your decisions were worth -12.40 and the cards gave you 30 more.

---

## 7. Advice, the cheat sheet and the odds

### 7.1 `busride advise`: what should I do now?

```
busride advise 9h Ks
```

Type the cards seen so far, in order. Cards are written rank then suit: `9h` = nine of hearts,
`Ks` = king of spades, `10d` (or `Td`) = ten of diamonds, `As` = ace of spades. Suits are `h d c
s`.

The screen shows, for each guess, its chance (as a bar, a percentage and a count like `43/51`),
then a box comparing **cash out** with **continue** and a verdict. Colours mean: **green** = the
better play by more than 2%, **amber** = within 2% (a coin flip either way), **red** = losing.

**Live mode:** `busride advise` with no cards asks you to type each card as it appears. `n` starts
a new round, `u` undoes the last card, `q` quits.

### 7.2 `busride cheatsheet`: the whole strategy

One table per stage:

- **Stage 1:** red or black is a coin flip on a fresh deck.
- **Stage 2:** a strip by the first card: "after a 2-7 say higher; 9-A say lower; after an 8,
  cash out" (exact wording depends on your ladder).
- **Stage 3:** a grid by the two cards, with I (inside), O (outside) or $ (cash out).
- **Stage 4:** by the suits seen: pick a suit you haven't seen, or cash out.

A `*` marks a cell where the best play depends on cards you saw earlier; the most likely case is
shown. Keep it open in a second window while you play.

### 7.3 `busride odds`: how fair is the game?

The banner says the house edge (or player edge) with perfect play, in plain words: "Even
playing perfectly, you get back about 96 of every 100 you bet." Then, per stage:

| Column | Means |
| --- | --- |
| **Win** | Chance to win this stage, if you got here |
| **Survive** | Chance to get through this stage from the start of the round |
| **Fair** | The payout at which always playing to this stage breaks even: 1 ÷ survive |
| **Offered** | What the game pays |
| **Break even** | Your ladder scaled so perfect play exactly breaks even |
| **Step edge** | What letting your winnings ride through this one stage costs you |
| **Plan edge** | What always playing to this stage and then cashing out costs you |

The stage with the biggest step edge is where the game takes most of its edge.

**Try another ladder** without changing anything: `busride odds --ladder 2,3,4,20` (or the
presets `house`, `classic`, `fair`). The "classic" ladder 2x/3x/4x/20x looks fair and isn't: it
gives perfect play a 31% *player* edge.

---

## 8. The arena

### 8.1 The idea

Usually you can't tell a good player from a lucky one without thousands of rounds. Ride the Bus
is different: busride knows the exact value of every move, so it can grade every **decision**,
not just the results. In the arena:

- **Every agent plays the same deals** (the same card sequences: "duplicate deals"). An agent
  that cashes out early simply never sees the later cards.
- **Every decision is graded:** the best move's value minus the move's value, as in Part 6. The
  sum per deal is what that agent **gives up** against perfect play, and luck doesn't enter it.

```
busride arena run
```

plays four built-in agents on 2,000 deals in about a second:

| Agent | Plays |
| --- | --- |
| `optimal` | perfect play: the answer key |
| `greedy` | always the guess most likely to win, and never cashes out |
| `stop:K` | the most likely guess, cashing out after stage K (`stop:2`) |
| `random` | any legal move at random |
| `human` | you |
| `rl:NAME` | an AI you trained (Part 10) |
| `claude`, `deepseek`, `ollama:MODEL`... | AI models (Part 9) |

Choose with `--agents optimal,greedy,stop:2` and the number of deals with `--deals 500`.
`busride arena agents` lists them all.

### 8.2 Reading the leaderboard

```
            Gives  Best   Odds                   vs
#  Agent       up  move  error  Return      optimal
1  optimal    0.0  100%  exact    99.2            —
2  stop:2    13.6   51%  exact    85.2   -14.0 ±3.1
3  greedy    21.7   33%  exact    84.0  -15.2 ±12.7
4  random    41.1   33%      —    55.8   -43.4 ±7.7
```

| Column | Means |
| --- | --- |
| **Gives up** | Chips lost to imperfect play, per 100 bet, on average. Luck doesn't count. 0 is perfect |
| **Best move** | How often it made the best move, counting only choices that mattered (red or black on a fresh deck is a free choice, so it doesn't count) |
| **Odds error** | How far the win chances it *said* were from the true ones (`exact`, or in percentage points; `—` if it never says) |
| **Return** | What it actually got back per 100 bet on these deals, luck included (no colour, because it is mostly luck) |
| **vs optimal** | The gap to perfect play on the same deals, with a "give or take" range (95%) |
| **Cost** | With AI models: what their calls cost |

Under the table, **Habits** counts moves that were clearly too bold (kept going when cashing
out was better by more than 2%) or too timid (the reverse).

Notice greedy's Return can beat its Gives up: on these 2,000 deals it was lucky. That's why
the ranking uses Gives up.

### 8.3 Replays and saved runs

- `busride arena replay --deal 2`: one deal, every agent's moves, the best move beside each,
  and what each mistake cost. `--agent NAME --worst` lists that agent's 10 costliest decisions.
- `busride arena runs`: your saved runs. `busride arena leaderboard NAME` shows one again.
- Runs are saved as you go. **Running the same command again carries on** where it stopped,
  and only new agents play. `--name NAME` gives a run a name, so you can add agents to it later:
  `busride arena run --name test1 --agents greedy`.

### 8.4 You in the arena

```
busride arena run --agents human,optimal,greedy --deals 10
```

You play 10 deals (new cards each time), then see where you rank. Type the number of your
choice, `$` to cash out, `q` to stop (finished deals are kept).

---

## 9. AI models in the arena

### 9.1 What happens

For each decision, busride sends the model the rules in plain words, the cards on the table and
the legal moves, and the model answers with a move, its own estimate of the win chance, and a
short reason. busride never lets it compute the grade: the exact answer key does that. An
unusable answer gets one retry with the reason; a second failure counts as a **forfeit** (the
deal is lost).

### 9.2 Which models

| Name | Model | Needs |
| --- | --- | --- |
| `ollama:MODEL` | a model on your own computer through [Ollama](https://ollama.com) | Ollama running; free |
| `lmstudio:MODEL` | a model in LM Studio | LM Studio's server on; free |
| `deepseek` | DeepSeek (deepseek-flash); `deepseek:deepseek-v4-pro` for the bigger one | `DEEPSEEK_API_KEY`; costs a few cents |
| `claude` | Claude (claude-opus-5-5); `claude:claude-sonnet-5-5` and others | `ANTHROPIC_API_KEY` or `ant auth login` |
| `openai:MODEL` | an OpenAI model | `OPENAI_API_KEY` |
| `openrouter:MODEL` | any model on OpenRouter; models ending in `:free` cost nothing | `OPENROUTER_API_KEY` |
| `groq:MODEL` | a model on Groq | `GROQ_API_KEY` |

Add `@EFFORT` to make a model think harder or less: `claude@high`, `deepseek@high` (efforts:
low, medium, high, and for Claude also xhigh and max).

**A free start:** install Ollama, run `ollama pull qwen3:4b-instruct` (or `llama3.1:8b`), then

```
busride arena run --agents optimal,ollama:qwen3:4b-instruct --deals 10
```

### 9.3 API keys, safely

An **API key** is a password that lets a program use a paid AI service. Keep it secret.

- **The easy way:** copy `.env.example` to `.env` in the busride folder and fill in the keys
  you have, one per line: `DEEPSEEK_API_KEY=sk-...`. busride reads it when it starts. You can
  also put `.env` in your settings folder (Part 12), so it works from any folder.
- **Or** set it in the terminal for one session: `$env:DEEPSEEK_API_KEY = "sk-..."` (PowerShell)
  or `export DEEPSEEK_API_KEY=sk-...` (macOS/Linux).
- `.env` is listed in `.gitignore`, so git won't upload it. **Never paste a key into a chat, an
  issue or a screenshot.** If one leaks, delete it on the provider's website and make a new one.
- `busride doctor` tells you which keys it found and where from, never their values.

### 9.4 What it costs, and staying in control

Before a paid model plays, busride shows a rough estimate, asks "Play 1 deal first, to measure
the real cost?", plays that one deal, shows the measured cost per deal and asks "Play the rest?".

- `--max-cost 1` stops the run once the calls have cost $1 (run the same command later to carry
  on).
- `--yes` skips the questions (for scripts). Without a terminal, a paid run refuses to start
  without `--yes`.
- `busride arena prices` shows the price table (US dollars per million **tokens**, the pieces of
  text models read and write) and saves an editable copy. A model that isn't in the table shows
  `?`: add it to get estimates; give a free-tier model price 0.

For scale: DeepSeek-flash played 10 deals for about $0.03 in testing.

### 9.5 Reading an AI's results

The leaderboard adds a **Cost** column and an "AI models" section: seconds and output tokens per
decision, and how much of each prompt came from the provider's **cache** (repeated text billed
cheaply). Use `busride arena replay --agent deepseek:deepseek-flash --worst` to read the
model's reasons for its worst moves: you'll often see exactly where its maths went wrong.

Small samples are noisy: 10 deals is a first look, 50 or more a fair comparison. And AI models
vary from run to run, so a rerun can score differently.

**If Claude declines a request** (its safety filters can refuse, rarely), Anthropic can let a
fallback model answer instead; the leaderboard counts how often that happened, and
`--no-fallback` turns it off.

---

## 10. A learning AI that teaches itself

```
busride train
```

The agent starts knowing **nothing**. It plays practice rounds, sees only what each round paid,
and keeps a running average of how good each move is in each situation. That's
**reinforcement learning**: learning from rewards, by trial and error.

- **Exploring:** at first, 30% of its moves are random tries, so it discovers moves it would
  otherwise never try; this fades to 2% as it learns.
- **The learning curve** shows what it gives up against perfect play as it practises. Every
  point is computed **exactly** from the moves it currently prefers, so the curve has no luck in
  it.
- On Ride the Bus it gets within about 0.2 chips per 100 bet of perfect play in 100,000 rounds,
  which takes well under a second.

**Two methods** (`--method`):

| Method | Learns... | So it... |
| --- | --- | --- |
| `q-learning` (default) | what each move is worth if it played perfectly afterwards | heads straight for perfect play |
| `sarsa` | what each move is worth the way it actually plays, random tries included | plays a little more carefully |

Options: `--episodes 1000000` (more practice), `--seed 7` (a different, repeatable learner),
`--name mine`, `--game hi-lo-5` (a bigger game needs more practice: try 2,000,000).

The agent is saved; play it in the arena as `rl:NAME`:

```
busride arena run --agents optimal,rl:q-ride-the-bus,greedy
```

It only plays the game and payouts it learned. For your own experiments with other learning
libraries, busride includes a **Gymnasium** environment (`uv sync --extra rl`, then
`from busride.agents.rl.env import BusRideEnv`).

---

## 11. Games

### 11.1 Built-in games

| Game | What you do | Perfect play returns |
| --- | --- | --- |
| `ride-the-bus` | Red or black, higher or lower, inside or outside, then the suit | 96.3% |
| `hi-lo-5` | One card is shown, then five higher-or-lower calls, each against the card before | 96.2% |
| `in-between` | Two cards are shown; bet whether the third lands between them | 97.5% |
| `colour-run-5` | Five red-or-black calls in a row (remembering the colours seen helps) | 97.5% |

- `busride games` lists them (yours too); `busride games hi-lo-5` shows one game's rules.
- `busride games use hi-lo-5` makes it **your game**: every command uses it until you switch.
- `--game NAME` on any command tries a game for that one command.

### 11.2 Making a game

`busride games new` asks you, step by step: the name, the stages (in order, from `colour`,
`higher_lower`, `inside_outside`, `suit`, `reveal` for a card shown without a guess), the deck,
the ace and tie rules, and the payouts. It saves the game and can make it yours.

A game is a small text file (TOML), so you can also copy one from `examples/` and edit it:
`busride odds --game examples/short-deck.toml`. See `examples/README.md` for what each one
shows, and Part 13.3 for every setting.

---

## 12. Settings, and where your files live

```
busride settings
```

shows your settings and asks what to change. Or set one directly:

| Command | Sets |
| --- | --- |
| `busride settings --game hi-lo-5` | your game |
| `busride settings --ladder 1.9,2.5,3.8,14` | your payouts for your game (`--reset-payouts` goes back) |
| `busride settings --chips 500 --stake 5` | play money |
| `busride settings --coach explain` | how much the coach says |
| `busride settings --ai deepseek` | the AI model that `--agents ai` means |
| `busride settings --effort high` | how hard Claude thinks by default |
| `busride settings --coach-ai deepseek` | an AI that rewords the coach's explanations (`off` to stop); busride still computes every number and throws away any rewording that changes one |

**Where things are saved.** busride keeps your things in your user folder, so it works from any
folder:

| What | Where |
| --- | --- |
| Settings (`config.toml`), prices (`prices.toml`), your games (`games/`), optionally `.env` | the settings folder |
| Logged rounds (`rounds.db`), arena runs (`runs/`), trained agents (`agents/`) | the data folder |

On Windows both are `C:\Users\<you>\AppData\Local\busride`; on macOS
`~/Library/Application Support/busride`; on Linux `~/.config/busride` and
`~/.local/share/busride`. `busride doctor` prints the exact paths. To keep everything in one
folder instead (a USB stick, say), set `BUSRIDE_HOME` to that folder.

---

## 13. Using it with a real game

### 13.1 Collect the rules (about 30 minutes, once)

busride is only as good as the rules you give it. Open the Ride the Bus game you play and use
the **smallest bet** while you find these out:

**The four payouts (most important).** After you win a stage, the game shows what cashing out
now would pay. If it shows a multiplier (`x1.9`), write it down. If it shows money, divide by your
bet: bet 100, cash-out 190, so 190 ÷ 100 = **1.9**. Stage 4 is rare (about 1 round in 16), so be
patient, or copy a payout table if the game has one.

| What to find out | How | Answers |
| --- | --- | --- |
| **Tie on higher/lower** | Wait for the 2nd card to match the 1st's rank (7 then 7). Did you lose, did the round end paying what you had, or did you carry on? | `lose` / `push` / `win` |
| **Tie on inside/outside** | Wait for the 3rd card to match one of the first two (4, J, then a J) | `lose` / `push` / `win` |
| **Ace** | 1st card an ace, then a 5: did "lower" win (ace high) or "higher" (ace low)? | `high` / `low` / `either` |
| **Deck** | You can't see it. Keep `fresh_52`; `busride verify` checks it later | `fresh_52` |
| **Version** | The app's version, or a name for your house rules | e.g. `0.3.6` |

### 13.2 Put the rules in

- **The wizard:** `busride init` asks one question at a time (Enter keeps the value in brackets)
  and saves your game as `my-ride-the-bus`, then makes it your game.
- **One command:** `busride init --yes --ladder 1.9,2.5,3.8,14 --game-version 0.3.6` (add `--ace
  low`, `--tie-higher-lower push` and so on as needed).
- **Just the payouts:** `busride settings --ladder 1.9,2.5,3.8,14`.

Then `busride odds` tells you what that game costs you with perfect play.

### 13.3 A rules file, line by line

```toml
[game]
name = "Ride the Bus"            # a label
game_version = "0.3.6"            # which version these rules are for
captured_on = "2026-10-24"        # when you collected them
min_stake = 0                     # smallest bet; 0 = not recorded
max_stake = 0                     # largest bet; 0 = not recorded
timeout = "unknown"               # what a card that times out does

[deck]
model = "fresh_52"                # fresh_52 | with_replacement | shoe
decks = 1                         # only for "shoe"
ace = "high"                      # high | low | either

[ties]
higher_lower = "lose"             # lose | push | win
range_edge = "lose"               # the same, for a card equal to either end of the range

[payout]
return_after_stage = [1.9, 2.5, 3.8, 14.0]
```

| Deck model | Means | Same card twice in a round? |
| --- | --- | --- |
| `fresh_52` | A new shuffled deck every round | No |
| `with_replacement` | Each card drawn from a full deck, as if put back | Yes (about 11% of 4-card rounds) |
| `shoe` | Several decks mixed together (`decks = 6` is 312 cards) | Yes, less often |

A **push** ends the round and pays what cashing out would have. **Inside** means strictly
between: with 4 and J, 5 to 10 are inside; a 4 or a J is a tie on the edge. Other games use
`[[stage]]` tables (one per card) and `ladder = [...]`: see `examples/first-card-high-low.toml`.
A misspelt name gets a warning (`Unknown key 'ties.higer_lower' is ignored`); an impossible
value is refused with the line to fix.

### 13.4 Your routine

- **Before playing:** `busride odds`, then `busride cheatsheet` in a window you keep open.
- **While playing:** use the cheat sheet, or `busride advise` live mode when you have time.
- **After each round:** record it in a second terminal with `busride log --stake 100` (your real
  bet). Type the cards in order and what you were paid: `9h Ks 3d 380`; `9h Ks x4.2` for a
  multiple of the stake; `2c 5h` for a loss. `u` undoes, `s 20` changes the stake.
- **Every 30 rounds or so:** `busride verify` (Part 14).
- **When the game updates:** collect the payouts again; they may change.

If `verify` says the best fit is "cards can repeat", the game doesn't deal from a fresh deck:
run `busride init --yes --deck with_replacement` and check `busride odds` again.

`log` and `verify` work with Ride the Bus only.

---

## 14. The statistics behind `busride verify`

### 14.1 The p-value: "how surprising is this, if the game is fair?"

Imagine the game is perfectly fair. The **p-value** is the chance that pure luck would give a
result **at least as unusual** as yours. p = 0.60 is completely normal; p = 0.03 happens by luck
only 3% of the time (suspicious); p < 0.001 is very suspicious. busride flags a test when p is
below 0.05 (change it with `--alpha`). A small p-value doesn't prove cheating, and a large one
doesn't prove fairness.

### 14.2 The Holm correction: "many tests, more chances of a false alarm"

Running five tests makes it more likely that *one* of them looks odd by luck. The **Holm
correction** raises the p-values to make up for it, so the chance of *any* false alarm stays
around 5%. That's why the column says **p (Holm)**.

### 14.3 Confidence intervals: "the range where the truth probably is"

`49.8% red (95% CI 45.4% to 54.2%)` means 49.8% of your first cards were red, and the true rate is
very probably between 45.4% and 54.2%. If the expected 50% is inside, all is consistent. More
rounds give a narrower range. (The arena's "give or take" is the same idea.)

### 14.4 Chi-square: "are all the counts about even?"

For ranks there are 13 counts. The **chi-square** score adds up how far each is from what it
should be; a fair game gives about 12 (the degrees of freedom). busride turns the score into a
p-value for you.

### 14.5 Why tests can't prove a game is fair

These tests catch a biased colour, a missing rank, cards repeating. A game could still deal
worse cards when you bet big, or after a winning streak, with cards that look normal. So busride
says "no evidence of bias", never "the game is fair".

---

## 15. Under the hood

### 15.1 Perfect play by working backwards

busride solves a game **exactly**: no guessing. It works **backwards from the last stage**, like
solving a maze from the exit:

1. **Stage 4:** for every possible set of 3 cards, the best suit is one seen least. Continuing
   is worth (chance) × (stage 4 payout); compare with cashing out and keep the bigger.
2. **Stage 3:** for every pair of cards, try inside and outside. Each card that could come leads
   to a stage 4 situation whose value is known from step 1; the average is the guess's value.
3. **Stages 2 and 1:** the same, using values already worked out.

```
value(now) = max( cash out now ,  best guess of  Σ over next cards  P(card) × value(after that card) )
```

The value at the very start is the **RTP of perfect play**. This is **backward induction**.

**Why it's fast:** many situations are really the same. Which suit you saw first doesn't matter
for the later stages, only how many of each, up to swapping suits. busride keeps only what the
remaining stages can still use, so Ride the Bus has just **329** different situations and solves
in a few hundredths of a second.

### 15.2 A second, independent check

`busride simulate` deals pretend cards and judges every guess with **its own separate code**,
never the solver's. When the two agree (the ✓ on its screen), both are very probably right, like
checking a sum by doing it another way.

### 15.3 How the arena grades

For each decision, busride computes the exact value of every legal move. The best value minus
the chosen move's value is the **regret** of that decision. Add the regrets of a deal and
average over deals: that is **Gives up**. Mathematically, its average equals perfect play's
return minus the agent's, so it measures skill without luck, and duplicate deals make the
comparison between agents fairer still.

### 15.4 How the learning AI learns

It practises on the same 329 situations the solver uses, drawing each card with its true chance,
so practice is fast and faithful. In each situation it keeps an average of what each move led to
(that table is the "Q" in Q-learning). Its curve is exact because busride evaluates the moves it
prefers with the same backward induction as above. Playing real cards, it finds the real move
that leads to the same outcomes as the one it learned.

### 15.5 The files

```
busride/
├── README.md, GUIDE.md        the overview and this guide
├── CONTRIBUTING.md, LICENSE   for people who want to help; the MIT licence
├── .env.example               the API key names (copy to .env; never commit .env)
├── docs/SPEC.md, ROADMAP.md   the full specification, and what's done and next
├── docs/demo/                 pictures of the screens
├── examples/                  example game files
├── pyproject.toml, uv.lock    the project's settings and exact library versions
├── src/busride/
│   ├── engine/                the maths: cards, games, rules files, stages, the exact solver, policies
│   ├── sim.py                 the independent simulator
│   ├── play.py                fake-chip play, every decision graded
│   ├── coach/                 the coach's words (and the optional AI rewording)
│   ├── agents/                bots, the oracle, AI models (llm/), learning agents (rl/)
│   ├── arena/                 duplicate deals, saved runs, the leaderboard numbers
│   ├── stats/                 the verify tests
│   ├── ui/                    how every screen looks
│   ├── config.py, store.py    your folders and settings; the rounds database
│   └── cli.py                 the commands you type
├── tests/                     about 400 automatic checks
└── scripts/                   the demo recorder and a quick maths check
```

| Library | Used for |
| --- | --- |
| **Typer** | the commands and their `--help` |
| **Rich** | colours, boxes, tables, live screens |
| **SciPy** | the statistics in `verify` |
| **anthropic**, **openai** | talking to AI models (only when you use them) |
| **platformdirs** | finding your settings and data folders |
| **Gymnasium** (optional) | the environment for your own learning experiments |

---

## 16. Running the project's own tests

```
uv run pytest
```

About 400 tests, in about a minute and a half. Dots are passes, `F` a failure, `s` a skipped
test (the live AI tests, which only run if you ask, because they cost money). Some highlights:

| Test file | Checks |
| --- | --- |
| `test_known_values.py` | The exact survival chances: all 4 stages = 0.06307 |
| `test_policy.py`, `test_builtin_games.py` | The fast solver against slow brute force, for every game |
| `test_sim.py` | The simulator against the exact maths |
| `test_arena.py` | Perfect play gives up exactly 0; greedy gives up what the formula says |
| `test_llm.py` | AI agents against fake servers: nothing is sent anywhere |
| `test_rl.py` | The learning AI gets within 1% of perfect play |
| `test_screens.py` | Every screen at 80 characters wide, with `--plain` and `--ascii` |

Developers also run `uv run ruff check src tests` (style) and `uv run mypy` (types).

---

## 17. Problems and fixes

| You see | What it means | What to do |
| --- | --- | --- |
| `uv : The term 'uv' is not recognized` | The terminal can't find uv | Install it (Part 3.2), then open a new terminal |
| `error: there is no game called ...` | A typo in a game name | `busride games` lists them |
| Every money value is `0.00` | No payouts entered | `busride settings --ladder ...` (Part 13.2) |
| `! The ladder goes down at some stage` | A later stage pays less: probably a typo | Check your numbers |
| `'Kx' has no suit: end it with h, d, c or s` | A typo in a card | Retype it, e.g. `Ks` |
| `'1h' has no valid rank` | There's no rank 1 | Use `A` for an ace |
| `... is already on the table this round` | The same card twice, which a fresh deck can't do | Check the cards, or `u` to undo |
| `need data` in `verify` | Not enough rounds for that test yet | Keep logging |
| `... cost(s) money for every decision ... add --yes` | A paid AI outside a terminal | Run it in a terminal to see the estimate, or add `--yes --max-cost 1` |
| `no Claude credentials found` / `deepseek needs an API key` | No key set | Part 9.3 |
| `rejected the API key` | The key is wrong or was deleted | Make a new one on the provider's site |
| `can't reach Ollama ... is it running?` | Ollama isn't started | Start the Ollama app, or `ollama serve` |
| `ollama has no model called ...` | That model isn't downloaded | `ollama pull NAME` |
| `rate limit was reached` | Too many requests for now | Wait a minute and run the same command again: it carries on |
| `... holds a different run` | That run name has other settings | Use another `--name`, or the same game, seed and deals |
| `rl:NAME learned ... with other rules or payouts` | A trained AI only plays its own game | `busride train` again with the same `--game`/`--ladder` |
| Boxes or `?` instead of ♥ ♦ ♣ ♠ | Your font lacks the symbols | Add `--ascii` |
| Colours hard to read | | Add `--plain` |
| A command won't stop | | Ctrl + C |

---

## 18. Quick summary card

```
busride                              the menu (start here)
busride tutorial                     a 2-minute intro
busride play                         fake chips, a coach grades every move
busride advise 9h Ks                 what to do with these cards (busride advise: live mode)
busride cheatsheet                   the whole strategy on one screen
busride odds                         how fair is the game, and where does it take its edge?
busride games use hi-lo-5            switch game (busride games new: make one)
busride arena run                    bots on 2,000 identical deals, graded exactly
busride arena run --agents optimal,deepseek --deals 20     an AI model (asks before spending)
busride arena replay --deal 2        one deal, move by move
busride train                        an AI teaches itself the game
busride doctor                       is everything set up?

add --ladder 1.9,2.5,3.8,14   to try other payouts      add --plain   for no colours
add --game NAME               to try another game       add --ascii   for plain characters
add --help                    for every option
```

---

## 19. Glossary

| Word | Meaning |
| --- | --- |
| **Ace high / low / either** | Whether an ace counts above the king, below the 2, or whichever helps you |
| **Agent** | Anything that plays in the arena: a bot, an AI model, a trained AI, or you |
| **API key** | A secret password that lets a program use a paid AI service (Part 9.3) |
| **Arena** | Where agents play the same deals and are graded against perfect play (Part 8) |
| **Backward induction** | Solving a step-by-step game from the last step back (Part 15.1) |
| **Cache (AI)** | Text an AI provider has seen before and bills cheaply when it's sent again |
| **Cash out** | Stop and take what you've won so far |
| **Chi-square** | A score for how uneven a set of counts is (Part 14.4) |
| **Confidence interval** | A range where the true value very probably lies (Part 14.3) |
| **Duplicate deals** | Every agent gets the same card sequences, so luck is shared |
| **Edge** | How much one side wins on average: house edge (the game's) or player edge (yours) |
| **Effort** | How hard an AI model thinks before answering: more is slower and costs more |
| **Episode** | One practice round of a learning AI |
| **Expected value (EV)** | The average result of a decision if repeated many times (Idea 3) |
| **Exploration** | A learning AI's random tries, so it discovers moves it would otherwise skip |
| **Fair multiplier** | The payout at which a bet breaks even on average: 1 ÷ chance (Idea 4) |
| **Fallback model** | A model that answers instead when Claude declines a request |
| **Forfeit** | An AI answer still unusable after one retry: the deal is lost |
| **Gives up** | What a player loses to imperfect play, per 100 bet, luck aside |
| **Greedy** | Always picking the guess most likely to win right now |
| **Holm correction** | An adjustment to p-values when several tests run together (Part 14.2) |
| **Ladder** | The returns for cashing out after each stage |
| **LLM** | Large language model: an AI like Claude, DeepSeek or GPT |
| **Odds error** | How far an agent's stated win chances were from the true ones |
| **p-value** | How surprising a result would be if the game were fair (Part 14.1) |
| **Policy** | A complete strategy: what to do in every situation |
| **Push** | A tie that ends the round and pays what you had |
| **Q-learning / SARSA** | Two ways a learning AI updates what it thinks moves are worth (Part 10) |
| **Regret** | The best move's value minus the chosen move's value |
| **Reinforcement learning** | Learning from rewards by trial and error |
| **Return** | Total payout per 1 bet, including the bet (Idea 2) |
| **RTP** | Return to player: average payout per 1 bet over many rounds (Idea 5) |
| **Seed** | A number that fixes the randomness, so a run can be repeated exactly |
| **Shoe** | Several decks mixed together |
| **Solver** | The part of busride that works out perfect play exactly |
| **Stake** | Your bet for one round |
| **Terminal** | The text window where you type commands |
| **Token** | A piece of text (about 4 letters) that AI models read and write, and charge by |
| **TOML** | The simple `name = value` text format of game and settings files |
| **uv** | The tool that runs busride with the right libraries |
