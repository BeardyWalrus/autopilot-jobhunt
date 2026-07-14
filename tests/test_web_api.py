"""Web API — FastAPI TestClient over a temp project dir. No real scans/network."""
import json

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


def test_suggest_endpoint(client, monkeypatch):
    c, tmp = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior ML engineer"})
    monkeypatch.setattr(
        "job_hunt.suggester.suggest_companies",
        lambda cfg, resume, existing, count: [
            {"name": "Cohere", "careers_url": "https://cohere.com/careers",
             "search_domain": "cohere.com", "location": "Toronto", "region": "NA",
             "reason": "NLP", "exists": False}],
    )
    r = c.post("/api/companies/suggest", json={"count": 5})
    assert r.status_code == 200 and r.json()["count"] == 1
    assert r.json()["suggestions"][0]["name"] == "Cohere"


def test_suggest_endpoint_requires_resume(client):
    c, _ = client
    r = c.post("/api/companies/suggest", json={"count": 5})
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


def test_review_endpoint(client, monkeypatch):
    c, tmp = client
    c.put("/api/config", json={"candidate": {"resume_path": "resume/r.md"}})
    c.put("/api/resume", json={"content": "Senior ML engineer"})
    c.put("/api/companies", json=[
        {"name": "Acme Bank", "careers_url": "https://acmebank.com/careers",
         "search_domain": "acmebank.com", "location": "NY", "region": "NA"}])
    monkeypatch.setattr(
        "job_hunt.suggester.review_companies",
        lambda cfg, resume, companies: [
            {"index": 0, "name": "Acme Bank", "search_domain": "acmebank.com", "reason": "finance"}],
    )
    r = c.post("/api/companies/review")
    assert r.status_code == 200 and r.json()["count"] == 1
    assert r.json()["flagged"][0]["name"] == "Acme Bank" and r.json()["reviewed"] == 1


def test_review_endpoint_requires_resume(client):
    c, _ = client
    r = c.post("/api/companies/review")
    assert r.status_code == 400 and "resume" in r.json()["detail"].lower()


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


# --- results ------------------------------------------------------------------

def test_results_sorted_by_score(client):
    c, tmp = client
    (tmp / "state" / "last_scan.json").write_text(json.dumps([
        {"url": "u1", "score": 40}, {"url": "u2", "score": 90}, {"url": "u3", "score": 70},
    ]))
    jobs = c.get("/api/results").json()["jobs"]
    assert [j["score"] for j in jobs] == [90, 70, 40]


# --- schedule -----------------------------------------------------------------

def test_schedule_roundtrip_and_validation(client):
    c, tmp = client
    assert c.get("/api/schedule").json()["enabled"] is False

    assert c.put("/api/schedule", json={"enabled": True, "time": "02:30"}).status_code == 200
    got = c.get("/api/schedule").json()
    assert got["enabled"] is True and got["time"] == "02:30"
    assert json.loads((tmp / "config.json").read_text())["schedule"]["time"] == "02:30"

    assert c.put("/api/schedule", json={"enabled": True, "time": "25:99"}).status_code == 400
