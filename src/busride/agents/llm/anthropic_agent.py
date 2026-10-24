"""Claude as an arena agent, through the official `anthropic` SDK.

Each decision is one request: the cached system prompt and tools, then the situation. The model
answers with one of two strict tools. Thinking can't be turned off on claude-opus-5-5, so the
effort level (default medium) sets how hard it thinks. A request the safety classifiers decline
is re-run server-side on Anthropic's recommended fallback model (`fallbacks: "default"`), and
each decision records which model actually answered.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from busride.agents.base import Action, AgentError, AgentUnavailable, Observation
from busride.agents.llm import prompt
from busride.agents.llm.prices import PriceTable, load_prices
from busride.engine.game import GameSpec

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # the beta that goes with fallbacks="default"
FALLBACK_MODELS = frozenset(
    {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5"}
)
MAX_TOKENS = 16_000  # thinking counts against this; a decision rarely needs a tenth of it
TIMEOUT = 300.0
# For the estimate before any call: output tokens a decision typically takes at each effort
# (thinking included), the question's length, and the tool instructions the API adds.
TYPICAL_OUTPUT = {"low": 400, "medium": 1200, "high": 3000, "xhigh": 6000, "max": 10000}
QUESTION = 150
PREAMBLE = 300
NO_KEY = (
    "no Claude credentials found: set ANTHROPIC_API_KEY (from platform.claude.com) or run "
    "`ant auth login`"
)


def make_client() -> Any:
    """The SDK client (tests replace this)."""
    try:
        return anthropic.Anthropic(timeout=TIMEOUT)
    except anthropic.CredentialsError:
        raise AgentUnavailable(NO_KEY) from None


def agent_name(model: str, effort: str) -> str:
    return f"claude:{model}" + ("" if effort == DEFAULT_EFFORT else f"@{effort}")


class ClaudeAgent:
    paid = True

    def __init__(
        self,
        rules: GameSpec,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
        fallback: bool = True,
        client: Any = None,
        prices: PriceTable | None = None,
    ) -> None:
        if effort not in EFFORTS:
            raise ValueError(f"effort must be one of {', '.join(EFFORTS)}, not {effort!r}")
        self.rules = rules
        self.model = model
        self.effort = effort
        self.fallback = fallback and model in FALLBACK_MODELS
        self.name = agent_name(model, effort)
        self.prices = prices or load_prices()
        self._client = client
        # built once, so every request starts with the same bytes and the prefix caches
        self.system: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": prompt.system_prompt(rules),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        self.tools: list[dict[str, Any]] = [
            {"name": name, "description": text, "strict": True, "input_schema": schema}
            for name, text, schema in prompt.tool_schemas(rules)
        ]

    def reset(self, seed: str) -> None:
        pass

    def rough_cost(self, decisions: int) -> float | None:
        """A guess at the cost before any call, from the prompt's size and a typical answer
        length at this effort. The first request writes the cache; the rest read it."""
        price = self.prices.get(self.model)
        if price is None or decisions <= 0:
            return None if price is None else 0.0
        prefix = (len(self.system[0]["text"]) + len(json.dumps(self.tools))) // 4 + PREAMBLE
        out = TYPICAL_OUTPUT[self.effort]
        first = price.cost(QUESTION, out, 0, prefix)
        return first + (decisions - 1) * price.cost(QUESTION, out, prefix, 0)

    def request(self, obs: Observation) -> dict[str, Any]:
        """The keyword arguments for one decision's request."""
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": self.system,
            "tools": self.tools,
            "messages": [{"role": "user", "content": prompt.user_message(obs, self.rules)}],
            "output_config": {"effort": self.effort},
        }
        if self.fallback:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def decide(self, obs: Observation) -> Action:
        if self._client is None:
            self._client = make_client()
        response = self._send(self.request(obs))
        meta = self._meta(response)
        if response.stop_reason == "refusal":
            details = response.stop_details
            category = getattr(details, "category", None) if details is not None else None
            why = f" ({category})" if category else ""
            raise AgentError(f"the model declined to answer{why}", meta=meta)
        calls = [b for b in response.content if b.type == "tool_use"]
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        if not calls:
            cut = " (it ran out of tokens)" if response.stop_reason == "max_tokens" else ""
            raise AgentError(
                f"no tool call{cut}: answer with {prompt.GUESS_TOOL} or {prompt.CASH_TOOL}",
                raw=text[:500] or None,
                meta=meta,
            )
        if len(calls) > 1:
            raise AgentError("more than one tool call: make exactly one", meta=meta)
        call = calls[0]
        raw = json.dumps({"tool": call.name, "input": call.input}, ensure_ascii=False)
        return prompt.to_action(call.name, call.input, raw, meta)

    def complete(self, system: str, user: str) -> str | None:
        """A plain text answer (for the coach's wording), at low effort. None if declined."""
        if self._client is None:
            self._client = make_client()
        response = self._send(
            {
                "model": self.model,
                "max_tokens": 2000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "output_config": {"effort": "low"},
            }
        )
        if response.stop_reason == "refusal":
            return None
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    def _send(self, params: dict[str, Any]) -> Any:
        """One request, with every failure that isn't the model's answer turned into a plain
        reason to stop (most specific first)."""
        try:
            return self._client.beta.messages.create(**params)
        except anthropic.AuthenticationError:
            raise AgentUnavailable(
                "Claude rejected the API key: check ANTHROPIC_API_KEY (or run `ant auth login`)"
            ) from None
        except anthropic.PermissionDeniedError as exc:
            raise AgentUnavailable(f"this key can't use {self.model}: {exc.message}") from None
        except anthropic.NotFoundError:
            raise AgentUnavailable(
                f"there is no Claude model called {self.model!r} (try {DEFAULT_MODEL})"
            ) from None
        except anthropic.BadRequestError as exc:
            raise AgentUnavailable(f"Claude rejected the request: {exc.message}") from None
        except anthropic.RateLimitError:
            raise AgentUnavailable(
                "Claude's rate limit was reached: wait a minute, then run the same command again"
            ) from None
        except anthropic.APIStatusError as exc:
            raise AgentUnavailable(
                f"the Claude API answered with an error ({exc.status_code}): {exc.message}"
            ) from None
        except anthropic.APIConnectionError:
            raise AgentUnavailable(
                "can't reach the Claude API: check your internet connection"
            ) from None
        except anthropic.CredentialsError:
            raise AgentUnavailable(NO_KEY) from None

    def _meta(self, response: Any) -> dict[str, Any]:
        """Tokens, cost and the model that answered. With a fallback, each attempt is priced at
        the rates of the model that ran it."""
        usage = response.usage
        attempts = list(getattr(usage, "iterations", None) or []) or [usage]
        meta: dict[str, Any] = {
            "requests": 1,
            "model": response.model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        cost: float | None = 0.0
        for a in attempts:
            tokens = (
                a.input_tokens or 0,
                a.output_tokens or 0,
                getattr(a, "cache_read_input_tokens", 0) or 0,
                getattr(a, "cache_creation_input_tokens", 0) or 0,
            )
            for key, n in zip(
                ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"),
                tokens,
                strict=True,
            ):
                meta[key] += n
            price = self.prices.get(getattr(a, "model", None) or response.model)
            if price is None or cost is None:
                cost = None
            else:
                cost += price.cost(*tokens)
        if cost is None:
            meta["cost_unknown"] = 1
        else:
            meta["cost"] = cost
        served = any(getattr(a, "type", "") == "fallback_message" for a in attempts)
        if served and response.stop_reason != "refusal":
            meta["fallback"] = 1
        return meta
