# 0003. Publish the web image on every merge to main

- **Status:** Accepted
- **Date:** 2026-11-12
- **OpenSpec change:** none (CI only, no app behaviour change)

## Context

`docker-publish.yml` pushed `:latest` only on a `v*` tag or a manual run, so
changes could pile up on `main` and ship together in a release. In practice no
release was cut after July, so fixes merged since then (the Claude Agent SDK
provider, duplicate-listing folding) never reached the owner's Unraid container,
which pulls `ghcr.io/beardywalrus/autopilot-jobhunt-web:latest`. The owner asked
for the image to publish on merge, like local-docker.

## Decision

Every push to `main` that touches the image (`Dockerfile.web`, `docker/`,
`frontend/`, `job_hunt/`, `pyproject.toml`, the workflow) builds and pushes
`:latest` and `:sha-…`. Release tags and manual runs keep working. A
concurrency group per ref cancels an older run when a newer merge lands, so an
older build can't overwrite `:latest` last.

## Alternatives

- **Keep release-only publishing:** every fix needs a tag or a manual run, which
  was forgotten for months.
- **Publish on every push to main, no path filter:** rebuilds a multi-arch image
  for docs-only merges for nothing.
- **A separate `:edge` tag for main, `:latest` for releases:** the owner's
  container would still need re-pointing, and releases aren't being cut.

## Consequences

- `:latest` is whatever is on `main`; `main` must stay releasable, which the CI
  rules in CLAUDE.md already require (check `main` after every merge).
- More GHCR pushes and Actions minutes per merge (multi-arch build).
- Pinning to a known version still works via `:sha-…` or a release tag.
