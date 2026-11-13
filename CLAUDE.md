# autopilot-jobhunt

AI job agent: scans 130+ company careers pages nightly, scores every role against your resume with an LLM (0–100), sends top matches via Telegram, and drafts tailored cover letters + resume bullets on demand.

## Commands for the owner

- **Use `gh`, not plain `git`.** Update a checkout on the owner's machines with
  `gh repo sync`, never `git pull`, and give each command as one complete line
  starting with `cd` and the checkout's full path.

## How we build features

- **Every feature starts with an OpenSpec change.** Before writing code for a
  new feature or a change in behaviour, create a change under
  `openspec/changes/<change-id>/` (`/opsx:propose`): `proposal.md` (why and
  what), `tasks.md`, spec deltas under `specs/`, and `design.md` listing each
  decision with the options weighed. Get the owner's go-ahead on the change
  before building, build from its tasks (`/opsx:apply`), and archive it once
  it ships (`/opsx:archive`) so `openspec/specs/` stays the current truth.
  Bug fixes, refactors and doc changes that don't change behaviour don't need
  one.
- **Lasting decisions get an ADR.** When a decision in `design.md` will
  outlive the change (a privacy rule, a storage, hardware or dependency
  choice, an interface other parts build on), also write
  `docs/adr/NNNN-short-title.md` from `docs/adr/template.md`, add it to the
  index in `docs/adr/README.md`, and link it from the change's `design.md`.
  ADRs aren't archived; to change one, write a new ADR that supersedes it.
  See [ADR 0001](docs/adr/0001-record-decisions-with-openspec-and-adrs.md).

## Keeping CI healthy

- **Check `main` after every merge.** A green PR doesn't make a green
  `main`. Once a PR merges, find the runs its merge commit started on `main`
  (`ci.yml` runs on every push to `main`) and wait for them to finish, e.g.
  `gh run list --branch main --commit <merge-sha>`. If one goes red, start
  fixing it straight away (a fix PR, or a revert if the fix isn't quick) and
  tell the owner what broke and what's being done. Don't just report it.
- **No silent re-runs.** A check that fails and then passes on a re-run is a
  flaky test, not a pass. Find the cause (timing, runner load, test order,
  shared state) before moving on, fix it or open an issue naming it, and say
  so in the PR.
- **Send an incident summary when something breaks.** When CI, a deploy or
  `main` breaks, tell the owner what broke, why, the fix, and what stops it
  happening again. Not just "done".

## Key commands

```bash
autopilot scan              # discover jobs, score with LLM, send Telegram notification
autopilot rescore           # retry scoring jobs whose LLM scoring failed (queued)
autopilot draft 1           # draft cover letter + resume for job #1 from last scan
autopilot draft https://... # draft for a specific job URL
autopilot export            # export last scan to CSV
autopilot export --min 70   # export only jobs with score >= 70
autopilot export --days 7   # export jobs from the past 7 days

python -m job_hunt.mcp_server  # start the MCP server (Claude Code / Claude Desktop)

autopilot web               # launch the web UI at http://127.0.0.1:8000
docker compose up --build   # run the web UI in Docker (recommended)
```

## Config files

| File | Controls | Gitignored? |
|---|---|---|
| `config.json` | Candidate profile, LLM settings, Telegram | Yes — copy from `config.example.json` |
| `.env` | API keys (TinyFish, OpenRouter, Telegram) | Yes — copy from `.env.example` |
| `companies.json` | List of companies to scan | No — committed, edit freely |
| `resume/YOUR_RESUME.md` | Your resume text (Markdown) | Yes — template committed |

## Package structure

```
job_hunt/
  scanner.py    — TinyFish API job discovery + LLM scoring pipeline
  drafter.py    — cover letter + tailored resume bullet generation
  notifier.py   — Telegram notification sender (optional, graceful if unconfigured)
  pay.py        — reads each role's pay from its listing text (never guessed; ADR 0005)
  llm_utils.py  — LLM dispatch: OpenRouter (default), Ollama, Claude Agent SDK, Anthropic API, or Claude Code CLI
  tools.py      — protocol-agnostic tool layer (wraps scanner/drafter/exporter)
  mcp_server.py — FastMCP server exposing scan_jobs, draft_application, export_jobs
  main.py       — CLI entry point (autopilot command)
  web/          — FastAPI web UI backend (routes, scan runner, scheduler)

frontend/       — React + Vite SPA (built into job_hunt/web/static)
```

## Web UI

A FastAPI + React app to manage config, job boards, resume, and scans from a browser.

```bash
docker compose up --build   # build locally — open http://127.0.0.1:8000
docker compose pull         # or pull the prebuilt image from GHCR, then: up -d
```

**Prebuilt image:** `ghcr.io/beardywalrus/autopilot-jobhunt-web:latest` (multi-arch
amd64/arm64), published by `.github/workflows/docker-publish.yml` on **every merge to
`main`** that touches the image (pushes `:latest` + `:sha-…`), so a fix is ready to
pull on Unraid as soon as it lands. A `v*` tag also pushes `:MAJOR.MINOR` +
`:MAJOR.MINOR.PATCH`, and a manual **Run workflow** (`workflow_dispatch`) pushes
`:latest`. PRs build the image to verify it but don't push. See
[ADR 0003](docs/adr/0003-publish-image-on-every-merge.md).

Docker seeds `./data` (config.json, companies.json, resume/, state/, output/) on
first run; edit everything from the **Settings**, **Job Boards**, and **Resume**
tabs. The **Scan & Results** tab runs a scan with a live streamed log and shows
scored jobs. Scans can also run on a daily schedule (Settings → Schedule).

- **Bind:** binds `0.0.0.0:8000` by default — reachable from other machines on
  your network. There is **no authentication**, so it exposes your config
  (including API keys) to anyone who can reach the host. For local-only access,
  run `autopilot web --host 127.0.0.1` (or map `127.0.0.1:8000:8000` in compose).
- **Run from source (no Docker):** `pip install -e '.[web]'`, then
  `cd frontend && npm install && npm run build`, then `autopilot web`.
  The SPA bundle (`job_hunt/web/static/`) is gitignored — build it or use Docker.
- **Scans** run as a subprocess of `autopilot scan`, so the live log is the same
  output the CLI produces and **Stop** actually terminates the run.

## Rate limits (free tier)

### TinyFish (job discovery)

- **Search:** 5 requests/min — scanner auto-paces, sleeps between batches
- **URL fetch:** 25 requests/min — auto-paced, no action needed
- **Free tier:** completely free, no credit card, no daily cap
- **Scan duration:** 30–90 min for 130+ companies is normal — deliberate pacing, not a bug
- **"No new jobs found":** TinyFish found no postings matching the query for that company today — not an error

### OpenRouter (LLM scoring + drafting)

- **Free tier:** no credit card needed, but each model has a **daily quota** (resets midnight UTC)
- **Fallback chain** (tried in order, auto-skips on quota exhaustion):
  1. `meta-llama/llama-3.3-70b-instruct:free` — primary
  2. `nvidia/nemotron-3-super-120b-a12b:free` — fallback 1
  3. `google/gemma-4-31b-it:free` — fallback 2
  4. `qwen/qwen3-coder:free` — fallback 3
- **Calls per scan:** ~10–30 LLM calls (jobs scored in small batches — default 5, set `score_batch_size`) — one nightly scan stays within all four models' free limits
- **"All LLM models failed":** all 4 models hit their daily quota — wait for midnight UTC reset, or add a small OpenRouter credit ($1–5) to remove the cap
- **Multiple scans/day:** risks exhausting free-tier quota — run once nightly via cron
- Check live per-model limits: [openrouter.ai/models](https://openrouter.ai/models)

### Ollama (LLM backend — local, no API key, no rate limits)

- **Cost:** free — models run locally on your own machine, no quota, no daily cap
- **Setup:** install from [ollama.com](https://ollama.com), then `ollama pull llama3.1`
- **Activate:** set `"llm_provider": "ollama"` in `config.json` or `LLM_PROVIDER=ollama` in `.env`
- **Model:** set `"ollama_model": "llama3.1"` (or `"mistral"`, `"qwen2.5"`, etc.)
- **Host:** defaults to `http://localhost:11434/v1`; override with `"ollama_base_url"` / `OLLAMA_BASE_URL` for a remote Ollama server
- **Rate limits:** none — bounded only by your local hardware
- **"Could not reach Ollama":** the server isn't running — start it with `ollama serve` and confirm the model is pulled (`ollama pull <model>`)

### Claude Agent SDK (LLM backend — Anthropic API key)

- **Setup:** Settings page → add **Claude (Agent SDK)** and paste the key (stored as `claude_agent_sdk_api_key` in `config.json`; `GET /api/config` returns it masked and a PUT of the mask keeps the stored key). Falls back to `anthropic_api_key` / `ANTHROPIC_API_KEY`
- **Activate:** `"llm_provider": "claude_agent_sdk"`
- **Model:** `"claude_agent_sdk_model"` / `CLAUDE_AGENT_SDK_MODEL` — default `claude-opus-5-5`; optional `"claude_agent_sdk_effort"`
- **Calls:** one-shot, `tools=[]`, `max_turns=1`, `setting_sources=[]`, strict empty MCP config. `claude-agent-sdk` is a core dependency; its wheel bundles the Claude Code CLI (no Node needed). 300s timeout per call
- **Cost:** billed per token on the Anthropic API key

### Claude Code CLI (LLM backend — no API key needed)

- **Cost:** uses your Claude subscription (Pro/Team/Enterprise)
- **Setup:** `claude auth login` — no API key required
- **Activate:** set `"llm_provider": "claude_cli"` in `config.json` or `LLM_PROVIDER=claude_cli` in `.env`
- **Model:** set `"claude_cli_model": "sonnet"` (or `"opus"`, `"haiku"`) — empty = Claude's default
- **Rate limits:** governed by your subscription tier, not a daily free quota
- **Cron / MCP note:** subprocess inherits user session auth — verify with `claude --print "hi"` in the same shell context before scheduling

## MCP registration (Claude Code)

See [SETUP.md §7](SETUP.md#step-7--register-with-claude-code-mcp) for the full setup.

Quick reference:
```bash
claude mcp add autopilot-jobhunt \
  --env TINYFISH_API_KEY=your_key \
  --env OPENROUTER_API_KEY=your_key \
  -- python -m job_hunt.mcp_server
# Then add "cwd": "/path/to/autopilot-jobhunt" in ~/.claude.json
```

MCP tools exposed: `scan_jobs`, `draft_application(job_ref)`, `export_jobs(min_score, days)`, `suggest_companies(count)`, `review_companies()`

## State files (gitignored)

- `state/last_scan.json` — job results from the most recent scan
- `state/results.json` — cumulative web-UI results (persist across scans, with applied/not-a-fit status)
- `state/rescore_queue.json` — jobs whose LLM scoring failed, awaiting retry (auto-drained at scan start, or `autopilot rescore`)
- `output/` — drafted cover letters and resume files
- `scan.log` — scan activity log (when using cron)
