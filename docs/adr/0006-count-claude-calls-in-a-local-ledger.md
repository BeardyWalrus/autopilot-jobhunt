# 0006. Count Claude calls in a local, counts-only ledger

- **Status:** Accepted
- **Date:** 2026-11-16
- **OpenSpec change:** `openspec/changes/count-claude-usage/`

## Context

The owner wants to see how much of his Claude plan each app uses, on his home
dashboard (local-docker). This app's Claude (Agent SDK) provider runs on his
Claude subscription, so its calls count against the same plan as his other
apps. The dashboard reads each app's `GET /api/usage?since=`; the art app
(open-call-finder ADR 0006) set the shape.

## Decision

Every call through the Claude (Agent SDK) or Claude Code CLI provider adds one
JSON line to `state/claude_usage.jsonl` in the project folder: when, feature,
model, ok, input, output, cache-read and cache-create tokens, the cost
estimate the provider reports, duration and a short error. Never a prompt,
reply, resume or listing. Lines older than 90 days are dropped.
`GET /api/usage?since=` returns the totals overall and by feature in the art
app's shape. A ledger write that fails is logged and never fails the call.

## Alternatives

- **Count in memory:** lost on every restart and image update.
- **Ask Anthropic for usage:** a subscription has no usage API per app, and it
  couldn't split by feature.
- **Store prompts and replies too:** more than the card needs, and it would
  put the resume and listings where the dashboard reads.
- **Count every provider:** OpenRouter, Ollama and the Anthropic API key
  aren't the Claude plan the card tracks.

## Consequences

- The dashboard can show this app's share with no new code beyond its address.
- The cost is the SDK's API-rate estimate, not money spent on the subscription.
- A new Claude provider has to record its calls too, or it won't show.
