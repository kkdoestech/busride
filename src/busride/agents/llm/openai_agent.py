"""Models behind an OpenAI-compatible API, through the official `openai` SDK: OpenAI itself,
DeepSeek, a local Ollama or LM Studio, OpenRouter and Groq.

The model answers with a tool call where it can. A model without tool calling (many small local
ones) is asked for a JSON reply instead; busride switches to that by itself the first time the
server says the model has no tools.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import openai

from busride import config
from busride.agents.base import Action, AgentError, AgentUnavailable, Observation
from busride.agents.llm import prompt
from busride.agents.llm.prices import PriceTable, load_prices
from busride.engine.game import GameSpec

TIMEOUT = 300.0  # a local model may need a while to load
TYPICAL_OUTPUT = 600  # output tokens per decision, for the estimate before any call


@dataclass(frozen=True)
class Preset:
    name: str
    base_url: str | None  # None: the SDK's default (api.openai.com)
    key_env: str | None  # None: no key needed (a local server)
    local: bool
    strict: bool = False  # send strict tool schemas (only where the server is known to take them)
    default_model: str | None = None  # what `deepseek` alone means


PRESETS = {
    "openai": Preset("openai", None, "OPENAI_API_KEY", local=False, strict=True),
    "deepseek": Preset(
        "deepseek",
        "https://api.deepseek.com",
        "DEEPSEEK_API_KEY",
        False,
        default_model="deepseek-flash",
    ),
    "ollama": Preset("ollama", None, None, local=True),  # base URL from OLLAMA_HOST, at use
    "openrouter": Preset("openrouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", False),
    "groq": Preset("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", False),
    "lmstudio": Preset("lmstudio", "http://localhost:1234/v1", None, local=True),
}


def base_url(preset: Preset) -> str | None:
    return f"{config.ollama_url()}/v1" if preset.name == "ollama" else preset.base_url


def make_client(preset: Preset) -> Any:
    """The SDK client for a provider (tests replace this)."""
    key = os.environ.get(preset.key_env, "") if preset.key_env else preset.name
    if not key:
        raise AgentUnavailable(f"{preset.name} needs an API key: set {preset.key_env}")
    return openai.OpenAI(api_key=key, base_url=base_url(preset), timeout=TIMEOUT)


def _no_tools(exc: openai.BadRequestError) -> bool:
    text = str(exc.message).lower()
    return "tool" in text or "function" in text


class OpenAICompatAgent:
    def __init__(
        self,
        provider: str,
        model: str,
        rules: GameSpec,
        effort: str | None = None,
        json_reply: bool = False,
        client: Any = None,
        prices: PriceTable | None = None,
    ) -> None:
        self.preset = PRESETS[provider]
        self.model = model
        self.rules = rules
        self.effort = effort
        self.json_reply = json_reply
        self.name = f"{provider}:{model}" + (f"@{effort}" if effort else "")
        self.prices = prices or load_prices()
        price = self.prices.get(f"{provider}:{model}")
        # free: on your computer, an OpenRouter ":free" model, or priced at 0 in your table
        self.free = (
            self.preset.local
            or (provider == "openrouter" and model.endswith(":free"))
            or (price is not None and price.input == 0 and price.output == 0)
        )
        self.paid = not self.free
        self._client = client
        self.tools: list[dict[str, Any]] = []
        for name, text, schema in prompt.tool_schemas(rules):
            function: dict[str, Any] = {"name": name, "description": text, "parameters": schema}
            if self.preset.strict:
                function["strict"] = True
            self.tools.append({"type": "function", "function": function})

    def reset(self, seed: str) -> None:
        pass

    def rough_cost(self, decisions: int) -> float | None:
        """A guess at the cost before any call (0 for a free model)."""
        if self.free:
            return 0.0
        price = self.prices.get(f"{self.preset.name}:{self.model}")
        if price is None:
            return None
        prompt_tokens = len(prompt.system_prompt(self.rules)) // 4 + 400
        return decisions * price.cost(prompt_tokens, TYPICAL_OUTPUT)

    def request(self, obs: Observation) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system_prompt(self.rules, self.json_reply)},
                {"role": "user", "content": prompt.user_message(obs, self.rules)},
            ],
        }
        if not self.json_reply:
            params["tools"] = self.tools
            params["tool_choice"] = "auto"
        if self.effort:
            params["reasoning_effort"] = self.effort
            if self.preset.name == "deepseek":  # DeepSeek thinks only when asked to
                params["extra_body"] = {"thinking": {"type": "enabled"}}
        return params

    def decide(self, obs: Observation) -> Action:
        if self._client is None:
            self._client = make_client(self.preset)
        try:
            response = self._send(self.request(obs))
        except _ToolsUnsupported:
            self.json_reply = True  # for the rest of the run
            response = self._send(self.request(obs))
        meta = self._meta(response)
        if not response.choices:
            raise AgentError("the reply was empty", meta=meta)
        choice = response.choices[0]
        message = choice.message
        text = (message.content or "").strip()
        calls = list(message.tool_calls or [])
        if choice.finish_reason == "content_filter" or getattr(message, "refusal", None):
            raise AgentError("the model declined to answer", raw=text[:500] or None, meta=meta)
        if len(calls) > 1:
            raise AgentError("more than one tool call: make exactly one", meta=meta)
        if calls:
            fn = calls[0].function
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                raise AgentError(
                    "the tool arguments were not valid JSON", raw=fn.arguments, meta=meta
                ) from None
            raw = json.dumps({"tool": fn.name, "input": args}, ensure_ascii=False)
            return prompt.to_action(fn.name, args, raw, meta)
        if text:  # no tool call: a JSON reply (asked for, or volunteered) still counts
            return prompt.from_json_reply(text, meta)
        raise AgentError("the reply had no move in it", meta=meta)

    def complete(self, system: str, user: str) -> str | None:
        """A plain text answer (for the coach's wording). None if empty or declined."""
        if self._client is None:
            self._client = make_client(self.preset)
        response = self._send(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        )
        if not response.choices:
            return None
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            return None
        return (message.content or "").strip() or None

    def _send(self, params: dict[str, Any]) -> Any:
        where = base_url(self.preset) or "api.openai.com"
        try:
            return self._client.chat.completions.create(**params)
        except openai.AuthenticationError:
            raise AgentUnavailable(
                f"{self.preset.name} rejected the API key: check {self.preset.key_env}"
            ) from None
        except openai.PermissionDeniedError as exc:
            raise AgentUnavailable(f"this key can't use {self.model}: {exc.message}") from None
        except openai.NotFoundError:
            hint = f" (download it with `ollama pull {self.model}`)" if self._ollama else ""
            raise AgentUnavailable(
                f"{self.preset.name} has no model called {self.model!r}{hint}"
            ) from None
        except openai.BadRequestError as exc:
            if "tools" in params and _no_tools(exc):
                raise _ToolsUnsupported from None
            raise AgentUnavailable(
                f"{self.preset.name} rejected the request: {exc.message}"
            ) from None
        except openai.RateLimitError:
            raise AgentUnavailable(
                f"{self.preset.name}'s rate limit was reached: wait, then run the same "
                "command again"
            ) from None
        except openai.APIStatusError as exc:
            raise AgentUnavailable(
                f"{self.preset.name} answered with an error ({exc.status_code}): {exc.message}"
            ) from None
        except openai.APIConnectionError:
            if self._ollama:
                raise AgentUnavailable(
                    f"can't reach Ollama at {config.ollama_url()}: is it running? (start it with "
                    "`ollama serve`)"
                ) from None
            raise AgentUnavailable(f"can't reach {self.preset.name} at {where}") from None

    @property
    def _ollama(self) -> bool:
        return self.preset.name == "ollama"

    def _meta(self, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        # OpenAI reports cache hits in the details; DeepSeek in prompt_cache_hit_tokens
        cached = getattr(details, "cached_tokens", 0) or getattr(
            usage, "prompt_cache_hit_tokens", 0
        )
        cached = cached or 0
        out = getattr(usage, "completion_tokens", 0) or 0
        meta: dict[str, Any] = {
            "requests": 1,
            "model": getattr(response, "model", None) or self.model,
            "input_tokens": prompt_tokens - cached,
            "output_tokens": out,
            "cache_read_tokens": cached,
        }
        if self.free:
            meta["free"] = 1
            if self.preset.local:
                meta["local"] = 1
            meta["cost"] = 0.0
            return meta
        price = self.prices.get(f"{self.preset.name}:{self.model}")
        if price is None:
            meta["cost_unknown"] = 1
        else:
            meta["cost"] = price.cost(prompt_tokens - cached, out, cached)
        return meta


class _ToolsUnsupported(Exception):
    """The server said this model can't call tools."""
