# Architecture decision records

One short note per decision that should outlive the feature it came from: a
privacy rule, a storage, hardware or dependency choice, an interface other
parts build on. The OpenSpec change says **what** the app does; an ADR says
**why** we chose this way of doing it, so nobody undoes it without knowing.

## How to add one

1. Copy [`template.md`](template.md) to `NNNN-short-title.md`, using the next
   free number.
2. Fill in context, decision, alternatives and consequences. Link the
   OpenSpec change it came from, and link the ADR back from that change's
   `design.md`.
3. Add a row to the index below.

ADRs are never archived and rarely edited. To change a decision, write a new
ADR that supersedes the old one, and set the old one's status to
`Superseded by NNNN`.

## Index

| # | Decision | Status | Date |
|---|----------|--------|------|
| [0001](0001-record-decisions-with-openspec-and-adrs.md) | Start every feature with an OpenSpec change and record lasting decisions as ADRs | Accepted | 2026-11-05 |
| [0002](0002-collapse-duplicate-job-listings.md) | Identify jobs by ATS job ID and fold repeat listings | Accepted | 2026-11-12 |
| [0003](0003-publish-image-on-every-merge.md) | Publish the web image on every merge to main | Accepted | 2026-11-12 |
| [0004](0004-test-the-web-frontend-in-ci.md) | Test the web frontend in CI with Vitest | Accepted | 2026-11-13 |
| [0005](0005-read-pay-from-the-listing-text.md) | Read pay from the listing text, never from a model | Accepted | 2026-11-13 |
