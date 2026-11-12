## Why

The results list shows the same company and title many times. Today a job only
counts as "already seen" when its URL string matches exactly, but one posting
reaches a scan under many URLs: the careers-page link and a search hit,
tracking parameters (`utm_*`, `gh_src`, `lever-source`), a trailing slash or
`/apply`, `http` vs `https`, Workday's locale segment, or a company page that
embeds the Greenhouse board (`?gh_jid=`). Each variant is fetched, scored by the
LLM (costing tokens) and saved as a new row. Jobs reposted under a new ID add
more. The owner can't tell real repeats from genuinely separate openings.

## What Changes

- A job is identified by a **job key**: the applicant-tracking system's own job
  ID when the URL shows one (Greenhouse, Lever, Ashby, SmartRecruiters,
  Workable, Workday req ID), otherwise a canonical URL with tracking noise
  stripped.
- Discovery skips any link whose job key was already seen, and keeps one link
  per job key within a scan, so repeats aren't fetched or scored at all.
- Saved results fold rows that share a job key, or the same company + title +
  location (a repost), into one row. The row keeps the first link as its
  primary `url`, lists every link in `sources`, and keeps the furthest-along
  status (applied > not a fit > new).
- Existing duplicates are folded the next time the results are saved (a scan,
  or marking/deleting a result); the list as it was is kept once in
  `state/results.pre-dedupe.json` so it can be restored.
- The web UI shows folded rows once, with a "+N more links" list.
- Job history, the rescore queue, last-scan, CSV export and the Telegram top
  list use the same job key.
- No extra LLM calls; fewer, because repeats are no longer scored.

## Capabilities

### New Capabilities
- `job-results`: how scanned jobs are identified, de-duplicated and saved.

### Modified Capabilities
- None (no specs yet in `openspec/specs/`).

## Impact

- New `job_hunt/dedupe.py`; `job_hunt/scanner.py` and `job_hunt/web/routes.py`
  use it. Frontend `Scan.jsx` shows `sources`.
- `results.json` rows may gain a `sources` list. Older readers ignore it.
- ADR [0002](../../../docs/adr/0002-collapse-duplicate-job-listings.md).
