## Why

The owner wants to see how much of his Claude plan each of his apps uses, on
the Claude card of his home dashboard (local-docker). The art app
(open-call-finder) already reports its share there. This app calls Claude
through the Agent SDK on the same subscription, but keeps no record of its
calls, so the card can't show it.

## What Changes

- Every Claude call this app makes through the **Claude (Agent SDK)** or
  **Claude Code CLI** provider is added to a ledger, worked or not:
  when, which feature, the model, tokens in and out, the API-rate cost
  estimate the SDK reports, how long it took and whether it worked. Never a
  prompt, a reply, the resume or a listing.
- The ledger is `state/claude_usage.jsonl` in the project folder (`/data` in
  Docker), so it survives image updates. Calls older than 90 days are dropped.
- **`GET /api/usage?since=<ISO time>`** returns the totals since then (default
  the last 7 days), overall and by feature, in the same shape the art app
  uses, so the home dashboard reads it with no new code on its side beyond
  knowing where this app is.
- Features: `scoring`, `drafts`, `company ideas`, `company review` and
  `search terms`.
- Nothing to set up and no new setting.

## Capabilities

### New Capabilities
- `claude-usage`: the app keeps a counts-only ledger of its Claude calls and
  reports it by feature.

### Modified Capabilities
- None.

## Impact

- New `job_hunt/usage.py` and `tests/test_usage.py`.
- `job_hunt/llm_utils.py`: `chat_with_llm` takes a `feature`; the Agent SDK and
  CLI providers record each call.
- `job_hunt/scanner.py`, `job_hunt/drafter.py`, `job_hunt/suggester.py`: name
  their feature.
- `job_hunt/web/routes.py`: `GET /api/usage`.
- No new dependency. The OpenRouter, Ollama and Anthropic API providers are
  not counted: they aren't on the Claude plan.
- ADR [0006](../../../docs/adr/0006-count-claude-calls-in-a-local-ledger.md).
