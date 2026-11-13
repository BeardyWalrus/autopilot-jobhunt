## Why

Now that repeat listings fold into one row, the owner wants to see the results
by company: each company once, with its roles under it. Today the Scan tab
shows one flat list sorted by score, so a company with six openings is spread
through the list and it's hard to see who is hiring what.

## What Changes

- The Results card on the Scan tab gets a **View** switch: **All roles** (the
  flat list, as today) or **By company**.
- **By company** shows one header row per company with its role count and best
  score, and that company's roles under it, best score first.
- Companies sort **A–Z** by default, or by **best score**.
- Each company collapses and expands on its own; **Expand all** and
  **Collapse all** act on every company at once. Companies start expanded.
- Rows that differ only in case, accents, spacing or punctuation of the company name
  (`Acme Inc.` and `acme inc`) group together under the first spelling seen.
- Every per-role action stays: Applied, Not a fit, Apply link, +N more links,
  delete. **Hide handled** filters both views, and a company whose roles are
  all handled drops out while it's on.
- The chosen view and sort are remembered in the browser.
- The web frontend gets unit tests (Vitest) and a CI job that runs them and
  builds the bundle.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `job-results`: adds how saved results are shown, flat or grouped by company.

## Impact

- New `frontend/src/grouping.js` (pure grouping/sorting) and its test;
  `frontend/src/components/Scan.jsx` renders both views; small CSS additions.
- `frontend/package.json` gains Vitest and a `test` script; `ci.yml` gains a
  `frontend` job (install, test, build).
- No backend or API change; `GET /api/results` is unchanged.
- ADR [0004](../../../docs/adr/0004-test-the-web-frontend-in-ci.md).
