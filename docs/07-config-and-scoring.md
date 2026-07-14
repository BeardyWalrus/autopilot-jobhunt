# 07 — Config & scoring

Two files hold your setup. Both are gitignored; copy them from the committed examples.

| File | Holds | Copy from |
|---|---|---|
| `config.json` | candidate profile, LLM provider, scoring thresholds, Telegram | `config.example.json` |
| `.env` | API keys | `.env.example` |

`autopilot init` writes both for you. `.env` values override `config.json`, except that
a `your_..._here` placeholder never clobbers a real `config.json` value.

## Candidate profile

The scoring quality depends on this section — the LLM reads it plus your full resume.

```jsonc
{
  "tinyfish_api_key": "sk-tinyfish-...",
  "openrouter_api_key": "sk-or-v1-...",
  "llm_provider": "openrouter",
  "candidate": {
    "name": "Your Name",                        // appears in drafted cover letters
    "resume_path": "resume/YOUR_RESUME.md",     // your resume (Markdown)
    "profile": "8 YOE ML Engineer. Python, LLMs, AWS, MLOps.",
    "seeking": "Remote EU or NA roles, open to relocation",   // positive signal — scores higher
    "not_suitable": "Junior roles, pure front-end, no-ML SWE", // negative filter — scores lower
    "search_seniority": "junior OR entry OR associate",
    //                   ↑ optional — drives job DISCOVERY (the search query itself),
    //                     not scoring. Empty/absent falls back to "senior OR staff
    //                     OR principal OR lead".
    "search_keywords": "\"full stack developer\" OR \"react developer\"",
    //                  ↑ optional — same discovery mechanism. Empty/absent falls back
    //                    to the default ML/DS role terms below.
    "min_score": 65,   // jobs below this are not saved or drafted
    "top_n": 5         // how many top matches go in the Telegram notification
  }
}
```

`profile` / `seeking` / `not_suitable` only affect **scoring** (how a discovered job
is judged) — they never change what gets searched for. `search_seniority` /
`search_keywords` are the only fields that shape **discovery** (the `site:` search
query sent to TinyFish). If your profile doesn't match the default senior ML/DS
search terms, set these two fields or you'll mostly discover jobs that can't score
well regardless of your resume.

## Your resume

Replace `resume/YOUR_RESUME.md` with your real work history (plain Markdown — headings +
bullets). The LLM reads the **full text** when scoring each job, so specific detail
(exact tools, project scale, years per role) directly improves accuracy. A thin resume
yields low-confidence scores.

## Scoring model

Each job gets a 0–100 score with a one-line rationale. The bands (from the scoring
prompt):

| Score | Meaning |
|---|---|
| 80–100 | near-perfect fit |
| 60–79 | good fit |
| 40–59 | partial fit |
| < 40 | poor fit |

- **`min_score`** — the save/draft threshold. 60–70 is a good starting range. Jobs below
  it are discarded from results.
- **`top_n`** — how many of the passing matches are pushed to Telegram (all passing jobs
  still land in the CSV and `last_scan.json`).
- **`score_batch_size`** — how many jobs are scored per LLM call (top-level config key,
  1–20, default 5). Lower it if the model returns unparseable output — a shorter prompt
  is easier for small/local models to complete and format; the trade-off is more LLM calls.

Tune `min_score` up if you get too many marginal matches, down if you get too few.

## Provider selection

Set `llm_provider` to `openrouter` (default), `claude_cli`, or `anthropic` — see
[02 — LLM providers](02-providers.md) for each backend's keys and models. Override at
runtime without editing config: `LLM_PROVIDER=claude_cli autopilot scan`.

## Next

- [08 — Troubleshooting](08-troubleshooting.md)
- [09 — Testing checklist](09-testing-checklist.md)
