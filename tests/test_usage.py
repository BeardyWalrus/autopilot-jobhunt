"""The Claude usage ledger and GET /api/usage (job_hunt/usage.py, ADR 0006)."""
from datetime import datetime, timedelta

import pytest

from job_hunt import usage

NOW = datetime(2026, 11, 16, 12, 0, 0)


def add(path, feature="scoring", ok=True, when=NOW, cost=0.01, **tokens):
    usage.record(path=path, feature=feature, model="claude-opus-5-5", ok=ok,
                 tokens={"input": 10, "output": 5, **tokens}, cost_estimate_usd=cost,
                 duration_ms=1200, error="" if ok else "timed out", now=when)


def test_totals_by_feature(tmp_path):
    path = tmp_path / "state" / "claude_usage.jsonl"
    add(path, "scoring")
    add(path, "scoring", cache_read=1000)
    add(path, "drafts", ok=False, cost=None)
    out = usage.summary(path, now=NOW)
    assert out["total"] == {"calls": 3, "failed": 1, "input": 30, "output": 15, "cache_read": 1000,
                            "cache_create": 0, "cost_estimate_usd": 0.02}
    assert out["by_feature"]["scoring"]["calls"] == 2
    assert out["by_feature"]["drafts"]["failed"] == 1


def test_since_leaves_out_older_calls(tmp_path):
    path = tmp_path / "u.jsonl"
    add(path, when=NOW - timedelta(days=3))
    add(path, when=NOW - timedelta(hours=1))
    assert usage.summary(path, since=NOW - timedelta(days=1), now=NOW)["total"]["calls"] == 1
    assert usage.summary(path, now=NOW)["total"]["calls"] == 2  # default: last 7 days


def test_no_ledger_yet_is_all_zero(tmp_path):
    out = usage.summary(tmp_path / "missing.jsonl", now=NOW)
    assert out["total"]["calls"] == 0 and out["by_feature"] == {} and out["last_call_at"] is None


def test_bad_lines_are_skipped(tmp_path):
    path = tmp_path / "u.jsonl"
    add(path)
    with path.open("a") as f:
        f.write("not json\n{\"at\": \"never\"}\n")
    add(path)
    assert usage.summary(path, now=NOW)["total"]["calls"] == 2


def test_old_calls_are_pruned(tmp_path):
    path = tmp_path / "u.jsonl"
    add(path, when=NOW - timedelta(days=120))
    add(path, when=NOW - timedelta(days=2))
    assert usage.prune(path, now=NOW) == 1
    assert usage.summary(path, since=NOW - timedelta(days=365), now=NOW)["total"]["calls"] == 1


def test_tokens_from_the_sdk_usage():
    assert usage.tokens_from({"input_tokens": 3, "output_tokens": "4", "cache_read_input_tokens": None}) == \
        {"input": 3, "output": 4, "cache_read": 0, "cache_create": 0}
    assert usage.tokens_from(None) == {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}


def test_ledger_lives_in_the_project_state_folder(monkeypatch, tmp_path):
    monkeypatch.undo()  # the autouse fixture swaps ledger_path; check the real one
    monkeypatch.setenv("AUTOPILOT_HOME", str(tmp_path))
    assert usage.ledger_path() == tmp_path.resolve() / "state" / "claude_usage.jsonl"


# --- GET /api/usage -------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from job_hunt.web.app import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("job_hunt.web.app.scheduler.start", lambda: None)
    monkeypatch.setattr("job_hunt.web.app.scheduler.stop", lambda: None)
    with TestClient(create_app()) as c:
        yield c


def test_usage_route_reports_since(client, usage_ledger):
    now = datetime.now()
    add(usage_ledger, "scoring", when=now - timedelta(days=2))
    add(usage_ledger, "drafts", when=now - timedelta(minutes=5))
    since = (now - timedelta(days=1)).isoformat(timespec="seconds")
    body = client.get("/api/usage", params={"since": since}).json()
    assert body["total"]["calls"] == 1 and list(body["by_feature"]) == ["drafts"]
    assert set(body["total"]) == {"calls", "failed", "input", "output", "cache_read", "cache_create",
                                  "cost_estimate_usd"}


def test_usage_route_takes_a_utc_time(client, usage_ledger):
    add(usage_ledger, when=datetime.now() - timedelta(minutes=1))
    r = client.get("/api/usage", params={"since": "2026-01-01T00:00:00Z"})
    assert r.status_code == 200 and r.json()["total"]["calls"] == 1


def test_usage_route_refuses_a_bad_since(client):
    assert client.get("/api/usage", params={"since": "yesterday"}).status_code == 422
