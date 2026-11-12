# 0002. Identify jobs by ATS job ID and fold repeat listings

- **Status:** Accepted
- **Date:** 2026-11-12
- **OpenSpec change:** `openspec/changes/dedupe-job-listings/`

## Context

Jobs were de-duplicated by their exact URL string. One posting reaches a scan
under many URLs (tracking parameters, trailing slashes, `/apply`, `http`/`https`,
Workday locales, a company page embedding the Greenhouse board), and employers
repost jobs under new IDs. The results list filled with the same company and
title, and each repeat cost a fetch and LLM scoring on a per-token key.

## Decision

A job's identity is its **job key**: the applicant-tracking system's job ID when
the URL shows one, otherwise its canonical URL (`job_hunt/dedupe.py`). Discovery,
results, history, the rescore queue, CSV and Telegram all compare job keys.

Saved results also fold rows with the same company, title and location
(normalised) into one, as a repost. A folded row keeps its first URL as `url`,
lists every link in `sources`, and keeps the furthest-along status. Nothing is
deleted: the first fold writes the old list to `state/results.pre-dedupe.json`.

## Alternatives

- **Canonical URL only:** misses the same job on a board and on a company page.
- **Company + title only:** merges different jobs in different cities.
- **Ask the LLM whether two listings are the same job:** costs tokens per pair,
  slower, and not repeatable.
- **Hide duplicates in the UI only:** CSV, Telegram and history still repeat,
  and repeats are still scored.

## Consequences

- Fewer fetches and LLM calls per scan.
- Two real openings with identical company, title and location show as one row;
  both links stay visible under "+N more links".
- New boards need a pattern in `ats_job_id` to get ID matching; until then they
  fall back to the canonical URL.
- `results.json` rows may carry a `sources` list that other code must tolerate.
