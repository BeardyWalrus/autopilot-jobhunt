"""LLM dispatch + fallback — every provider path mocked; no network, no subprocess."""
import subprocess
import sys
import types

import pytest
from openai import RateLimitError

from job_hunt import llm_utils

# --- OpenRouter fallback chain -------------------------------------------------

class _Choice:
    def __init__(self, content):
        self.message = types.SimpleNamespace(content=content)


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Resp:
    def __init__(self, content, usage=True):
        self.choices = [_Choice(content)]
        self.usage = _Usage() if usage else None


def _client(create):
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def test_fallback_first_model_succeeds():
    llm = _client(lambda **k: _Resp("answer"))
    out = llm_utils.chat_with_fallback(llm, {}, [{"role": "user", "content": "hi"}])
    assert out == "answer"


def test_fallback_no_usage_branch():
    llm = _client(lambda **k: _Resp("answer", usage=False))
    assert llm_utils.chat_with_fallback(llm, {}, [{"role": "user", "content": "hi"}]) == "answer"


def _rate_limit_error():
    # Build without __init__ (which needs a real httpx.Response) — we only need isinstance.
    return RateLimitError.__new__(RateLimitError)


def test_fallback_switches_model_on_quota(monkeypatch):
    monkeypatch.setattr(llm_utils.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def create(model, **k):
        calls["n"] += 1
        if model == "primary":
            raise _rate_limit_error()
        return _Resp("from fallback")

    cfg = {"openrouter_model": "primary", "openrouter_fallback_models": ["backup"]}
    out = llm_utils.chat_with_fallback(_client(create), cfg, [{"role": "user", "content": "x"}])
    assert out == "from fallback"
    # primary retried twice (2 rate-limit hits) then backup succeeds
    assert calls["n"] == 3


def test_fallback_all_models_fail(monkeypatch):
    monkeypatch.setattr(llm_utils.time, "sleep", lambda *_: None)

    def create(**k):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="All LLM models failed"):
        llm_utils.chat_with_fallback(_client(create), {}, [{"role": "user", "content": "x"}])


# --- provider dispatch ---------------------------------------------------------

def test_chat_with_llm_routes_openrouter(monkeypatch):
    monkeypatch.setattr(llm_utils, "chat_with_fallback", lambda *a, **k: "OR")
    monkeypatch.setattr(llm_utils, "_make_openrouter_client", lambda cfg: object())
    assert llm_utils.chat_with_llm({"llm_provider": "openrouter"}, []) == "OR"


def test_chat_with_llm_routes_anthropic(monkeypatch):
    monkeypatch.setattr(llm_utils, "_chat_with_anthropic", lambda *a, **k: "ANT")
    assert llm_utils.chat_with_llm({"llm_provider": "anthropic"}, []) == "ANT"


def test_chat_with_llm_routes_claude_cli(monkeypatch):
    monkeypatch.setattr(llm_utils, "_chat_with_claude_cli", lambda *a, **k: "CLI")
    assert llm_utils.chat_with_llm({"llm_provider": "claude_cli"}, []) == "CLI"


def test_chat_with_llm_routes_claude_agent_sdk(monkeypatch):
    monkeypatch.setattr(llm_utils, "_chat_with_claude_agent_sdk", lambda *a, **k: "SDK")
    assert llm_utils.chat_with_llm({"llm_provider": "claude_agent_sdk"}, []) == "SDK"


def test_legacy_ollama_provider_routes_to_agent_sdk(monkeypatch):
    monkeypatch.setattr(llm_utils, "_chat_with_claude_agent_sdk", lambda *a, **k: "SDK")
    monkeypatch.setattr(llm_utils, "_warned_aliases", set())
    assert llm_utils.chat_with_llm({"llm_provider": "ollama"}, []) == "SDK"
    assert llm_utils.resolve_provider({"llm_provider": "ollama"}) == "claude_agent_sdk"


def test_resolve_provider_defaults_to_agent_sdk():
    assert llm_utils.resolve_provider({}) == "claude_agent_sdk"
    assert llm_utils.resolve_provider({"llm_provider": "anthropic"}) == "anthropic"


# --- Claude Agent SDK -------------------------------------------------------

class _SDKError(Exception):
    pass


class _CLINotFound(_SDKError):
    pass


def _fake_sdk(monkeypatch, messages=None, raises=None):
    """Install a stand-in claude_agent_sdk module; returns the captured calls."""
    captured: dict = {}

    class Opts:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.effort = None

    class TextBlock:
        def __init__(self, text):
            self.text = text

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    class ResultMessage:
        def __init__(self, result=None, is_error=False, subtype="success", cost=0.0012):
            self.result, self.is_error, self.subtype = result, is_error, subtype
            self.total_cost_usd, self.errors = cost, None

    async def query(prompt, options):
        captured["prompt"], captured["options"] = prompt, options
        if raises:
            raise raises
        for m in (messages or [])(AssistantMessage, TextBlock, ResultMessage):
            yield m

    mod = types.ModuleType("claude_agent_sdk")
    mod.ClaudeAgentOptions = Opts
    mod.AssistantMessage, mod.TextBlock, mod.ResultMessage = AssistantMessage, TextBlock, ResultMessage
    mod.ClaudeSDKError, mod.CLINotFoundError = _SDKError, _CLINotFound
    mod.query = query
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    return captured


def _reply(*texts, result=None, **res_kw):
    def build(Assistant, Text, Result):
        return [Assistant([Text(t) for t in texts]), Result(result=result, **res_kw)]
    return build


def test_agent_sdk_success(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cap = _fake_sdk(monkeypatch, _reply("Hello", " world", result="Hello world"))
    got = []
    msgs = [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}]
    out = llm_utils._chat_with_claude_agent_sdk({"claude_agent_sdk_api_key": "sk-ant-x"}, msgs,
                                                0.1, 100, on_token=got.append)
    assert out == "Hello world" and got == ["Hello", " world"]
    opts = cap["options"]
    assert cap["prompt"] == "hi"
    assert opts.model == llm_utils.DEFAULT_AGENT_SDK_MODEL == "claude-opus-5-5"
    assert opts.system_prompt == "be terse"
    assert opts.tools == [] and opts.max_turns == 1 and opts.setting_sources == []
    assert opts.strict_mcp_config is True
    assert opts.env == {"ANTHROPIC_API_KEY": "sk-ant-x"}
    assert opts.effort is None


def test_agent_sdk_model_effort_and_env_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    cap = _fake_sdk(monkeypatch, _reply("ok"))
    cfg = {"claude_agent_sdk_model": "claude-sonnet-5-5", "claude_agent_sdk_effort": "low",
           "anthropic_api_key": "YOUR_ANTHROPIC_API_KEY"}  # placeholder is skipped
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"}]
    out = llm_utils._chat_with_claude_agent_sdk(cfg, msgs, 0.1, 100)
    assert out == "ok"  # no ResultMessage.result → joined text blocks
    assert cap["options"].model == "claude-sonnet-5-5" and cap["options"].effort == "low"
    assert cap["options"].env == {"ANTHROPIC_API_KEY": "sk-ant-env"}
    assert cap["options"].system_prompt is None
    assert cap["prompt"] == "USER:\na\n\nASSISTANT:\nb\n\nUSER:\nc"


def test_agent_sdk_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _fake_sdk(monkeypatch, _reply("x"))
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        llm_utils._chat_with_claude_agent_sdk({}, [{"role": "user", "content": "x"}], 0.1, 100)


def test_agent_sdk_error_result(monkeypatch):
    _fake_sdk(monkeypatch, _reply(result="overloaded", is_error=True, subtype="error_during_execution"))
    with pytest.raises(RuntimeError, match="error_during_execution"):
        llm_utils._chat_with_claude_agent_sdk({"claude_agent_sdk_api_key": "k"},
                                              [{"role": "user", "content": "x"}], 0.1, 100)


def test_agent_sdk_cli_missing(monkeypatch):
    _fake_sdk(monkeypatch, raises=_CLINotFound("gone"))
    with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
        llm_utils._chat_with_claude_agent_sdk({"claude_agent_sdk_api_key": "k"},
                                              [{"role": "user", "content": "x"}], 0.1, 100)


def test_agent_sdk_other_sdk_error(monkeypatch):
    _fake_sdk(monkeypatch, raises=_SDKError("Invalid API key"))
    with pytest.raises(RuntimeError, match="Invalid API key"):
        llm_utils._chat_with_claude_agent_sdk({"claude_agent_sdk_api_key": "k"},
                                              [{"role": "user", "content": "x"}], 0.1, 100)


def test_agent_sdk_timeout(monkeypatch):
    import asyncio

    _fake_sdk(monkeypatch, _reply("x"))

    async def slow():
        await asyncio.sleep(5)

    monkeypatch.setattr(llm_utils, "_AGENT_SDK_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        llm_utils._run_coro_sync(slow, 0.01)


def test_agent_sdk_works_inside_running_event_loop(monkeypatch):
    """FastMCP tool handlers can call us from inside a loop; asyncio.run would refuse."""
    import asyncio

    _fake_sdk(monkeypatch, _reply("from a thread", result="from a thread"))

    async def caller():
        return llm_utils._chat_with_claude_agent_sdk({"claude_agent_sdk_api_key": "k"},
                                                     [{"role": "user", "content": "x"}], 0.1, 100)

    assert asyncio.run(caller()) == "from a thread"


# --- streaming (on_token) -----------------------------------------------------

def _stream_client(deltas):
    def create(**k):
        if k.get("stream"):
            return (
                types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=d))])
                for d in deltas
            )
        return _Resp("".join(deltas))

    fake = _client(create)
    fake.base_url = "http://x/v1"
    return fake


def test_openrouter_streams_tokens():
    got = []
    out = llm_utils.chat_with_fallback(_stream_client(["a", "b", "c"]), {"openrouter_model": "m"},
                                       [{"role": "user", "content": "x"}], on_token=got.append)
    assert out == "abc" and got == ["a", "b", "c"]


def test_nonstreaming_provider_emits_full_output(monkeypatch):
    # Anthropic doesn't stream — on_token still fires once with the whole output.
    monkeypatch.setattr(llm_utils, "_chat_with_anthropic", lambda *a, **k: "full answer")
    got = []
    out = llm_utils.chat_with_llm({"llm_provider": "anthropic"}, [], on_token=got.append)
    assert out == "full answer" and got == ["full answer"]


# --- Anthropic ----------------------------------------------------------------

def test_chat_with_anthropic(monkeypatch):
    created = {}

    class FakeMessages:
        def create(self, **kwargs):
            created.update(kwargs)
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(text="hello from claude")],
                usage=types.SimpleNamespace(input_tokens=3, output_tokens=4),
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)

    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}]
    out = llm_utils._chat_with_anthropic({"anthropic_api_key": "k"}, msgs, 0.1, 100)
    assert out == "hello from claude"
    assert created["system"] == "sys"
    assert created["messages"] == [{"role": "user", "content": "u"}]


# --- Claude CLI ---------------------------------------------------------------

def _run_ok(stdout):
    return lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_claude_cli_dict_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_ok('{"result": "dict answer"}'))
    out = llm_utils._chat_with_claude_cli({"claude_cli_model": "sonnet"},
                                          [{"role": "user", "content": "hi"}], 0.1, 100)
    assert out == "dict answer"


def test_claude_cli_list_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        _run_ok('[{"type": "other"}, {"type": "result", "result": "list answer"}]'))
    out = llm_utils._chat_with_claude_cli({}, [{"role": "system", "content": "s"},
                                               {"role": "user", "content": "hi"}], 0.1, 100)
    assert out == "list answer"


def test_claude_cli_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=2, stdout="", stderr="nope"))
    with pytest.raises(RuntimeError, match="exited 2"):
        llm_utils._chat_with_claude_cli({}, [{"role": "user", "content": "x"}], 0.1, 100)


def test_claude_cli_bad_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _run_ok("not json"))
    with pytest.raises(RuntimeError, match="unexpected output"):
        llm_utils._chat_with_claude_cli({}, [{"role": "user", "content": "x"}], 0.1, 100)


def test_claude_cli_binary_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="claude binary not found"):
        llm_utils._chat_with_claude_cli({}, [{"role": "user", "content": "x"}], 0.1, 100)


def test_claude_cli_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=300)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="timed out"):
        llm_utils._chat_with_claude_cli({}, [{"role": "user", "content": "x"}], 0.1, 100)
