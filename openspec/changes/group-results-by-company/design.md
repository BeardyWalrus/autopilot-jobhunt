## Context

The Scan tab's Results card renders `GET /api/results` (already sorted by score,
already de-duplicated by the `dedupe-job-listings` change) as one table. The
owner asked for "a sort by company" that shows each company with its roles,
instead of a list of roles.

## Goals / Non-Goals

**Goals:** see results per company with counts; keep the flat list; keep every
per-role action; no backend change.

**Non-Goals:** merging companies with different names (a parent and its
subsidiary, an agency and its client); changing CSV export or Telegram;
per-company actions such as "mark all not a fit".

## Decisions

### 1. Group in the browser, not the API

- **New API endpoint returning groups:** a second shape to keep in step with
  the flat one, and status changes would need to refresh both.
- **Group the already-loaded list in the browser (chosen):** the list is
  small (hundreds of rows), the optimistic status/delete updates keep working
  unchanged, and switching views needs no request.

### 2. A view switch, not a column sort

- **Click the Company column header to sort A–Z:** puts each company's roles
  together but still repeats the company on every row, with no counts and no
  way to fold a company away. Not what was asked.
- **Separate "By company" view with header rows (chosen):** one row per
  company with role count and best score, roles under it, collapsible.

### 3. Group by a normalised company name

- **Exact string:** `Acme Inc.` and `acme inc` (one from a careers page, one
  from a search hit) would show as two companies.
- **Lower-case, strip accents and punctuation, collapse spaces (chosen):** catches the
  variants seen in practice, matching how `dedupe.py` already normalises names.
  Legal suffixes (`Inc`, `Ltd`) are kept, so `Acme` and `Acme Inc` stay apart;
  stripping them risks merging unrelated firms and is easy to add later.

### 4. Companies A–Z by default, best score as an option

- **Best score only:** the brief was "sort by company", so names come first.
- **A–Z default with a best-score option (chosen):** A–Z answers the ask;
  best-score order keeps the "what should I look at first" use.

### 5. Remember view and sort in localStorage

- **Server-side setting:** a config write for a display preference.
- **localStorage, wrapped so a blocked store just falls back to defaults
  (chosen):** per-browser, no backend change. Collapsed companies aren't
  remembered; every company starts expanded.

### 6. Unit-test the frontend with Vitest in CI (ADR)

- **No frontend tests (today):** the grouping logic would ship untested, and
  CI never even builds the bundle, so a broken import only shows up in the
  Docker build after merge.
- **Jest:** needs Babel config for ESM/JSX alongside Vite.
- **Vitest (chosen):** shares Vite's config, runs ESM as-is, one dev
  dependency. The new `frontend` CI job runs `npm ci`, `npm test` and
  `npm run build` on every PR.

Recorded in [ADR 0004](../../../docs/adr/0004-test-the-web-frontend-in-ci.md).

## Risks / Trade-offs

- A company listed under two different names (`Acme` vs `Acme Corporation`)
  shows twice → acceptable; both are visible and A–Z puts them next to each
  other.
