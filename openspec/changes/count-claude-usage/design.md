## Context

The home dashboard's Claude card shows this plan week's Claude use by app.
Each app on the plan keeps its own ledger and answers `GET /api/usage?since=`
with `{"total": {...}, "by_feature": {...}}`, where each total holds `calls`,
`failed`, `input`, `output`, `cache_read`, `cache_create` and
`cost_estimate_usd` (local-docker ADR 0032, open-call-finder ADR 0006).

This app's Agent SDK provider runs on the owner's Claude subscription: the
value on the Settings page's Claude (Agent SDK) card is his subscription
token, not a paid API key. The SDK's result still reports tokens and an
API-rate cost, which the card shows as an estimate of the plan's use.

## Goals / Non-Goals

**Goals:** count every Claude call on the plan, by feature; report it in the
art app's shape; nothing to set up; never store what was said.

**Non-Goals:** a usage view inside this app, limits or alerts, counting the
OpenRouter, Ollama or Anthropic API providers, changing how the app signs in
to Claude.

## Decisions

### 1. A JSON-lines ledger in the project's state folder
See [ADR 0006](../../../docs/adr/0006-count-claude-calls-in-a-local-ledger.md).

- **Count in memory:** lost on every restart and image update.
- **A table in a database:** this app keeps its state as JSON files and has no
  database.
- **One JSON line per call in `state/` (chosen):** the same as the art app,
  appends are cheap, and it lives in the mounted volume so it outlasts updates.

### 2. Counts only
The ledger holds when, feature, model, ok, the four token counts, the cost
estimate, duration and a short error. No prompt, reply, resume or listing
text, so the dashboard can read it without seeing anything personal.

### 3. Only the providers on the Claude plan
The Agent SDK and Claude Code CLI providers both run on the owner's Claude
sign-in, so both are counted. OpenRouter and Ollama aren't Claude; the
Anthropic provider bills an API key, which isn't the plan the card tracks.

### 4. The caller names the feature
`chat_with_llm(..., feature="scoring")`. A call that names none counts as
`other`. Guessing the feature from the prompt would break when a prompt
changes.

### 5. A failed write never fails the call
The call has already happened; a ledger write that fails is logged and the
reply is still returned.
