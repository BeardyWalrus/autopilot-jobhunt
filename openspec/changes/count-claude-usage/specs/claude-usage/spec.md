## ADDED Requirements

### Requirement: Every Claude call on the plan is counted
The app SHALL add one entry to its usage ledger for each call it makes through
the Claude (Agent SDK) or Claude Code CLI provider, whether the call worked or
not. An entry SHALL hold only when, the feature, the model, whether it worked,
the input, output and cache token counts, the cost estimate the provider
reports, the duration and a short error. It SHALL NOT hold any prompt, reply,
resume or listing text.

#### Scenario: A scoring call works
- **WHEN** a scan scores a batch of roles through the Agent SDK
- **THEN** the ledger gains one entry for `scoring` with its token counts and cost estimate

#### Scenario: A call fails
- **WHEN** an Agent SDK call times out
- **THEN** the ledger gains one entry marked failed, and the call's error is still raised

#### Scenario: A provider that isn't on the plan
- **WHEN** the app scores through OpenRouter or Ollama
- **THEN** the ledger is unchanged

#### Scenario: The ledger can't be written
- **WHEN** writing the ledger fails
- **THEN** the call's reply is still returned

### Requirement: Usage is reported by feature
`GET /api/usage` SHALL return the calls since `since` (an ISO date and time;
default the last 7 days) as `total` and `by_feature`, each with `calls`,
`failed`, `input`, `output`, `cache_read`, `cache_create` and
`cost_estimate_usd`.

#### Scenario: The dashboard asks for this plan week
- **WHEN** it asks with `since` set to the start of the plan week
- **THEN** only calls from then on are counted

#### Scenario: A since that isn't a time
- **WHEN** `since` is `yesterday`
- **THEN** the reply is a 422

### Requirement: Old calls are dropped
Calls older than 90 days SHALL be removed from the ledger.

#### Scenario: A call from four months ago
- **WHEN** the ledger is pruned
- **THEN** that call is gone and newer calls stay
