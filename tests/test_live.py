"""Live smoke tests: one real decision from a real model. Skipped unless you ask for them.

BUSRIDE_LIVE=1 uv run pytest tests/test_live.py              # Claude: about $0.02
BUSRIDE_LIVE_DEEPSEEK=1 uv run pytest tests/test_live.py     # DeepSeek: under $0.01
BUSRIDE_LIVE_OLLAMA=qwen3:4b uv run pytest tests/test_live.py  # a local model: free
"""

import json
import os
import urllib.request

import pytest

from busride import config
from busride.agents.base import CASH, Observation, describe
from busride.agents.llm.anthropic_agent import ClaudeAgent
from busride.agents.llm.openai_agent import OpenAICompatAgent
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_cards

RTB = BUILTIN_GAMES["ride-the-bus"]


def _ollama_up() -> bool:
    try:
        with urllib.request.urlopen(f"{config.ollama_url()}/api/tags", timeout=1.0) as reply:
            return isinstance(json.load(reply), dict)
    except (OSError, ValueError):
        return False


def _observation() -> Observation:
    seen = tuple(parse_cards("2h"))
    return Observation(
        game=RTB.name,
        stage=2,
        stages=4,
        question="Higher or lower",
        kind="higher_lower",
        options=("higher", "lower"),
        can_cash_out=True,
        seen=seen,
        compare=seen,
        cash_value=1.8,
        ladder=RTB.returns,
        rules=describe(RTB),
    )


@pytest.mark.skipif(not os.environ.get("BUSRIDE_LIVE"), reason="costs money: set BUSRIDE_LIVE=1")
def test_one_real_claude_decision() -> None:
    action = ClaudeAgent(RTB, effort="low").decide(_observation())
    assert action.move in ("higher", "lower", CASH)
    assert action.meta["requests"] == 1 and action.meta["output_tokens"] > 0


@pytest.mark.skipif(
    not os.environ.get("BUSRIDE_LIVE_DEEPSEEK"), reason="costs money: set BUSRIDE_LIVE_DEEPSEEK=1"
)
def test_one_real_deepseek_decision() -> None:
    config.load_env_files()  # DEEPSEEK_API_KEY may be in .env
    action = OpenAICompatAgent("deepseek", "deepseek-flash", RTB).decide(_observation())
    assert action.move in ("higher", "lower", CASH)
    assert action.meta["requests"] == 1 and "cost" in action.meta


@pytest.mark.skipif(
    not os.environ.get("BUSRIDE_LIVE_OLLAMA") or not _ollama_up(),
    reason="set BUSRIDE_LIVE_OLLAMA=MODEL with Ollama running",
)
def test_one_real_ollama_decision() -> None:
    model = os.environ["BUSRIDE_LIVE_OLLAMA"]
    action = OpenAICompatAgent("ollama", model, RTB).decide(_observation())
    assert action.move in ("higher", "lower", CASH)
    assert action.meta["local"] == 1
