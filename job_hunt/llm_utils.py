import json
import os
import subprocess
import time
from typing import Any, cast

from openai import OpenAI, RateLimitError

from job_hunt.log import get_logger

logger = get_logger()

# Per-request timeout (seconds) for HTTP-based LLM providers. Without this the
# openai/anthropic SDKs default to 600s, so a single stalled free-tier model can
# freeze a scan for 10 minutes. claude_cli has its own subprocess timeout (300s).
_LLM_REQUEST_TIMEOUT = 120.0


def _make_openrouter_client(config: dict) -> OpenAI:
    return OpenAI(
        api_key=config.get("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        timeout=_LLM_REQUEST_TIMEOUT,
    )


def _stream_chat(llm: OpenAI, model: str, messages: list[dict], temperature: float,
                 max_tokens: int, on_token) -> str:
    """Stream a chat completion, calling on_token(delta) for each chunk. Returns
    the full text. Used by the OpenAI-compatible provider (OpenRouter)
    so the web UI can show the model's output as it generates."""
    resp = llm.chat.completions.create(
        model=model,
        messages=cast("Any", messages),
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    parts: list[str] = []
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            parts.append(delta)
            on_token(delta)
    return "".join(parts)


# Default model for the Claude Agent SDK provider. Override with
# "claude_agent_sdk_model" in config.json or CLAUDE_AGENT_SDK_MODEL in .env.
DEFAULT_AGENT_SDK_MODEL = "claude-opus-5-5"

# Wall-clock cap for one Agent SDK call (it runs the bundled Claude Code CLI as a
# subprocess, like claude_cli, so it gets the same 300s budget).
_AGENT_SDK_TIMEOUT = 300.0

# Older configs used "ollama"; that provider has been replaced by the Claude
# Agent SDK, so the old value is routed there instead of failing.
_PROVIDER_ALIASES = {"ollama": "claude_agent_sdk"}
_warned_aliases: set[str] = set()


def resolve_provider(config: dict) -> str:
    """The provider to use (default claude_agent_sdk), with retired names mapped
    to their replacement."""
    provider = config.get("llm_provider") or "claude_agent_sdk"
    new = _PROVIDER_ALIASES.get(provider)
    if new:
        if provider not in _warned_aliases:
            _warned_aliases.add(provider)
            logger.warning(
                f'llm_provider "{provider}" is no longer supported — using "{new}" instead. '
                f'Set "llm_provider": "{new}" in config.json to silence this.'
            )
        return new
    return provider


def _agent_sdk_api_key(config: dict) -> str | None:
    for val in (
        config.get("claude_agent_sdk_api_key"),
        config.get("anthropic_api_key"),
        os.getenv("ANTHROPIC_API_KEY"),
    ):
        if val and not val.upper().startswith("YOUR_") and not val.lower().endswith("_here"):
            return val
    return None


def _run_coro_sync(make_coro, timeout: float):
    """Run an async SDK call from sync code. Callers include FastMCP tool
    handlers that may already be inside an event loop, where asyncio.run()
    refuses to start — in that case run it on a fresh thread instead."""
    import asyncio
    import concurrent.futures

    async def _bounded():
        return await asyncio.wait_for(make_coro(), timeout=timeout)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_bounded())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _bounded()).result()


def _chat_with_claude_agent_sdk(config: dict, messages: list[dict], temperature: float,
                                max_tokens: int, on_token=None) -> str:
    """One-shot completion through the Claude Agent SDK.

    The SDK drives the Claude Code CLI bundled in the claude-agent-sdk wheel, so
    no separate install is needed. All built-in tools, MCP servers and on-disk
    Claude settings are switched off: this is a plain prompt → text call.
    temperature and max_tokens aren't settable through the SDK and are ignored.
    """
    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKError,
            CLINotFoundError,
            ResultMessage,
            TextBlock,
            query,
        )
    except ImportError:
        raise ImportError("Run: pip install claude-agent-sdk")

    api_key = _agent_sdk_api_key(config)
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set for the claude_agent_sdk provider.\n"
            "Add ANTHROPIC_API_KEY=sk-ant-... to your .env (or the container's environment).\n"
            "Get a key at https://console.anthropic.com"
        )
    model = config.get("claude_agent_sdk_model") or DEFAULT_AGENT_SDK_MODEL
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
    user_msgs = [m for m in messages if m["role"] != "system"]
    if len(user_msgs) == 1:
        prompt_text = user_msgs[0]["content"]
    else:
        prompt_text = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in user_msgs)

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system,
        tools=[],                # no built-in tools: plain text in, text out
        max_turns=1,
        setting_sources=[],      # ignore ~/.claude and project settings
        mcp_servers={},
        strict_mcp_config=True,  # and any .mcp.json / user MCP servers
        env={"ANTHROPIC_API_KEY": api_key},
    )
    effort = config.get("claude_agent_sdk_effort")
    if effort:  # low / medium / high / xhigh / max — blank = the model's default
        options.effort = effort
    logger.debug(f"LLM call → Claude Agent SDK / {model}")
    t0 = time.time()

    async def _run() -> tuple[str, Any]:
        parts: list[str] = []
        final: Any = None
        async for msg in query(prompt=prompt_text, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        parts.append(block.text)
                        if on_token:
                            on_token(block.text)
            elif isinstance(msg, ResultMessage):
                final = msg
        return "".join(parts), final

    try:
        text, result = _run_coro_sync(_run, _AGENT_SDK_TIMEOUT)
    except CLINotFoundError:
        raise RuntimeError(
            "Claude Code CLI not found. It ships inside the claude-agent-sdk package — "
            "reinstall it with: pip install --force-reinstall claude-agent-sdk"
        )
    except TimeoutError:
        raise RuntimeError(f"Claude Agent SDK call timed out after {_AGENT_SDK_TIMEOUT:.0f}s.")
    except ClaudeSDKError as e:
        raise RuntimeError(f"Claude Agent SDK call failed: {e}") from e

    if result is not None and result.is_error:
        detail = result.result or getattr(result, "errors", None) or result.subtype
        raise RuntimeError(f"Claude Agent SDK call failed ({result.subtype}): {detail}")
    if result is not None and result.result:
        text = result.result
    elapsed = time.time() - t0
    cost = getattr(result, "total_cost_usd", None)
    cost_note = f", ${cost:.4f}" if cost else ""
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via agent-sdk/{model}{cost_note}")
    return text


def _chat_with_anthropic(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install 'autopilot-jobs[claude]'")
    api_key = config.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY")
    model = config.get("anthropic_model", "claude-haiku-4-5-20251001")
    logger.debug(f"LLM call → Anthropic / {model}")
    t0 = time.time()
    client = anthropic.Anthropic(api_key=api_key, timeout=_LLM_REQUEST_TIMEOUT)
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    kwargs: dict = {
        "model": model,
        "messages": user_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system
    r = client.messages.create(**kwargs)
    elapsed = time.time() - t0
    text = r.content[0].text
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s (input={r.usage.input_tokens} out={r.usage.output_tokens} tokens)")
    return text


def _chat_with_claude_cli(config: dict, messages: list[dict], temperature: float, max_tokens: int) -> str:
    model = config.get("claude_cli_model", "")
    logger.debug(f"LLM call → Claude CLI{' / ' + model if model else ''}")
    t0 = time.time()

    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    user_msgs = [m for m in messages if m["role"] != "system"]
    prompt_text = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in user_msgs)

    # --strict-mcp-config suppresses all MCP servers in the subprocess; reduces ~27k context tokens
    cmd = [
        "claude", "--print", "--output-format", "json", "--tools", "",
        "--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config",
        "--disable-slash-commands",
    ]
    if system:
        cmd += ["--system-prompt", system]
    if model:
        cmd += ["--model", model]

    try:
        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude binary not found in PATH.\n"
            "Install Claude Code from https://claude.ai/code and run 'claude auth login'."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("claude CLI timed out after 300s.")

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI exited {result.returncode}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            text = data.get("result")
            if text is None:
                raise KeyError("no 'result' field in output")
        elif isinstance(data, list):
            result_event = next((e for e in data if isinstance(e, dict) and e.get("type") == "result"), None)
            if result_event is None:
                raise KeyError("no 'result' event found in output")
            text = result_event["result"]
        else:
            raise TypeError(f"unexpected output type: {type(data)}")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"claude CLI unexpected output ({e}): {result.stdout[:200]}")

    elapsed = time.time() - t0
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via claude CLI")
    return text


def chat_with_llm(
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
    on_token=None,
) -> str:
    """Dispatch a chat completion to the configured provider.

    If on_token is given, it's called with each text chunk as it streams —
    OpenRouter streams token by token, the Claude Agent SDK block by block;
    Anthropic and Claude CLI don't stream, so their full output is passed to
    on_token once at the end.
    """
    provider = resolve_provider(config)
    if provider == "claude_agent_sdk":
        return _chat_with_claude_agent_sdk(config, messages, temperature, max_tokens, on_token)
    if provider == "anthropic":
        text = _chat_with_anthropic(config, messages, temperature, max_tokens)
    elif provider == "claude_cli":
        text = _chat_with_claude_cli(config, messages, temperature, max_tokens)
    else:
        return chat_with_fallback(
            _make_openrouter_client(config), config, messages, temperature, max_tokens, on_token
        )
    if on_token and text:
        on_token(text)  # non-streaming providers: emit the whole output at once
    return text


def chat_with_fallback(
    llm: OpenAI,
    config: dict,
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 4096,
    on_token=None,
) -> str:
    primary = config.get("openrouter_model", "nvidia/nemotron-3-super-120b-a12b:free")
    fallbacks = config.get("openrouter_fallback_models", [])
    models = [primary] + [m for m in fallbacks if m != primary]

    for model_idx, model in enumerate(models):
        label = f"[model {model_idx + 1}/{len(models)}] {model}"
        for attempt in range(2):
            try:
                logger.debug(f"LLM call → {label} (attempt {attempt + 1})")
                t0 = time.time()
                if on_token:
                    text = _stream_chat(llm, model, messages, temperature, max_tokens, on_token)
                else:
                    resp = llm.chat.completions.create(
                        model=model,
                        messages=cast("Any", messages),
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    text = resp.choices[0].message.content or ""
                elapsed = time.time() - t0
                logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via {model}")
                return text
            except RateLimitError:
                if attempt == 0:
                    logger.warning(f"Rate-limited on {model} — retrying in 3s...")
                    time.sleep(3)
                    continue
                logger.warning(f"Rate-limited on {model} (quota exhausted) — trying next model...")
                break
            except Exception as e:
                logger.error(f"LLM error ({model}): {e}")
                break

    raise RuntimeError("All LLM models failed. Check your OpenRouter API key and quota.")
