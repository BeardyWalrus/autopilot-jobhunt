## Why

The owner's home dashboard (local-docker) keeps the art app on its newest image
by itself, and he wants it to do the same for this app. The dashboard only
counts an update as done once the app reports the new build, and it waits
while the app is in the middle of work so a restart doesn't cut it off. This
app's `GET /api/health` says neither which build it is nor whether it's busy,
so the dashboard would have to trust Unraid's own "update available" view,
which has been stale before.

## What Changes

- The web image records the commit it was built from (`APP_REVISION` build
  argument, set by the publish workflow to the commit SHA, read at run time
  from `AUTOPILOT_REVISION`). A local build says `dev`.
- `GET /api/health` adds:
  - `revision`: the first 12 characters of that commit, or `dev`;
  - `busy`: true while a scan or a company job (suggest or review) is running.
- Nothing to set up; the existing fields stay as they were.

## Capabilities

### New Capabilities
- `web-health`: the health endpoint reports the build and whether the app is busy.

## Impact

- `Dockerfile.web`, `.github/workflows/docker-publish.yml`, `job_hunt/web/routes.py`.
- Tests in `tests/test_web_api.py`.
- ADR 0007.
