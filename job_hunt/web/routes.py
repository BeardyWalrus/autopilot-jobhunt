"""HTTP API for the web UI.

All endpoints operate on the project directory (see paths.py) so the CLI and
the UI read and write the same config.json / companies.json / resume / state.
"""
import json
import queue
from importlib import resources
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from job_hunt.web import paths
from job_hunt.web.job_runner import runner as jobs
from job_hunt.web.scan_runner import runner
from job_hunt.web.scheduler import read_schedule, scheduler, write_schedule

router = APIRouter(prefix="/api")

_REQUIRED_COMPANY_KEYS = ("name", "careers_url", "search_domain", "location", "region")


def _read_json(path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"{path.name} is not valid JSON: {e}")


def _config_template() -> dict:
    """The shipped example config, used to seed the settings page on first run."""
    try:
        text = resources.files("job_hunt.data").joinpath("config.example.json").read_text()
        return json.loads(text)
    except Exception:
        return {"llm_provider": "openrouter", "candidate": {}}


# --- health -------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    try:
        from importlib.metadata import version
        ver = version("autopilot-jobhunt")
    except Exception:
        ver = "unknown"
    return {"status": "ok", "version": ver, "project_dir": str(paths.project_dir())}


# --- config -------------------------------------------------------------------

@router.get("/config")
def get_config() -> dict:
    cfg = _read_json(paths.config_path(), None)
    if cfg is None:
        return {"config": _config_template(), "exists": False}
    return {"config": cfg, "exists": True}


@router.put("/config")
def put_config(config: dict = Body(...)) -> dict:
    if not isinstance(config, dict):
        raise HTTPException(400, "config must be a JSON object")
    paths.config_path().write_text(json.dumps(config, indent=2))
    return {"config": config, "exists": True}


@router.post("/ollama/test")
def ollama_test(base_url: str = Body("", embed=True)) -> dict:
    """Ping the Ollama server and list its installed models. Returns ok/error
    inline (200) so the settings page can show status without HTTP error handling."""
    from job_hunt.llm_utils import list_ollama_models

    cfg = _read_json(paths.config_path(), {}) or {}
    url = base_url or cfg.get("ollama_base_url") or "http://localhost:11434/v1"
    try:
        models = list_ollama_models(base_url=url, config=cfg)
    except Exception as e:
        return {"ok": False, "error": str(e), "base_url": url, "models": []}
    return {"ok": True, "models": models, "base_url": url}


# --- companies ----------------------------------------------------------------

@router.get("/companies")
def get_companies() -> dict:
    companies = _read_json(paths.companies_path(), [])
    return {"companies": companies, "count": len(companies)}


def _validate_company(c: Any) -> dict:
    if not isinstance(c, dict):
        raise HTTPException(400, "each company must be a JSON object")
    missing = [k for k in _REQUIRED_COMPANY_KEYS if not c.get(k)]
    if missing:
        raise HTTPException(400, f"company missing required fields: {', '.join(missing)}")
    cleaned = {k: c.get(k, "") for k in _REQUIRED_COMPANY_KEYS}
    # Preserve the disable toggle. Only persist it when a board is actually
    # disabled, so enabled companies.json entries stay clean (no "enabled": true).
    if c.get("enabled", True) is False:
        cleaned["enabled"] = False
    return cleaned


@router.put("/companies")
def put_companies(companies: list = Body(...)) -> dict:
    if not isinstance(companies, list):
        raise HTTPException(400, "companies must be a JSON array")
    cleaned = [_validate_company(c) for c in companies]
    paths.companies_path().write_text(json.dumps(cleaned, indent=2))
    return {"companies": cleaned, "count": len(cleaned)}


@router.post("/companies")
def add_company(company: dict = Body(...)) -> dict:
    cleaned = _validate_company(company)
    companies = _read_json(paths.companies_path(), [])
    if any(c.get("careers_url") == cleaned["careers_url"] for c in companies):
        raise HTTPException(409, "a company with that careers_url already exists")
    companies.append(cleaned)
    paths.companies_path().write_text(json.dumps(companies, indent=2))
    return {"companies": companies, "count": len(companies)}


def _resume_or_400(cfg: dict) -> str:
    rpath = paths.resume_path(cfg)
    resume = rpath.read_text(encoding="utf-8") if rpath.exists() else ""
    if not resume.strip():
        raise HTTPException(400, "No resume found — add one on the Resume tab first.")
    return resume


@router.post("/companies/suggest")
def suggest_start(count: int = Body(8, embed=True)) -> dict:
    """Start a background suggestion job. Poll /companies/jobs/result for the
    outcome and watch /companies/jobs/stream for the live log."""
    from job_hunt.suggester import suggest_companies

    cfg = _read_json(paths.config_path(), {})
    resume = _resume_or_400(cfg)
    existing = _read_json(paths.companies_path(), [])
    n = max(1, min(20, count))

    def job():
        return {"kind": "suggest",
                "suggestions": suggest_companies(cfg, resume, existing, n, on_token=jobs.emit_token)}

    try:
        jobs.start("suggest", job)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()


@router.post("/companies/review")
def review_start() -> dict:
    """Start a background review job (see /companies/jobs/* for stream + result)."""
    from job_hunt.suggester import review_companies

    cfg = _read_json(paths.config_path(), {})
    resume = _resume_or_400(cfg)
    companies = _read_json(paths.companies_path(), [])

    def job():
        flagged = review_companies(cfg, resume, companies, on_token=jobs.emit_token) if companies else []
        return {"kind": "review", "flagged": flagged, "reviewed": len(companies)}

    try:
        jobs.start("review", job)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()


@router.get("/companies/jobs/result")
def jobs_result() -> dict:
    return {**jobs.status(), "result": jobs.result}


def _sse(item: dict) -> str:
    # Encode a job item as an SSE event. Multi-line values become multiple
    # `data:` lines (EventSource rejoins them with "\n"). Token chunks use a
    # distinct `token` event so the UI appends them inline; status lines are the
    # default `message` event and get their own row.
    body = "".join(f"data: {ln}\n" for ln in item["v"].split("\n"))
    prefix = "event: token\n" if item["t"] == "tok" else ""
    return f"{prefix}{body}\n"


@router.get("/companies/jobs/stream")
def jobs_stream() -> StreamingResponse:
    def event_stream():
        q = jobs.subscribe()
        try:
            while True:
                try:
                    item = q.get(timeout=1.0)
                except queue.Empty:
                    if not jobs.running:
                        yield "event: end\ndata: done\n\n"
                        break
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    yield "event: end\ndata: done\n\n"
                    break
                yield _sse(item)
        finally:
            jobs.unsubscribe(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/companies/{index}")
def delete_company(index: int) -> dict:
    companies = _read_json(paths.companies_path(), [])
    if not 0 <= index < len(companies):
        raise HTTPException(404, f"no company at index {index}")
    removed = companies.pop(index)
    paths.companies_path().write_text(json.dumps(companies, indent=2))
    return {"removed": removed, "count": len(companies)}


# --- resume -------------------------------------------------------------------

@router.get("/resume")
def get_resume() -> dict:
    cfg = _read_json(paths.config_path(), {})
    path = paths.resume_path(cfg)
    if not path.exists():
        return {"content": "", "exists": False, "path": str(path)}
    return {"content": path.read_text(encoding="utf-8"), "exists": True, "path": str(path)}


@router.put("/resume")
def put_resume(content: str = Body(..., embed=True)) -> dict:
    cfg = _read_json(paths.config_path(), {})
    path = paths.resume_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"exists": True, "path": str(path), "bytes": len(content.encode("utf-8"))}


@router.post("/resume/upload")
async def upload_resume(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "resume must be UTF-8 text (Markdown or plain text)")
    cfg = _read_json(paths.config_path(), {})
    path = paths.resume_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"exists": True, "path": str(path), "bytes": len(data), "filename": file.filename}


# --- scan ---------------------------------------------------------------------

@router.get("/scan/status")
def scan_status() -> dict:
    return runner.status()


@router.get("/scan/logs")
def scan_logs(limit: int = 500) -> dict:
    return {"lines": runner.recent_lines(limit), **runner.status()}


@router.post("/scan/start")
def scan_start() -> dict:
    try:
        runner.start()
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return runner.status()


@router.post("/scan/stop")
def scan_stop() -> dict:
    stopped = runner.stop()
    return {"stopped": stopped, **runner.status()}


@router.get("/scan/stream")
def scan_stream() -> StreamingResponse:
    def event_stream():
        q = runner.subscribe()
        try:
            while True:
                try:
                    item = q.get(timeout=1.0)
                except queue.Empty:
                    if not runner.running:
                        yield "event: end\ndata: done\n\n"
                        break
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    yield "event: end\ndata: done\n\n"
                    break
                yield f"data: {item}\n\n"
        finally:
            runner.unsubscribe(q)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- results ------------------------------------------------------------------

@router.get("/results")
def results() -> dict:
    jobs = _read_json(paths.last_scan_path(), [])
    jobs = sorted(jobs, key=lambda j: j.get("score", 0), reverse=True)
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/results/history")
def results_history() -> dict:
    jobs = _read_json(paths.job_history_path(), [])
    return {"jobs": jobs, "count": len(jobs)}


# --- schedule -----------------------------------------------------------------

@router.get("/schedule")
def get_schedule() -> dict:
    return {**read_schedule(), "next_run": scheduler.next_run, "scan_running": runner.running}


@router.put("/schedule")
def put_schedule(enabled: bool = Body(...), time: str = Body(...)) -> dict:
    import re
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", time):
        raise HTTPException(400, "time must be 24h HH:MM, e.g. 02:00")
    saved = write_schedule(enabled, time)
    return {**saved, "next_run": scheduler.next_run}
