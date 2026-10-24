# Example games

Each file is a complete game for busride. Use one for a single command with `--game`, or make
it your game:

```sh
uv run busride odds --game examples/short-deck.toml        # how fair is it?
uv run busride games use examples/short-deck.toml          # make it your game
uv run busride arena run --game examples/two-deck-shoe.toml
uv run busride train --game examples/first-card-high-low.toml
```

| File | What it shows | Perfect play returns |
| --- | --- | --- |
| `ride-the-bus-rules.toml` | Every setting of classic Ride the Bus, with comments: copy it and fill in the game you play | 96.3% |
| `short-deck.toml` | A smaller deck: `ranks = [6, ..., 14]` (36 cards, sixes to aces) | 96.1% |
| `two-deck-shoe.toml` | `model = "shoe"` with `decks = 2`, and ties that push instead of losing | 96.1% |
| `first-card-high-low.toml` | `[[stage]]` tables: a card shown, then three calls all against card 1 (`against = 1`), aces high or low | 96.1% |
| `in-between-walkaway.toml` | `forced_first_bet = false`: you may walk away after seeing the two cards | 139.9% |

The last one is there for its lesson: when you may leave after seeing the cards, perfect play
bets only on wide gaps and can't lose on average. Real tables make you bet first.

The payouts of the first four were chosen so that perfect play gets back about 96 of every 100
bet, like a real house game. To make your own game, run `busride games new` (it asks the
questions and writes a file like these), or copy one and edit it. Section 5 of
[`docs/SPEC.md`](../docs/SPEC.md) describes every setting.

## A saved arena run

`arena-example.jsonl` is the real run shown in the main README: seven agents on 30 deals,
including DeepSeek-flash and a local model, with every decision, the models' stated odds and
their reasons. No API key is needed to look through it:

```sh
uv run busride arena leaderboard examples/arena-example.jsonl
uv run busride arena replay examples/arena-example.jsonl --deal 2
uv run busride arena replay examples/arena-example.jsonl --agent ollama:qwen3:4b-instruct --worst
```
