## Context

local-docker's app updater (its ADR 0034) reads `GET /api/health` → `revision`
and compares it with the newest image's `org.opencontainers.image.revision`
label. This app's images already carry that label: `docker/metadata-action`
sets it to the commit SHA. What's missing is the running app saying the same.

## Decisions

- **Build argument, not a file.** `ARG APP_REVISION=dev` then
  `ENV AUTOPILOT_REVISION=$APP_REVISION`, the same pattern as the art app. The
  publish workflow passes `APP_REVISION=${{ github.sha }}`. See
  [ADR 0007](../../../docs/adr/0007-health-reports-the-build-and-busy.md).
- **12 characters.** Enough to match the label's full SHA by prefix, which is
  how the updater compares.
- **Busy covers both runners.** A scan runs as a subprocess (`scan_runner`); a
  suggest or review job runs in a thread (`job_runner`). A container restart
  would cut either off, so either makes `busy` true.

## Risks

- The image now on the box predates this, so the first update the dashboard
  makes is judged by Unraid's view, and could land during a scan. A cut-off
  scan is simply rerun on the next schedule.
