"""M6: AI models in the arena. Every test talks to a fake client: nothing is sent anywhere."""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from typer.testing import CliRunner

from busride import cli, config
from busride.agents.base import CASH, AgentError, AgentUnavailable, Observation, describe
from busride.agents.baselines import make_agent
from busride.agents.llm import LLMOptions, make_llm_agent
from busride.agents.llm import anthropic_agent as claude_mod
from busride.agents.llm import openai_agent as openai_mod
from busride.agents.llm.anthropic_agent import FALLBACK_BETA, ClaudeAgent
from busride.agents.llm.openai_agent import OpenAICompatAgent
from busride.agents.llm.prices import BUILT_IN, Price, PriceTable, dump_prices, load_prices
from busride.agents.llm.prompt import all_guesses, from_json_reply, user_message
from busride.arena.runner import Arena
from busride.arena.runs import RunFile
from busride.arena.scoring import score
from busride.cli import app
from busride.coach.llm import Rewording, keeps_numbers
from busride.engine.builtins import BUILTIN_GAMES
from busride.engine.cards import parse_cards

RTB = BUILTIN_GAMES["ride-the-bus"]
runner = CliRunner()


def obs(
    cards: str = "9h", stage: int = 2, cash: float = 1.8, feedback: str | None = None
) -> Observation:
    seen = tuple(parse_cards(cards)) if cards else ()
    s = RTB.stages[len(seen)]
    return Observation(
        game=RTB.name,
        stage=stage,
        stages=4,
        question=s.question,
        kind=s.kind,
        options=s.guesses,
        can_cash_out=stage > 1,
        seen=seen,
        compare=tuple(seen[i] for i in s.refs),
        cash_value=cash,
        ladder=RTB.returns,
        rules=describe(RTB),
        feedback=feedback,
    )


# ── fake clients ─────────────────────────────────────────────────────────────────────────


def usage(
    inp: int = 100, out: int = 500, read: int = 600, write: int = 0, iterations: Any = None
) -> NS:
    return NS(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=read,
        cache_creation_input_tokens=write,
        iterations=iterations,
    )


def claude_reply(
    tool: str | None = "make_guess",
    args: dict[str, Any] | None = None,
    text: str = "",
    stop: str = "tool_use",
    model: str = "claude-opus-5-5",
    use: NS | None = None,
    details: Any = None,
) -> NS:
    content: list[NS] = [NS(type="thinking", thinking="")]
    if text:
        content.append(NS(type="text", text=text))
    if tool:
        args = (
            {"choice": "lower", "win_probability": 0.6, "reason": "a hunch"}
            if args is None
            else args
        )
        content.append(NS(type="tool_use", id="toolu_1", name=tool, input=args))
    return NS(
        content=content, stop_reason=stop, stop_details=details, model=model, usage=use or usage()
    )


class FakeMessages:
    def __init__(self, respond: Callable[[dict[str, Any]], Any]) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []

    def create(self, **params: Any) -> Any:
        self.calls.append(params)
        reply = self.respond(params)
        if isinstance(reply, Exception):
            raise reply
        return reply


def fake_claude(respond: Callable[[dict[str, Any]], Any]) -> NS:
    return NS(beta=NS(messages=FakeMessages(respond)))


def replies(*items: Any) -> Callable[[dict[str, Any]], Any]:
    queue = list(items)
    return lambda params: queue.pop(0)


def legal_moves(params: dict[str, Any]) -> list[str]:
    messages = params["messages"]
    text = messages[-1]["content"]
    m = re.search(
        r"Legal moves: (.+?)(, or cash out| \(cashing out is not allowed yet\))?\.\n", text + "\n"
    )
    assert m, text
    return m.group(1).split(", ")


def plays_first_legal(params: dict[str, Any]) -> NS:
    """A fake Claude that always makes the first legal guess and says 50%."""
    choice = legal_moves(params)[0]
    return claude_reply(args={"choice": choice, "win_probability": 0.5, "reason": "first"})


def status_error(cls: type, code: int, message: str = "nope") -> Exception:
    request = httpx2.Request("POST", "https://example.invalid/v1/messages")
    return cls(message, response=httpx2.Response(code, request=request), body=None)  # type: ignore[no-any-return]


# ── the prompt ───────────────────────────────────────────────────────────────────────────


def test_the_question_is_in_plain_words() -> None:
    text = user_message(obs(), RTB)
    assert "Stage 2 of 4: higher or lower." in text
    assert "9h (nine of hearts)" in text and "Cards left in the deck: 51." in text
    assert "Legal moves: higher, lower, or cash out." in text
    assert "Cashing out now pays 1.80" in text and "2.30" in text
    first = user_message(obs("", stage=1, cash=1.0), RTB)
    assert "No cards are on the table yet." in first and "must guess" in first
    assert "cashing out is not allowed yet" in first
    retry = user_message(obs(feedback="'purple' is not a move here"), RTB)
    assert "rejected: 'purple' is not a move here" in retry


def test_every_guess_of_the_game_is_in_the_tool_enum() -> None:
    assert all_guesses(RTB) == [
        "red", "black", "higher", "lower", "inside", "outside",
        "hearts", "diamonds", "clubs", "spades",
    ]  # fmt: skip
    assert all_guesses(BUILTIN_GAMES["hi-lo-5"]) == ["higher", "lower"]


def test_json_replies_are_read() -> None:
    a = from_json_reply('Sure! {"move": "Higher", "win_probability": "0.7", "reason": "x"}', {})
    assert (a.move, a.win_probability) == ("higher", 0.7)
    assert from_json_reply('{"move": "cash out", "win_probability": null}', {}).move == CASH
    with pytest.raises(AgentError):
        from_json_reply("I think higher.", {})
    with pytest.raises(AgentError):
        from_json_reply('{"move": "higher", "win_probability": "likely"}', {})


# ── Claude ───────────────────────────────────────────────────────────────────────────────


def test_claude_requests_cache_and_fall_back() -> None:
    client = fake_claude(plays_first_legal)
    agent = ClaudeAgent(RTB, client=client)
    agent.decide(obs("", stage=1, cash=1.0))
    agent.decide(obs("9h"))
    first, second = client.beta.messages.calls
    assert first["model"] == "claude-opus-5-5"
    assert first["output_config"] == {"effort": "medium"}
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    for key in ("thinking", "temperature", "tool_choice", "top_p"):
        assert key not in first  # thinking stays on; forced tool choice is a 400 on this model
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    for tool in first["tools"]:
        assert tool["strict"] is True and tool["input_schema"]["additionalProperties"] is False
    # the cached prefix is byte-identical; only the question changes
    assert json.dumps(first["tools"]) == json.dumps(second["tools"])
    assert json.dumps(first["system"]) == json.dumps(second["system"])
    assert first["messages"] != second["messages"]
    no_fallback = ClaudeAgent(RTB, fallback=False, client=fake_claude(plays_first_legal))
    assert "fallbacks" not in no_fallback.request(obs()) and "betas" not in no_fallback.request(
        obs()
    )
    assert "fallbacks" not in ClaudeAgent(RTB, "claude-opus-4-8", client=client).request(obs())


def test_claude_answers_become_moves_with_their_cost() -> None:
    agent = ClaudeAgent(RTB, client=fake_claude(replies(claude_reply())))
    action = agent.decide(obs())
    assert (action.move, action.win_probability, action.reason) == ("lower", 0.6, "a hunch")
    assert json.loads(action.raw or "")["tool"] == "make_guess"
    m = action.meta
    assert (m["input_tokens"], m["output_tokens"], m["cache_read_tokens"]) == (100, 500, 600)
    assert m["cost"] == pytest.approx((100 * 4 + 500 * 20 + 600 * 0.2) / 1e6)
    assert "fallback" not in m
    cash = ClaudeAgent(
        RTB, client=fake_claude(replies(claude_reply("cash_out", {"reason": "safe"})))
    )
    assert cash.decide(obs()).move == CASH


def test_an_answer_from_a_fallback_model_is_flagged_and_priced_at_its_rates() -> None:
    attempts = [
        NS(type="message", model="claude-opus-5-5", input_tokens=700, output_tokens=0,
           cache_read_input_tokens=0, cache_creation_input_tokens=0),
        NS(type="fallback_message", model="claude-opus-4-8", input_tokens=700, output_tokens=300,
           cache_read_input_tokens=0, cache_creation_input_tokens=0),
    ]  # fmt: skip
    reply = claude_reply(model="claude-opus-4-8", use=usage(700, 300, 0, iterations=attempts))
    action = ClaudeAgent(RTB, client=fake_claude(replies(reply))).decide(obs())
    assert action.meta["fallback"] == 1 and action.meta["model"] == "claude-opus-4-8"
    assert action.meta["cost"] == pytest.approx((700 * 4 + 700 * 5 + 300 * 25) / 1e6)


def test_refusals_and_missing_tool_calls_are_retried_then_forfeited(tmp_path: Path) -> None:
    refusal = claude_reply(None, stop="refusal", details=NS(category="cyber", explanation=None))
    chatty = claude_reply(None, text="I'd go lower, I think.", stop="end_turn")
    client = fake_claude(lambda params: chatty if len(client.beta.messages.calls) % 2 else refusal)
    agent = ClaudeAgent(RTB, client=client)
    path = tmp_path / "run.jsonl"
    Arena(RTB, path, seed=1, deals=3).run([agent])
    calls = client.beta.messages.calls
    assert len(calls) == 6  # one decision per deal, asked twice
    assert "rejected: no tool call" in calls[1]["messages"][0]["content"]
    decisions = list(RunFile(path).decisions())
    assert all(d["move"] == "forfeit" for d in decisions)
    assert "declined to answer (cyber)" in decisions[0]["problems"][1]
    assert "I'd go lower" in decisions[0]["problems"][0]
    assert decisions[0]["meta"]["requests"] == 2  # both attempts are counted (and paid for)
    board = score(RunFile(path))[agent.name]
    assert board.forfeits == 3 and board.meta["requests"] == 6


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (status_error(anthropic.AuthenticationError, 401), "rejected the API key"),
        (status_error(anthropic.NotFoundError, 404), "no Claude model called"),
        (status_error(anthropic.RateLimitError, 429), "rate limit"),
        (status_error(anthropic.InternalServerError, 500), "answered with an error"),
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x.invalid")),
            "reach",
        ),
    ],
)
def test_claude_failures_stop_the_run_with_a_plain_reason(error: Exception, says: str) -> None:
    agent = ClaudeAgent(RTB, client=fake_claude(replies(error)))
    with pytest.raises(AgentUnavailable, match=says):
        agent.decide(obs())


def test_no_credentials_says_how_to_get_them(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_key() -> None:
        raise anthropic.CredentialsError("no profile")

    monkeypatch.setattr(claude_mod.anthropic, "Anthropic", lambda **kw: no_key())
    with pytest.raises(AgentUnavailable, match="ANTHROPIC_API_KEY"):
        ClaudeAgent(RTB).decide(obs())


# ── OpenAI-compatible ────────────────────────────────────────────────────────────────────


def chat_reply(tool: str | None = "make_guess", args: str = "", text: str | None = None) -> NS:
    calls = None
    if tool:
        args = args or json.dumps({"choice": "higher", "win_probability": 0.4, "reason": "r"})
        calls = [NS(id="c1", type="function", function=NS(name=tool, arguments=args))]
    message = NS(content=text, tool_calls=calls, refusal=None)
    return NS(
        choices=[NS(message=message, finish_reason="tool_calls" if tool else "stop")],
        model="m",
        usage=NS(prompt_tokens=800, completion_tokens=50, prompt_tokens_details=None),
    )


def fake_openai(respond: Callable[[dict[str, Any]], Any]) -> NS:
    return NS(chat=NS(completions=FakeMessages(respond)))


def test_openai_compatible_tool_calls() -> None:
    client = fake_openai(replies(chat_reply()))
    agent = OpenAICompatAgent("ollama", "llama3.1:8b", RTB, client=client)
    action = agent.decide(obs())
    assert (action.move, action.win_probability) == ("higher", 0.4)
    assert action.meta["local"] == 1 and action.meta["cost"] == 0.0
    params = client.chat.completions.calls[0]
    assert params["tool_choice"] == "auto" and "strict" not in params["tools"][0]["function"]
    assert params["messages"][0]["role"] == "system"
    strict = OpenAICompatAgent("openai", "gpt-x", RTB, client=client)
    assert strict.tools[0]["function"]["strict"] is True and strict.paid


def test_a_model_without_tools_answers_in_json() -> None:
    no_tools = status_error(openai.BadRequestError, 400, "llama2 does not support tools")
    client = fake_openai(
        replies(
            no_tools,
            chat_reply(None, text='{"move": "lower"}'),
            chat_reply(None, text='{"move": "cash"}'),
        )
    )
    agent = OpenAICompatAgent("ollama", "llama2", RTB, client=client)
    assert agent.decide(obs()).move == "lower"
    assert agent.decide(obs()).move == CASH
    calls = client.chat.completions.calls
    assert "tools" in calls[0] and "tools" not in calls[1] and "tools" not in calls[2]
    assert "Reply with one JSON object" in calls[1]["messages"][0]["content"]


def test_ollama_not_running_says_how_to_start_it() -> None:
    down = openai.APIConnectionError(request=httpx2.Request("POST", "http://localhost:11434"))
    agent = OpenAICompatAgent("ollama", "llama3.1:8b", RTB, client=fake_openai(replies(down)))
    with pytest.raises(AgentUnavailable, match="ollama serve"):
        agent.decide(obs())
    gone = status_error(openai.NotFoundError, 404)
    agent = OpenAICompatAgent("ollama", "nope", RTB, client=fake_openai(replies(gone)))
    with pytest.raises(AgentUnavailable, match="ollama pull nope"):
        agent.decide(obs())


def test_a_paid_provider_without_a_key_says_which_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(AgentUnavailable, match="GROQ_API_KEY"):
        OpenAICompatAgent("groq", "llama", RTB).decide(obs())


# ── names, prices, settings ──────────────────────────────────────────────────────────────


def test_ai_agent_names() -> None:
    assert make_agent("claude", RTB).name == "claude:claude-opus-5-5"
    assert make_agent("claude@high", RTB).name == "claude:claude-opus-5-5@high"
    sonnet = make_agent("claude:claude-sonnet-5-5@low", RTB)
    assert sonnet.name == "claude:claude-sonnet-5-5@low" and sonnet.effort == "low"  # type: ignore[attr-defined]
    local = make_agent("ollama:llama3.1:8b", RTB)
    assert local.name == "ollama:llama3.1:8b" and local.model == "llama3.1:8b"  # type: ignore[attr-defined]
    assert (
        make_agent("ai", RTB, llm=LLMOptions(default_ai="ollama:qwen3:4b")).name
        == "ollama:qwen3:4b"
    )
    assert make_llm_agent("claude", RTB, LLMOptions(effort="high")).name.endswith("@high")
    for bad in ("openai", "claude@huge", "ollama", "ai"):
        with pytest.raises(ValueError):
            make_agent(bad, RTB, llm=LLMOptions(default_ai="greedy"))


def test_prices_are_dated_and_editable(tmp_path: Path) -> None:
    table = load_prices(tmp_path / "missing.toml")
    assert (
        table.source == "built in" and table.get("claude-opus-5-5") == BUILT_IN["claude-opus-5-5"]
    )
    assert table.get("claude:claude-opus-5-5") is not None
    path = tmp_path / "prices.toml"
    edited = PriceTable({**table.prices, "openai:gpt-x": Price(1.0, 2.0)}, "2026-10-24", "test")
    path.write_text(dump_prices(edited), encoding="utf-8")
    again = load_prices(path)
    assert again.as_of == "2026-10-24" and again.get("openai:gpt-x") == Price(1.0, 2.0)
    assert again.get("claude-haiku-5-5") == BUILT_IN["claude-haiku-5-5"]
    out = run_cli("arena", "prices")
    assert "claude-opus-5-5" in out and (config.config_dir() / "prices.toml").exists()


def test_unknown_prices_are_unknown_not_zero() -> None:
    agent = OpenAICompatAgent("openai", "gpt-x", RTB, client=fake_openai(replies(chat_reply())))
    meta = agent.decide(obs()).meta
    assert meta["cost_unknown"] == 1 and "cost" not in meta
    assert agent.rough_cost(10) is None
    assert ClaudeAgent(RTB, client=object()).rough_cost(10) > 0  # type: ignore[operator]


def run_cli(*args: str, input: str | None = None) -> str:
    result = runner.invoke(app, [*args, "--plain"], input=input)
    assert result.exit_code == 0, result.output
    return result.output


def test_settings_keep_your_ai_model() -> None:
    run_cli("settings", "--ai", "ollama:qwen3:4b", "--effort", "high", "--coach-ai", "claude")
    s = config.load_settings()
    assert (s.ai, s.effort, s.coach_ai) == ("ollama:qwen3:4b", "high", "claude")
    run_cli("settings", "--coach-ai", "off")
    assert config.load_settings().coach_ai == ""
    for bad in (["--ai", "greedy"], ["--ai", "openai"], ["--effort", "huge"]):
        result = runner.invoke(app, ["settings", *bad, "--plain"])
        assert result.exit_code == 1, bad


# ── the arena command and its cost guard ─────────────────────────────────────────────────


@pytest.fixture
def claude_client(monkeypatch: pytest.MonkeyPatch) -> NS:
    client = fake_claude(plays_first_legal)
    monkeypatch.setattr(claude_mod, "make_client", lambda: client)
    return client


def test_a_paid_run_needs_your_ok(claude_client: NS) -> None:
    result = runner.invoke(app, ["arena", "run", "--agents", "optimal,claude", "--plain"])
    assert result.exit_code == 1 and "--yes" in result.output and "costs money" in result.output
    assert claude_client.beta.messages.calls == []  # nothing was sent


def test_with_yes_the_run_plays_and_shows_the_cost(claude_client: NS) -> None:
    out = run_cli("arena", "run", "--agents", "optimal,claude", "--deals", "5", "--yes")
    assert "20 duplicate deals" not in out and "5 duplicate deals" in out
    assert "Cost" in out and "claude:claude-opus-5-5" in out and "AI models:" in out
    assert "from the cache" in out and "AI calls this time: $" in out
    assert claude_client.beta.messages.calls


def test_ai_runs_default_to_20_deals(claude_client: NS) -> None:
    out = run_cli("arena", "run", "--agents", "claude", "--yes")
    assert "20 duplicate deals" in out


def test_the_cost_limit_stops_the_run(claude_client: NS) -> None:
    out = run_cli(
        "arena", "run", "--agents", "claude", "--deals", "20", "--yes", "--max-cost", "0.001"
    )
    assert "Stopped at the cost limit" in out
    done = RunFile(config.runs_dir() / "ride-the-bus-seed7-20.jsonl").done()
    assert 1 <= len(done) < 20


def test_in_a_terminal_it_estimates_pilots_then_asks(
    claude_client: NS, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    out = run_cli("arena", "run", "--agents", "claude", "--deals", "4", input="n\n")
    assert "a rough guess" in out and "Nothing more was played" in out
    assert claude_client.beta.messages.calls == []
    out = run_cli("arena", "run", "--agents", "claude", "--deals", "4", input="y\ny\n")
    assert "Measured on the first deal" in out and "per deal so far" in out
    assert len(RunFile(config.runs_dir() / "ride-the-bus-seed7-4.jsonl").done()) == 4


def test_an_unreachable_model_stops_the_run_and_keeps_what_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def flaky(params: dict[str, Any]) -> Any:
        calls["n"] += 1
        if calls["n"] > 3:
            return status_error(anthropic.RateLimitError, 429)
        return plays_first_legal(params)

    monkeypatch.setattr(claude_mod, "make_client", lambda: fake_claude(flaky))
    result = runner.invoke(
        app, ["arena", "run", "--agents", "claude", "--deals", "10", "--yes", "--plain"]
    )
    assert result.exit_code == 1
    assert "rate limit" in result.output and "run the same command again" in result.output
    done = RunFile(config.runs_dir() / "ride-the-bus-seed7-10.jsonl").done()
    assert len(done) < 10
    monkeypatch.setattr(claude_mod, "make_client", lambda: fake_claude(plays_first_legal))
    run_cli("arena", "run", "--agents", "claude", "--deals", "10", "--yes")  # carries on
    assert len(RunFile(config.runs_dir() / "ride-the-bus-seed7-10.jsonl").done()) == 10


def test_agents_lists_the_ai_models() -> None:
    out = run_cli("arena", "agents")
    assert "claude" in out and "ollama:MODEL" in out and "optimal" in out


# ── the coach's wording ──────────────────────────────────────────────────────────────────


def test_rewording_keeps_every_number() -> None:
    text = "Lower wins 48 of 51 cards (94%), worth 2.29 against 1.80 for stopping."
    assert keeps_numbers(
        text, "48 of the 51 cards win if you go lower (94%), worth 2.29, not 1.80."
    )
    assert not keeps_numbers(text, "Lower wins about 95% of the time.")  # a new number
    assert not keeps_numbers(text, "Go lower!")  # every number dropped
    assert keeps_numbers("Every choice is worth the same.", "Both choices are equal here.")


def test_the_coach_falls_back_to_its_own_words(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Lower wins 48 of 51 cards (94%)."
    good = fake_claude(
        replies(claude_reply(None, text="Going lower wins 48 of 51 cards (94%).", stop="end_turn"))
    )
    monkeypatch.setattr(claude_mod, "make_client", lambda: good)
    assert Rewording("claude", RTB)(text) == "Going lower wins 48 of 51 cards (94%)."
    assert good.beta.messages.calls[0]["output_config"] == {"effort": "low"}
    wrong = fake_claude(replies(claude_reply(None, text="Lower wins 49 of 51.", stop="end_turn")))
    monkeypatch.setattr(claude_mod, "make_client", lambda: wrong)
    assert Rewording("claude", RTB)(text) == text
    down = fake_claude(replies(status_error(anthropic.AuthenticationError, 401)))
    monkeypatch.setattr(claude_mod, "make_client", lambda: down)
    coach = Rewording("claude", RTB)
    assert coach(text) == text and coach.problem and "API key" in coach.problem


def test_play_explain_uses_the_ai_wording(monkeypatch: pytest.MonkeyPatch) -> None:
    def reword(params: dict[str, Any]) -> NS:
        original = params["messages"][0]["content"].removeprefix("Reword this: ")
        return claude_reply(None, text=f"In other words: {original}", stop="end_turn")

    monkeypatch.setattr(claude_mod, "make_client", lambda: fake_claude(reword))
    config.save_settings(config.Settings(coach_ai="claude"))
    out = run_cli(
        "play", "--rounds", "1", "--seed", "3", "--coach", "explain", input="\n1\n1\n1\n1\n$\n"
    )
    assert "reworded by claude" in out and "In other words:" in out


# ── doctor ───────────────────────────────────────────────────────────────────────────────


def test_doctor_reports_ollama_without_hanging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")  # nothing listens there
    out = run_cli("doctor")
    assert "Ollama" in out and "not running at http://127.0.0.1:9" in out
    assert "anthropic" in out and "openai" in out


def test_ollama_host_forms() -> None:
    assert openai_mod.base_url(openai_mod.PRESETS["ollama"]).endswith("/v1")


# ── DeepSeek, free models and .env files ─────────────────────────────────────────────────


def test_deepseek_is_a_preset_with_a_default_model() -> None:
    agent = make_agent("deepseek", RTB)
    assert agent.name == "deepseek:deepseek-flash" and agent.paid  # type: ignore[attr-defined]
    assert openai_mod.base_url(openai_mod.PRESETS["deepseek"]) == "https://api.deepseek.com"
    pro = make_agent("deepseek:deepseek-v4-pro@high", RTB)
    params = pro.request(obs())  # type: ignore[attr-defined]
    assert params["reasoning_effort"] == "high"
    assert params["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "extra_body" not in agent.request(obs())  # type: ignore[attr-defined]


def test_deepseek_cache_hits_are_priced_as_cache_reads() -> None:
    reply = chat_reply()
    reply.usage = NS(
        prompt_tokens=1000,
        completion_tokens=200,
        prompt_tokens_details=None,
        prompt_cache_hit_tokens=800,
        prompt_cache_miss_tokens=200,
    )
    agent = OpenAICompatAgent("deepseek", "deepseek-flash", RTB, client=fake_openai(replies(reply)))
    meta = agent.decide(obs()).meta
    assert (meta["input_tokens"], meta["cache_read_tokens"]) == (200, 800)
    assert meta["cost"] == pytest.approx((200 * 0.30 + 200 * 1.20 + 800 * 0.006) / 1e6)
    assert agent.rough_cost(50) == pytest.approx(agent.rough_cost(1) * 50)  # type: ignore[operator]


def test_free_models_need_no_ok() -> None:
    assert not make_agent("openrouter:deepseek/deepseek-chat:free", RTB).paid  # type: ignore[attr-defined]
    assert make_agent("openrouter:deepseek/deepseek-chat", RTB).paid  # type: ignore[attr-defined]
    table = PriceTable({"groq:llama-3.1-8b": Price(0.0, 0.0)}, "today", "test")
    groq = OpenAICompatAgent(
        "groq", "llama-3.1-8b", RTB, prices=table, client=fake_openai(replies(chat_reply()))
    )
    assert not groq.paid and groq.rough_cost(10) == 0.0
    assert groq.decide(obs()).meta["free"] == 1


def test_keys_can_live_in_a_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BUSRIDE_T1", "BUSRIDE_T2", "BUSRIDE_T3", "BUSRIDE_T4"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BUSRIDE_T4", "from the terminal")
    monkeypatch.setattr(config, "ENV_FROM", {})
    env = tmp_path / ".env"
    env.write_text(
        "﻿# keys\nBUSRIDE_T1=plain\nexport BUSRIDE_T2='quoted # not a comment'\n"
        "BUSRIDE_T3=value # a comment\nBUSRIDE_T4=from the file\nEMPTY=\nnot a line\n",
        encoding="utf-8",
    )
    loaded = config.load_env_files([env, tmp_path / "missing.env"])
    assert os.environ["BUSRIDE_T1"] == "plain"
    assert os.environ["BUSRIDE_T2"] == "quoted # not a comment"
    assert os.environ["BUSRIDE_T3"] == "value"
    assert os.environ["BUSRIDE_T4"] == "from the terminal"  # the terminal wins
    assert set(loaded) == {"BUSRIDE_T1", "BUSRIDE_T2", "BUSRIDE_T3"} and loaded["BUSRIDE_T1"] == env


def test_doctor_says_a_key_came_from_dotenv_without_showing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-test-not-a-real-key-123"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    monkeypatch.setattr(config, "ENV_FROM", {"DEEPSEEK_API_KEY": Path(".env")})
    out = run_cli("doctor")
    assert "found (from .env)" in out and secret not in out
