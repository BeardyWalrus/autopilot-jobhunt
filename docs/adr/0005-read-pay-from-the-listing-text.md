# 0005. Read pay from the listing text, never from a model

- **Status:** Accepted
- **Date:** 2026-11-13
- **OpenSpec change:** `openspec/changes/show-role-pay/`

## Context

The owner wants each role's pay shown so he can weigh roles at a glance. The
scanner didn't record pay. A wrong figure is worse than none: he would judge a
role on a number the employer never offered. Model calls are billed per token
on his own key, and the scoring model only sees the first 1,500 characters of
a posting, while pay often sits at the end.

## Decision

Pay is read by **pattern matching on the listing's own text** (`job_hunt/pay.py`),
from the whole fetched page before it is trimmed, and shown exactly as the
listing words it. When no figure reads as pay, the role shows **"Not given"**.
No model is asked for pay, and no figure is ever converted or estimated.

## Alternatives

- **Add a `PAY:` field to the scoring prompt:** cheap, but the model sees too
  little of the page and tends to fill gaps with plausible figures.
- **A dedicated model call per role:** more cost on the owner's key, same risk
  of invented figures.
- **Market salary estimates (an external API):** not what the listing offers,
  and adds a dependency and a key.

## Consequences

- Pay costs nothing per role and is the same on every LLM provider.
- Unusual wording is missed and shows "Not given"; widening the patterns is a
  code change with tests, not a prompt tweak.
- Anything that later wants pay from another source (a board's structured
  `baseSalary`, say) must still copy the employer's figure, not estimate one,
  or supersede this ADR.
