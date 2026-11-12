## Context

Jobs were de-duplicated by exact URL string in four places: the seen-jobs
memory (discovery), `results.json`, `job_history.json` and the rescore queue.
Real-world URLs for one posting vary a lot, so the same job came through again
and again. The owner reported many rows with the same company and title.

## Goals / Non-Goals

**Goals:** stop the same posting being fetched, scored and listed twice; fold
the duplicates already saved, reversibly; keep genuinely different jobs apart.

**Non-Goals:** cross-company matching (agency reposts of a client's job); using
the LLM to judge sameness; changing how the seen-jobs memory is stored.

## Decisions

### 1. Identify a job by ATS job ID, else canonical URL (ADR)

- **Exact URL string (today):** misses every tracking/slash/scheme variant.
- **Canonical URL only:** fixes tracking noise but not the same job on the
  board vs a company page embedding it (`?gh_jid=`), or Workday locale paths.
- **ATS job ID, falling back to canonical URL (chosen):** the ID is what the
  employer uses for the posting, so it survives every link variant we see.
  Unknown boards still get the canonical-URL fallback.

Recorded in [ADR 0002](../../../docs/adr/0002-collapse-duplicate-job-listings.md).

### 2. Also fold same company + title + location (ADR)

- **Job key only:** a job reposted under a new ID still shows twice.
- **Company + title only:** would merge different jobs in different cities.
- **LLM "same job?" check:** costs tokens per pair on a per-token key, and is
  slower and less predictable.
- **Company + title + location, normalised (chosen):** catches reposts at no
  cost. The risk is two real openings with identical title and location at one
  company; they show as one row, but every link stays in `sources`, so nothing
  is hidden.

### 3. Fold into one row with `sources`, not delete

- **Drop the later copy:** loses links and possibly a status the owner set.
- **Keep copies, hide in UI only:** the CSV, Telegram and history still repeat.
- **One row, every link in `sources`, furthest-along status wins (chosen).**

### 4. Clean up existing rows lazily, with a one-time backup

- **Migration command:** one more step for the owner to run.
- **Fold on next save + `results.pre-dedupe.json` backup (chosen):** happens on
  its own at the next scan or status change; the backup is written once and
  never overwritten, so it can be restored by copying it back.
- `GET /api/results` folds for display but doesn't write, so it can't race a
  running scan's checkpoint.

## Risks / Trade-offs

- Two genuinely separate openings with the same title and location fold
  together → both links remain under "+N more links".
- The fallback location is the company's default when the LLM finds none, so
  two such jobs in different cities could fold → same mitigation.
