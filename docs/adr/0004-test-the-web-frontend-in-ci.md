# 0004. Test the web frontend in CI with Vitest

- **Status:** Accepted
- **Date:** 2026-11-13
- **OpenSpec change:** `openspec/changes/group-results-by-company/`

## Context

The React frontend in `frontend/` had no tests and CI never built it. Only the
Python package was linted and tested; the bundle was first built in the Docker
image after a merge to `main`. The "By company" results view adds real logic
(grouping, name matching, sort orders) to the frontend, and our rule is that a
new kind of code gets a CI check alongside it, not later.

## Decision

Unit-test frontend logic with **Vitest**, kept in pure modules beside the
components (`src/*.js` with `src/*.test.js`). A `frontend` job in `ci.yml` runs
`npm ci`, `npm test` and `npm run build` on every pull request and push to
`main`, on the same runner choice as the Python job.

## Alternatives

- **No frontend tests:** grouping bugs and broken imports would only show up
  in the browser or in the post-merge Docker build.
- **Jest:** needs a separate Babel setup for ESM and JSX next to Vite.
- **Component tests with jsdom and Testing Library now:** more dependencies
  than the current logic needs; can be added later on top of Vitest.

## Consequences

- Frontend logic worth testing goes in plain functions, not inside components.
- `vitest` is a dev dependency; it isn't in the built bundle or the image.
- A PR that breaks the frontend build now fails CI before merge.
