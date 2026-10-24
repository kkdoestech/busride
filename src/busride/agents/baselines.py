"""The agents that need no AI model: the answer key, a few simple plans, chance, and you."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from busride.agents.base import CASH, Action, Agent, Observation
from busride.agents.oracle import Odds, Oracle, oracle_for
from busride.engine.game import GameSpec
from busride.ui import fmt

if TYPE_CHECKING:
    from busride.agents.llm import LLMOptions

AI_PROVIDERS = ("claude", "openai", "deepseek", "ollama", "openrouter", "groq", "lmstudio")

# What `busride arena agents` lists: (name, what it plays)
BASELINES = (
    ("optimal", "the exact solver: perfect play, and the answer key for everyone else"),
    ("greedy", "always the guess most likely to win, and never cashes out"),
    ("stop:K", "the guess most likely to win, cashing out after stage K (try stop:2)"),
    ("random", "any legal move, picked at random"),
    ("human", "you: type your moves, on the same deals as everyone else"),
    ("rl:NAME", "an agent you trained with busride train (it learned from rounds it played)"),
)

# AI models (busride.agents.llm), listed here so listing them doesn't load the SDKs
AI_AGENTS = (
    ("claude", "Claude (claude-opus-5-5) through the Anthropic API (ANTHROPIC_API_KEY)"),
    ("claude:MODEL", "another Claude model, like claude:claude-sonnet-5-5"),
    ("claude@EFFORT", "how hard Claude thinks: low, medium (default), high, xhigh, max"),
    ("ollama:MODEL", "a model on your computer through Ollama, free (like ollama:llama3.1:8b)"),
    ("lmstudio:MODEL", "a model on your computer through LM Studio, free"),
    ("deepseek", "DeepSeek (deepseek-flash) through its API (DEEPSEEK_API_KEY)"),
    ("deepseek:MODEL", "another DeepSeek model, like deepseek:deepseek-v4-pro"),
    ("openai:MODEL", "an OpenAI model (OPENAI_API_KEY)"),
    ("openrouter:MODEL", "any model on OpenRouter (OPENROUTER_API_KEY); :free ones cost nothing"),
    ("groq:MODEL", "a model on Groq (GROQ_API_KEY)"),
    ("ai", "your default AI model, set with busride settings --ai"),
)


def likeliest(odds: tuple[Odds, ...]) -> Odds:
    """The guess most likely to win; on a tie, the one the game lists first."""
    best = odds[0]
    for o in odds[1:]:
        if o.wins > best.wins:
            best = o
    return best


class Optimal:
    """Plays the solver's move and states the exact odds of its guess."""

    name = "optimal"

    def __init__(self, oracle: Oracle) -> None:
        self.oracle = oracle

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        d = self.oracle.decision(obs.seen)
        if d is None:  # too big to solve from here: fall back on the likeliest guess
            o = likeliest(self.oracle.odds(obs.seen))
            return Action(o.guess, o.chance, "no exact answer here; the likeliest guess")
        per = "per 100 bet"
        if obs.can_cash_out and not d.should_continue:
            return Action(
                CASH,
                reason=f"stopping is worth {fmt.hundred(d.cash_out)} {per}, going on "
                f"{fmt.hundred(d.continue_value)}",
            )
        best = d.best
        if not obs.can_cash_out:
            why = f"the best guess, worth {fmt.hundred(best.ev)} {per}"
        else:
            why = f"worth {fmt.hundred(best.ev)} {per}, stopping {fmt.hundred(d.cash_out)}"
        return Action(best.guess, best.survive_chance, f"{best.guess}: {why}")


class Greedy:
    """The guess most likely to win, every time; with `stop_after`, cash out after that stage."""

    def __init__(self, oracle: Oracle, stop_after: int | None = None) -> None:
        self.oracle = oracle
        self.stop_after = stop_after
        self.name = "greedy" if stop_after is None else f"stop:{stop_after}"

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        if self.stop_after is not None and obs.stage > self.stop_after and obs.can_cash_out:
            return Action(CASH)
        o = likeliest(self.oracle.odds(obs.seen))
        return Action(o.guess, o.chance)


class RandomAgent:
    """Any legal move, at random, from its own random stream (never the deal's)."""

    name = "random"

    def __init__(self) -> None:
        self.rng = random.Random(0)

    def reset(self, seed: str) -> None:
        self.rng = random.Random(seed)

    def decide(self, obs: Observation) -> Action:
        return Action(self.rng.choice(obs.legal))


class Human:
    """You. `ask` shows the table and returns your move (the CLI supplies it)."""

    name = "human"

    def __init__(self, ask: Callable[[Observation], Action]) -> None:
        self._ask = ask

    def reset(self, seed: str) -> None:
        pass

    def decide(self, obs: Observation) -> Action:
        return self._ask(obs)


def agent_names_help() -> str:
    return (
        "optimal, greedy, stop:K (like stop:2), random, human, rl:NAME (a trained agent), or an "
        "AI model such as claude or ollama:llama3.1:8b (see busride arena agents)"
    )


def is_ai(word: str) -> bool:
    return word == "ai" or word.split(":", 1)[0].split("@", 1)[0] in AI_PROVIDERS


def make_agent(
    name: str,
    rules: GameSpec,
    oracle: Oracle | None = None,
    ask: Callable[[Observation], Action] | None = None,
    llm: LLMOptions | None = None,
) -> Agent:
    """An agent from its name, as typed after --agents. Raises ValueError for unknown names."""
    word = name.strip().lower()
    if is_ai(word):
        from busride.agents.llm import make_llm_agent  # the SDKs load only when needed

        return make_llm_agent(name, rules, llm)
    if word.startswith("rl:"):
        from busride.agents.rl.agent import load_agent

        return load_agent(name.strip()[3:], rules)
    oracle = oracle or oracle_for(rules)
    if word == "optimal":
        return Optimal(oracle)
    if word == "greedy":
        return Greedy(oracle)
    if word == "random":
        return RandomAgent()
    if word == "human":
        if ask is None:
            raise ValueError("the human agent needs someone at the keyboard")
        return Human(ask)
    m = re.fullmatch(r"stop:(\d+)", word)
    if m:
        k, low = int(m.group(1)), 1 if rules.forced_first_bet else 0
        if not low <= k <= rules.guess_count:
            raise ValueError(
                f"{word}: {rules.name} has {rules.guess_count} guessing stages, so K goes from "
                f"{low} to {rules.guess_count}"
            )
        return Greedy(oracle, k)
    raise ValueError(f"there is no agent called {name!r}: use {agent_names_help()}")
