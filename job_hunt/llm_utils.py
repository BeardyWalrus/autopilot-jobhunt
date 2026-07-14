import json
import os
import subprocess
import time
from typing import Any, cast

from openai import APIConnectionError, OpenAI, RateLimitError

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


def _make_ollama_client(config: dict) -> OpenAI:
    base_url = config.get("ollama_base_url") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    return OpenAI(
        # Ollama ignores the API key, but the OpenAI SDK refuses to start without
        # a non-empty one — "ollama" is the conventional placeholder.
        api_key=config.get("ollama_api_key") or os.getenv("OLLAMA_API_KEY") or "ollama",
        base_url=base_url,
        timeout=_LLM_REQUEST_TIMEOUT,
    )


def list_ollama_models(base_url: str | None = None, config: dict | None = None) -> list[str]:
    """Return the model names installed on the Ollama server.

    Uses Ollama's OpenAI-compatible /models endpoint. Raises RuntimeError with a
    friendly message if the server can't be reached.
    """
    cfg = config or {}
    url = base_url or cfg.get("ollama_base_url") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    client = OpenAI(
        api_key=cfg.get("ollama_api_key") or os.getenv("OLLAMA_API_KEY") or "ollama",
        base_url=url,
        timeout=10.0,
    )
    try:
        resp = client.models.list()
    except APIConnectionError:
        raise RuntimeError(
            f"Could not reach Ollama at {url}. Is it running? Start it with 'ollama serve'."
        )
    return sorted(m.id for m in resp.data)


def _stream_chat(llm: OpenAI, model: str, messages: list[dict], temperature: float,
                 max_tokens: int, on_token) -> str:
    """Stream a chat completion, calling on_token(delta) for each chunk. Returns
    the full text. Used by the OpenAI-compatible providers (Ollama, OpenRouter)
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


def _chat_with_ollama(config: dict, messages: list[dict], temperature: float,
                      max_tokens: int, on_token=None) -> str:
    model = config.get("ollama_model", "llama3.1")
    client = _make_ollama_client(config)
    logger.debug(f"LLM call → Ollama / {model} @ {client.base_url}")
    t0 = time.time()
    try:
        if on_token:
            text = _stream_chat(client, model, messages, temperature, max_tokens, on_token)
        else:
            resp = client.chat.completions.create(
                model=model,
                messages=cast("Any", messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content or ""
    except APIConnectionError:
        raise RuntimeError(
            f"Could not reach Ollama at {client.base_url}. Is it running?\n"
            f"  Start the server:  ollama serve\n"
            f"  Pull the model:    ollama pull {model}"
        )
    elapsed = time.time() - t0
    logger.debug(f"LLM response: {len(text)} chars in {elapsed:.1f}s via ollama/{model}")
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
    Ollama and OpenRouter stream natively; Anthropic and Claude CLI don't, so
    their full output is passed to on_token once at the end.
    """
    provider = config.get("llm_provider")
    if provider == "ollama":
        return _chat_with_ollama(config, messages, temperature, max_tokens, on_token)
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
