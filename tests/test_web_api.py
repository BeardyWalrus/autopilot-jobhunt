"""Web API — FastAPI TestClient over a temp project dir. No real scans/network."""
import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from job_hunt.web.app import create_app  # noqa: E402
from job_hunt.web.scan_runner import runner  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOPILOT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    # Don't run the scheduler thread during tests.
    monkeypatch.setattr("job_hunt.web.app.scheduler.start", lambda: None)
    monkeypatch.setattr("job_hunt.web.app.scheduler.stop", lambda: None)
    with TestClient(create_app()) as c:
        yield c, tmp_path


# --- health / config ----------------------------------------------------------

def test_health(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ollama_test_endpoint_ok(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("job_hunt.llm_utils.list_ollama_models",
                        lambda base_url, config: ["llama3.1", "qwen2.5:7b"])
    r = c.post("/api/ollama/test", json={"base_url": "http://x:11434/v1"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["models"] == ["llama3.1", "qwen2.5:7b"]


def test_ollama_test_endpoint_error_is_inline(client, monkeypatch):
    c, _ = client

    def boom(base_url, config):
        raise RuntimeError("Could not reach Ollama at http://x")

    monkeypatch.setattr("job_hunt.llm_utils.list_ollama_models", boom)
    r = c.post("/api/ollama/test", json={"base_url": ""})
    assert r.status_code == 200  # error is reported inline, not as HTTP error
    assert r.json()["ok"] is False and "Ollama" in r.json()["error"]


def test_config_seeds_template_then_roundtrips(client):
    c, tmp = client
    r = c.get("/api/config")
    assert r.status_code == 200 and r.json()["exists"] is False
    assert "candidate" in r.json()["config"]  # template served

    new_cfg = {"llm_provider": "ollama", "ollama_model": "gemma4:e4b",
               "candidate": {"name": "Ada", "min_score": 60}}
    assert c.put("/api/config", json=new_cfg).status_code == 200
    got = c.get("/api/config")
    assert got.json()["exists"] is True
    assert got.json()["config"]["ollama_model"] == "gemma4:e4b"
    assert json.loads((tmp / "config.json").read_text())["llm_provider"] == "ollama"


# --- companies ----------------------------------------------------------------

def test_companies_crud(client):
    c, tmp = client
    assert c.get("/api/companies").json() == {"companies": [], "count": 0}

    acme = {"name": "Acme", "careers_url": "https://acme.co/careers",
            "search_domain": "acme.co", "location": "Remote", "region": "EU"}
    assert c.put("/api/companies", json=[acme]).json()["count"] == 1

    beta = {**acme, "name": "Beta", "careers_url": "https://beta.co/careers", "search_domain": "beta.co"}
    assert c.post("/api/companies", json=beta).json()["count"] == 2

    # duplicate careers_url rejected
    assert c.post("/api/companies", json=beta).status_code == 409

    # delete index 0
    assert c.delete("/api/companies/0").json()["count"] == 1
    assert c.get("/api/companies").json()["companies"][0]["name"] == "Beta"


def test_company_validation_rejects_missing_fields(client):
    c, _ = client
    r = c.post("/api/companies", json={"name": "NoUrl"})
    assert r.status_code == 400 and "careers_url" in r.json()["detail"]


def _wait_job(c, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = c.get("/api/companies/jobs/result").json()
        if r["done"]:
            return r
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_suggest_job(client, monkeypatch):
    c, tmp = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior ML engineer"})
    monkeypatch.setattr(
        "job_hunt.suggester.suggest_companies",
        lambda cfg, resume, existing, count, on_token=None: [
            {"name": "Cohere", "careers_url": "https://cohere.com/careers",
             "search_domain": "cohere.com", "location": "Toronto", "region": "NA",
             "reason": "NLP", "exists": False}],
    )
    assert c.post("/api/companies/suggest", json={"count": 5}).status_code == 200
    r = _wait_job(c)
    assert r["ok"] is True and r["result"]["kind"] == "suggest"
    assert r["result"]["suggestions"][0]["name"] == "Cohere"


def test_suggest_requires_resume(client):
    c, _ = client
    r = c.post("/api/companies/suggest", json={"count": 5})
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


def test_review_job(client, monkeypatch):
    c, tmp = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior ML engineer"})
    c.put("/api/companies", json=[
        {"name": "Acme Bank", "careers_url": "https://acmebank.com/careers",
         "search_domain": "acmebank.com", "location": "NY", "region": "NA"}])
    monkeypatch.setattr(
        "job_hunt.suggester.review_companies",
        lambda cfg, resume, companies, on_token=None: [
            {"index": 0, "name": "Acme Bank", "search_domain": "acmebank.com", "reason": "finance"}],
    )
    assert c.post("/api/companies/review").status_code == 200
    r = _wait_job(c)
    assert r["ok"] is True and r["result"]["kind"] == "review"
    assert r["result"]["flagged"][0]["name"] == "Acme Bank" and r["result"]["reviewed"] == 1


def test_review_excludes_disabled_boards(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "resume"})
    c.put("/api/companies", json=[
        {"name": "On", "careers_url": "https://on.co/c", "search_domain": "on.co",
         "location": "L", "region": "EU"},
        {"name": "Off", "careers_url": "https://off.co/c", "search_domain": "off.co",
         "location": "L", "region": "EU", "enabled": False},
    ])
    seen = {}

    def fake(cfg, resume, companies, on_token=None):
        seen["names"] = [x["name"] for x in companies]
        return []

    monkeypatch.setattr("job_hunt.suggester.review_companies", fake)
    c.post("/api/companies/review", json={"include_disabled": False})
    r = _wait_job(c)
    assert r["ok"] is True
    assert seen["names"] == ["On"]  # the disabled "Off" board is excluded
    assert r["result"]["reviewed"] == 1


def test_review_requires_resume(client):
    c, _ = client
    r = c.post("/api/companies/review")
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


def test_reconsider_job_only_reviews_disabled(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior ML engineer"})
    c.put("/api/companies", json=[
        {"name": "On", "careers_url": "https://on.co/c", "search_domain": "on.co",
         "location": "L", "region": "EU"},
        {"name": "Off", "careers_url": "https://off.co/c", "search_domain": "off.co",
         "location": "L", "region": "EU", "enabled": False},
    ])
    seen = {}

    def fake(cfg, resume, companies, on_token=None):
        seen["names"] = [x["name"] for x in companies]
        return [{"index": 0, "name": "Off", "search_domain": "off.co", "reason": "actually a good fit"}]

    monkeypatch.setattr("job_hunt.suggester.reconsider_companies", fake)
    assert c.post("/api/companies/reconsider").status_code == 200
    r = _wait_job(c)
    assert r["ok"] is True and r["result"]["kind"] == "reconsider"
    assert seen["names"] == ["Off"]  # only disabled boards are reconsidered
    assert r["result"]["recommended"][0]["name"] == "Off" and r["result"]["reviewed"] == 1


def test_reconsider_no_disabled_boards(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "resume"})
    c.put("/api/companies", json=[
        {"name": "On", "careers_url": "https://on.co/c", "search_domain": "on.co",
         "location": "L", "region": "EU"}])

    def boom(*a, **k):
        raise AssertionError("should not call the LLM when nothing is disabled")

    monkeypatch.setattr("job_hunt.suggester.reconsider_companies", boom)
    assert c.post("/api/companies/reconsider").status_code == 200
    r = _wait_job(c)
    assert r["ok"] is True and r["result"]["recommended"] == [] and r["result"]["reviewed"] == 0


def test_reconsider_requires_resume(client):
    c, _ = client
    r = c.post("/api/companies/reconsider")
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


def test_suggest_search_terms_job(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior product manager, 10 YOE"})
    monkeypatch.setattr(
        "job_hunt.suggester.suggest_search_terms",
        lambda cfg, resume, on_token=None: {
            "search_keywords": '"product manager" OR "product lead"',
            "search_seniority": "senior OR staff",
        },
    )
    assert c.post("/api/candidate/search-terms/suggest").status_code == 200
    r = _wait_job(c)
    assert r["ok"] is True and r["result"]["kind"] == "search_terms"
    assert r["result"]["search_keywords"] == '"product manager" OR "product lead"'
    assert r["result"]["search_seniority"] == "senior OR staff"


def test_suggest_search_terms_requires_resume(client):
    c, _ = client
    r = c.post("/api/candidate/search-terms/suggest")
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


def test_suggest_job_streams_tokens(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "resume"})

    # A fake suggester that streams a couple of tokens through on_token.
    def fake(cfg, resume, existing, count, on_token=None):
        if on_token:
            on_token("Cohere\n")
            on_token("Hugging Face")
        return [{"name": "Cohere", "search_domain": "cohere.com", "reason": "x", "exists": False}]

    monkeypatch.setattr("job_hunt.suggester.suggest_companies", fake)
    assert c.post("/api/companies/suggest", json={"count": 2}).status_code == 200
    _wait_job(c)
    stream = c.get("/api/companies/jobs/stream").text  # replays buffered items
    assert "event: token" in stream and "Cohere" in stream and "Hugging Face" in stream


def test_job_reports_failure_inline(client, monkeypatch):
    c, _ = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "resume"})

    def boom(cfg, resume, existing, count, on_token=None):
        raise RuntimeError("LLM unreachable")

    monkeypatch.setattr("job_hunt.suggester.suggest_companies", boom)
    assert c.post("/api/companies/suggest", json={"count": 3}).status_code == 200
    r = _wait_job(c)
    assert r["ok"] is False and "LLM unreachable" in r["error"]


def test_company_enabled_flag_preserved(client):
    c, tmp = client
    base = {"careers_url": "https://x.co/careers", "search_domain": "x.co",
            "location": "Remote", "region": "EU"}
    payload = [
        {**base, "name": "On"},                       # no flag -> enabled, stays clean
        {**base, "name": "Off", "careers_url": "https://y.co/careers", "enabled": False},
    ]
    c.put("/api/companies", json=payload)
    saved = json.loads((tmp / "companies.json").read_text())
    assert "enabled" not in saved[0]          # enabled companies stay flag-free
    assert saved[1]["enabled"] is False       # disabled flag persisted


# --- resume -------------------------------------------------------------------

def test_resume_put_get_and_upload(client):
    c, tmp = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/YOUR_RESUME.md"}})

    assert c.get("/api/resume").json()["exists"] is False
    assert c.put("/api/resume", json={"content": "# Ada\nSenior MLE"}).status_code == 200
    assert c.get("/api/resume").json()["content"].startswith("# Ada")

    files = {"file": ("cv.md", b"# Uploaded\nvia multipart", "text/markdown")}
    r = c.post("/api/resume/upload", files=files)
    assert r.status_code == 200 and r.json()["filename"] == "cv.md"
    assert "Uploaded" in c.get("/api/resume").json()["content"]


def test_resume_upload_rejects_binary(client):
    c, _ = client
    files = {"file": ("x.pdf", b"\xff\xfe\x00\x01binary", "application/pdf")}
    assert c.post("/api/resume/upload", files=files).status_code == 400


# --- scan ---------------------------------------------------------------------

def test_scan_status_idle(client):
    c, _ = client
    r = c.get("/api/scan/status")
    assert r.status_code == 200 and r.json()["running"] is False


def test_scan_start_ok_and_conflict(client, monkeypatch):
    c, _ = client
    calls = []
    monkeypatch.setattr(runner, "start", lambda *a, **k: calls.append(1))
    assert c.post("/api/scan/start").status_code == 200
    assert calls == [1]

    def boom(*a, **k):
        raise RuntimeError("A scan is already running.")

    monkeypatch.setattr(runner, "start", boom)
    assert c.post("/api/scan/start").status_code == 409


def test_scan_seen_and_forget(client):
    c, tmp = client
    (tmp / "state" / "seen_jobs.json").write_text(json.dumps({"seen_urls": ["a", "b", "c"]}))
    assert c.get("/api/scan/seen").json()["seen"] == 3
    r = c.post("/api/scan/forget")
    assert r.status_code == 200 and r.json() == {"forgotten": 3, "seen": 0}
    assert c.get("/api/scan/seen").json()["seen"] == 0
    # File is left present but emptied.
    assert json.loads((tmp / "state" / "seen_jobs.json").read_text()) == {"seen_urls": []}


def test_scan_forget_conflict_while_running(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(type(runner), "running", property(lambda self: True))
    assert c.post("/api/scan/forget").status_code == 409


def test_scan_seen_list_and_edit(client):
    c, tmp = client
    (tmp / "state" / "seen_jobs.json").write_text(json.dumps({"seen_urls": ["a", "b", "c"]}))
    # count-only by default; list when limit is passed
    assert c.get("/api/scan/seen").json() == {"seen": 3}
    listed = c.get("/api/scan/seen?limit=2").json()
    assert listed["seen"] == 3 and listed["urls"] == ["a", "b"] and listed["truncated"] is True
    # edit: drop "b" -> it will be re-scanned; de-dups too
    r = c.put("/api/scan/seen", json={"urls": ["a", "c", "c"]})
    assert r.status_code == 200 and r.json() == {"seen": 2, "removed": 1}
    assert json.loads((tmp / "state" / "seen_jobs.json").read_text()) == {"seen_urls": ["a", "c"]}


def test_scan_seen_set_validation_and_conflict(client, monkeypatch):
    c, _ = client
    assert c.put("/api/scan/seen", json={"urls": [1, 2]}).status_code == 400
    monkeypatch.setattr(type(runner), "running", property(lambda self: True))
    assert c.put("/api/scan/seen", json={"urls": ["a"]}).status_code == 409


# --- results ------------------------------------------------------------------

def test_results_sorted_by_score(client):
    c, tmp = client
    (tmp / "state" / "last_scan.json").write_text(json.dumps([
        {"url": "u1", "score": 40}, {"url": "u2", "score": 90}, {"url": "u3", "score": 70},
    ]))
    jobs = c.get("/api/results").json()["jobs"]
    assert [j["score"] for j in jobs] == [90, 70, 40]


def test_delete_single_result(client):
    c, tmp = client
    (tmp / "state" / "last_scan.json").write_text(json.dumps([
        {"url": "u1", "score": 90}, {"url": "u2", "score": 70}, {"url": "u3", "score": 40},
    ]))
    r = c.request("DELETE", "/api/results", json={"url": "u2"})
    assert r.status_code == 200 and r.json() == {"removed": 1, "count": 2}
    assert [j["url"] for j in c.get("/api/results").json()["jobs"]] == ["u1", "u3"]
    # deleting a URL that isn't there -> 404
    assert c.request("DELETE", "/api/results", json={"url": "nope"}).status_code == 404


def test_clear_all_results(client):
    c, tmp = client
    (tmp / "state" / "last_scan.json").write_text(json.dumps([
        {"url": "u1", "score": 90}, {"url": "u2", "score": 70},
    ]))
    r = c.delete("/api/results/all")
    assert r.status_code == 200 and r.json() == {"removed": 2, "count": 0}
    assert c.get("/api/results").json()["count"] == 0


# --- schedule -----------------------------------------------------------------

def test_schedule_roundtrip_and_validation(client):
    c, tmp = client
    assert c.get("/api/schedule").json()["enabled"] is False

    assert c.put("/api/schedule", json={"enabled": True, "time": "02:30"}).status_code == 200
    got = c.get("/api/schedule").json()
    assert got["enabled"] is True and got["time"] == "02:30"
    assert json.loads((tmp / "config.json").read_text())["schedule"]["time"] == "02:30"

    assert c.put("/api/schedule", json={"enabled": True, "time": "25:99"}).status_code == 400
