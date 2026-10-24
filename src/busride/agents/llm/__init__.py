"""AI models as arena agents: Claude through the Anthropic API, and anything that speaks the
OpenAI chat API (OpenAI, a local Ollama or LM Studio, OpenRouter, Groq).

Agent names: `claude` (claude-opus-5-5), `claude:MODEL`, `PROVIDER:MODEL`, each with an optional
`@EFFORT` (`claude@high`). `ai` means the default model from your settings.
"""

from __future__ import annotations

from dataclasses import dataclass

from busride.agents.base import Agent
from busride.agents.llm.anthropic_agent import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS, ClaudeAgent
from busride.agents.llm.openai_agent import PRESETS, OpenAICompatAgent
from busride.agents.llm.prices import PriceTable
from busride.engine.game import GameSpec

PROVIDERS = ("claude", *PRESETS)
OPENAI_EFFORTS = ("minimal", "low", "medium", "high")


@dataclass(frozen=True)
class LLMOptions:
    effort: str = DEFAULT_EFFORT  # Claude's effort when the name doesn't give one
    fallback: bool = True  # Claude: re-run declined requests on a fallback model
    default_ai: str = "claude"  # what `ai` means
    prices: PriceTable | None = None


def make_llm_agent(name: str, rules: GameSpec, options: LLMOptions | None = None) -> Agent:
    """An AI agent from its name. Raises ValueError with what to type instead."""
    options = options or LLMOptions()
    text = name.strip()
    if text.lower() == "ai":
        text = options.default_ai.strip()
        if text.lower().split(":", 1)[0].split("@", 1)[0] not in PROVIDERS:
            raise ValueError(f"your default AI model {text!r} isn't one: see busride settings")
    effort = None
    base, at, suffix = text.rpartition("@")
    if at and suffix.lower() in (*EFFORTS, *OPENAI_EFFORTS):
        text, effort = base, suffix.lower()
    provider, _, model = text.partition(":")
    provider = provider.lower()
    if provider == "claude":
        effort = effort or options.effort
        if effort not in EFFORTS:
            raise ValueError(f"Claude's effort is one of {', '.join(EFFORTS)}, not {effort!r}")
        return ClaudeAgent(
            rules, model or DEFAULT_MODEL, effort, options.fallback, prices=options.prices
        )
    if provider not in PRESETS:
        raise ValueError(f"unknown AI provider {provider!r}: use one of {', '.join(PROVIDERS)}")
    model = model or (PRESETS[provider].default_model or "")
    if not model:
        raise ValueError(f"say which model: {provider}:MODEL (like ollama:llama3.1:8b)")
    if effort is not None and effort not in OPENAI_EFFORTS:
        raise ValueError(f"the effort for {provider} is one of {', '.join(OPENAI_EFFORTS)}")
    return OpenAICompatAgent(provider, model, rules, effort, prices=options.prices)
