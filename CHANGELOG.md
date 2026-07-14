# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Dates are omitted for pre-1.0 releases that predate this changelog and were
reconstructed from git history.

## [Unreleased]

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
