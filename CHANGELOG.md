# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Dates are omitted for pre-1.0 releases that predate this changelog and were
reconstructed from git history.

## [Unreleased]

### Changed
- **Docker image now publishes at release time only.** The GHCR `:latest` image is
  pushed on a `v*` tag or a manual **Run workflow**, not on every merge to `main`.
  PRs still build the image to verify it, but don't push. This lets several changes
  accumulate on `main` and ship together when a release is cut.

## [0.12.1] — 2026-07-14

### Fixed
- **Mobile layout.** The top bar no longer overflows the screen (it wrapped the
  brand, four tabs, and version onto one row, forcing the whole page to scroll
  sideways) — the tabs now sit on their own horizontally-scrollable row. Card
  header rows (title + search/filter/actions) stack instead of cramming, and
  inputs/selects fill the width rather than being clipped to a sliver. Verified
  at 390px with zero horizontal page overflow.

## [0.12.0] — 2026-07-14

### Added
- **Delete scan results** — each row on the Scan tab's Results table now has a
  **delete** action, plus a **clear all** button. Deleting a result leaves its
  URL in the seen-jobs memory (so it won't re-appear next scan) and keeps your job
  history intact. Backed by `DELETE /api/results` (by URL) and `DELETE /api/results/all`.

## [0.11.0] — 2026-07-14

### Changed
- **Jobs are now scored in batches of 5 (was 10).** A large batch was the main
  cause of unparseable scoring output — small/local models truncate or drift when
  asked to score 10 jobs at once. Smaller batches keep the prompt short and parse
  far more reliably. Configurable via the top-level `score_batch_size` (1–20) and
  a new field in Settings → Diagnostics.

### Docs
- Corrected docs that described the scorer as returning "JSON" — it asks for a
  simpler `KEY: value` block per job (the parser still accepts JSON as a fallback).

## [0.10.0] — 2026-07-14

### Added
- **Suggest search terms from your résumé** (Settings → Job search terms): a
  button that asks the LLM to propose keywords + seniority from your résumé and
  profile, streams its thinking live, and fills the fields for you to edit before
  saving. Runs on the shared background job runner, so it survives navigating away.
- **View / edit previously seen jobs** (Scan tab): the seen-URL memory is no
  longer a black box — expand it to see the URLs the scanner skips and remove
  individual ones so just those jobs are re-discovered and re-scored next scan.
  Backed by `GET /api/scan/seen?limit=` and `PUT /api/scan/seen`.

## [0.9.0] — 2026-07-14

### Added
- **Editable job-search terms** in Settings → Candidate: "Search keywords" and
  "Search seniority" fields that build the per-company query
  (`site:domain (seniority) (keywords)`). Previously these were hardcoded to
  ML/data-science defaults and only changeable by editing config.json — now you
  can tune what's actually searched for your own field from the browser.

## [0.8.0] — 2026-07-14

### Added
- **Scan log level** setting (Settings → Diagnostics): switch the scan log between
  INFO and DEBUG from the browser. DEBUG shows per-URL/per-job detail and the raw
  LLM output. (The full DEBUG log is always written to `scan.log` regardless.)
- **Forget scanned history** button (Scan tab): clears the scanner's seen-jobs
  memory so the next scan re-discovers and re-scores every job. Saved results are
  kept — only the "already seen, skip it" list is cleared.

### Changed
- Scoring failures are now **debuggable from the normal scan log** — when the LLM
  output can't be parsed, the raw output is logged at ERROR (not DEBUG), with a
  targeted hint when the model returned almost nothing (e.g. a reasoning model
  that spent its token budget, a too-small local model, or a quota limit).

### Fixed
- A scoring/LLM failure no longer **silently drops** a batch of jobs. Previously a
  parse failure returned no results while the jobs were still marked "seen," so
  they were lost and never retried; they're now saved unscored (matching the
  existing behavior for LLM call errors).

## [0.7.0] — 2026-07-14

### Added
- **Reconsider my off boards** — a third Job Boards button that looks through the
  currently-disabled boards and recommends any that are actually a good fit for
  your resume, with a one-click **Enable** to turn each back on. The inverse of
  "Review my list for poor fits."

### Fixed
- Scans no longer try to send a **Telegram** notification when Telegram was never
  set up — the shipped placeholder token/chat_id values are now treated as
  unconfigured, so the scan cleanly relies on the CSV instead of erroring.

## [0.6.0] — 2026-07-14

### Added
- Configure **multiple LLM providers** in Settings at once (OpenRouter, Ollama,
  Anthropic, Claude CLI), each with its own model/key fields, and pick the
  active one with a radio ("use this one").
- Ollama Settings gained a **model dropdown** (populated from the server) and a
  **Test** connection button.
- **Sortable Job Boards columns** — click a header to sort asc/desc/off.
- Disabled job boards are hidden by default with a "Show off" toggle.

### Changed
- **Suggest / Review stream the model's output live** — tokens appear in the job
  log as they're generated (Ollama / OpenRouter), so slow local runs are visible.

## [0.5.0] — 2026-07-14

### Added
- **Web UI** — a FastAPI + React app to manage everything from a browser
  (`autopilot web`, or `docker compose up`). Tabs: Settings, Job Boards,
  Resume, and Scan & Results with a live streamed scan log.
- **Docker + GHCR** — `Dockerfile.web` / `docker-compose.yml`, and a workflow
  that publishes a multi-arch image to `ghcr.io/<owner>/autopilot-jobhunt-web`.
- **Ollama provider** — run models locally, no API key, no rate limits
  (`llm_provider: "ollama"`). Settings offers a model dropdown populated from
  the server plus a connection Test button.
- **Suggest companies from your resume** — new tool across web, MCP
  (`suggest_companies`), and CLI (`autopilot suggest`).
- **Review companies for poor fits** — flags tracked companies unlikely to fit,
  across web, MCP (`review_companies`), and CLI (`autopilot review-companies`).
- **Disable job boards** without deleting them (`"enabled": false`); disabled
  boards are skipped on scans and hidden from the UI by default (with a toggle).
- Live streamed logs for the Suggest/Review jobs, so slow/failed LLM calls are
  visible instead of a silent spinner.

### Changed
- Scans now **checkpoint results and seen URLs after every batch of 10** (not
  just per company), so an interrupted scan re-does at most one batch. Fetch and
  scoring report per-batch progress at INFO.
- **Tolerant scoring output parsing** — the scorer accepts a simple `KEY: value`
  block format (with a JSON fallback), so small local models no longer score
  nothing on malformed JSON.

## [0.4.4] — 2026-07-09

### Added
- Job discovery search query is now config-driven: `candidate.search_seniority`
  / `candidate.search_keywords` in `config.json` shape the `site:<domain>`
  query sent to TinyFish per company. Empty/absent falls back to the previous
  hardcoded senior/staff ML/DS terms, so existing configs behave identically.
  Closes #24.

### Fixed
- `job_hunt/__init__.py` `__version__` re-synced with `pyproject.toml` (had
  drifted to a stale `0.4.1` across the last two releases).

## [0.4.3] — 2026-07-05

### Added
- MCP tools now ship full metadata: per-tool `ToolAnnotations` (title, readOnly/
  destructive/idempotent/openWorld hints), per-parameter descriptions via
  `Annotated[..., Field(...)]`, and structured output schemas (FastMCP auto).
  Improves registry quality scoring and host UX.

### Changed
- `mcp` extra now requires `mcp>=1.9` (ToolAnnotations support).

## [0.4.2] — 2026-07-05

> Note: 0.4.1 was recorded here but never uploaded to PyPI (latest there was 0.4.0);
> 0.4.2 supersedes it everywhere (PyPI, MCP registries).

### Added
- PEP 561 `py.typed` marker + `Typing :: Typed` and explicit Python 3.11/3.12/3.13
  classifiers on PyPI.
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist including the drafts-only invariant.
- README: `mcp-name` ownership marker (Official MCP Registry) and registry-status line.

## [0.4.1] — 2026-07-03

### Added
- CI hardening: Python 3.13 in the test matrix, pip caching, and a `gitleaks`
  secret-scan job.
- Formal test scaffold: `pytest.ini` and a shared `conftest.py` (`fake_llm`,
  `clean_env`, `sample_config`, `sample_job` fixtures).
- Coverage gate (`--cov=job_hunt`, `fail_under = 85`) plus a mocked test suite
  raising coverage from ~36% to ~90%.
- `mypy` type checking with `job_hunt/` fully annotated; enforced in CI.
- GitHub issue templates (bug report, feature request).
- `skills/autopilot-jobhunt/SKILL.md` — a Claude Code usage skill that drives the hunt
  via the MCP tools.
- MCP registry manifests: `server.json` (official MCP Registry) and `smithery.yaml`.
- `autopilot mcp` subcommand to launch the stdio MCP server from the installed console
  script.
- `autopilot-jobhunt` console-script alias (== the PyPI distribution name) so
  MCP-registry runners that derive the command from the package name resolve
  correctly.
- `docs/` guide set: install, providers, API keys, scanning, integrations, MCP,
  config/scoring, troubleshooting, and a testing checklist.
- `SECURITY.md`, `PRIVACY.md`, and this `CHANGELOG.md`.

### Fixed
- `job_hunt/__init__.py` `__version__` corrected from a stale `0.1.0` to track the
  packaged version.

## [0.4.0]

### Added
- `glama.json` for Glama MCP ownership/indexing and a Glama quality badge.
- `Dockerfile` and OCI image labels for the Glama MCP listing and ghcr package linking.
- Demo GIF and star CTA in the README.
- `LOG_LEVEL` env honored for console verbosity.

### Changed
- Scanner always saves results to CSV and logs a provider-aware startup line.

## [0.3.1]

### Fixed
- Compose `config.json` and `.env` correctly (placeholder guard so the default `.env`
  template no longer clobbers real config values).
- `export` works without API keys (reads local scan state only).
- Added per-request timeouts to OpenRouter and Anthropic calls.
- Handle both dict and list JSON shapes from the Claude CLI output.

## [0.3.0]

### Added
- `claude_cli` LLM provider (score/draft via the local `claude` CLI, no API key).

## [0.2.0]

### Added
- pip-install workflow with `autopilot init` scaffolding.
- Structured logging and CSV fallback when Telegram send fails.
- Anthropic/Claude as an optional LLM provider.
- `SETUP.md` and `CLAUDE.md`.

### Changed
- Renamed the package and repository to `autopilot-jobhunt`.

## [0.1.0]

### Added
- Initial open-source release: nightly careers-page scan, LLM resume scoring,
  Telegram alerts, and on-demand resume + cover-letter drafting.
