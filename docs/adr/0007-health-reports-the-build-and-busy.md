# 0007. The health check reports the build and whether the app is busy

- **Status:** Accepted
- **Date:** 2026-11-16
- **OpenSpec change:** `openspec/changes/report-build-for-updates/`

## Context

The owner's home dashboard (local-docker) keeps his other apps on their newest
image. It counts an update as done only when the app reports the new build,
and it holds off while an app is busy so a restart doesn't cut work off.

## Decision

The image records its commit through the `APP_REVISION` build argument (the
publish workflow passes the commit SHA), and `GET /api/health` returns it as
`revision` (12 characters, or `dev`), along with `busy`, true while a scan or a
company job is running.

## Alternatives

- **Let the dashboard trust Unraid's "update available".** It has been stale
  before and says nothing about what the container runs afterwards.
- **A separate `/api/build` endpoint.** The dashboard already reads
  `/api/health` from each app; one more field there needs no new route.

## Consequences

- Updates can be confirmed, the same way as the art app's.
- `busy` must cover any new long-running work added later.
