"""Web infra: scheduler, server launcher, SPA serving, scan-runner internals."""
import sys
import types

import pytest

pytest.importorskip("fastapi")

from job_hunt.web import app as appmod  # noqa: E402
from job_hunt.web import scan_runner, scheduler, server  # noqa: E402

# --- scheduler ----------------------------------------------------------------

def test_schedule_read_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scheduler.read_schedule() == {"enabled": False, "time": "02:00"}
    scheduler.write_schedule(True, "03:15")
    s = scheduler.read_schedule()
    assert s["enabled"] is True and s["time"] == "03:15"


class _FakeNow:
    def strftime(self, fmt):
        return "2026-01-01" if "%Y" in fmt else "02:00"


def test_scheduler_tick_fires_at_time(monkeypatch):
    monkeypatch.setattr(scheduler, "read_schedule", lambda: {"enabled": True, "time": "02:00"})
    fired = []
    monkeypatch.setattr(scheduler.runner, "start", lambda: fired.append(1))
    sched = scheduler.DailyScheduler()
    sched._tick(_FakeNow())
    assert fired == [1]
    # same day -> does not fire twice
    sched._tick(_FakeNow())
    assert fired == [1]


def test_scheduler_tick_disabled_clears_next_run(monkeypatch):
    monkeypatch.setattr(scheduler, "read_schedule", lambda: {"enabled": False, "time": "02:00"})
    sched = scheduler.DailyScheduler()
    sched.next_run = "something"
    sched._tick(_FakeNow())
    assert sched.next_run is None


# --- server launcher ----------------------------------------------------------

def test_run_server_invokes_uvicorn(monkeypatch):
    calls = {}
    fake = types.SimpleNamespace(run=lambda app, host, port, log_level: calls.update(app=app, host=host, port=port))
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    server.run_server(["--host", "0.0.0.0", "--port", "9123"])  # non-loopback -> warns
    assert calls["host"] == "0.0.0.0" and calls["port"] == 9123
    assert calls["app"] == "job_hunt.web.app:app"


# --- SPA serving --------------------------------------------------------------

def test_create_app_serves_spa(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa-root</html>")
    monkeypatch.setattr(appmod, "_STATIC_DIR", static)
    monkeypatch.setattr(appmod.scheduler, "start", lambda: None)
    monkeypatch.setattr(appmod.scheduler, "stop", lambda: None)
    with TestClient(appmod.create_app()) as c:
        assert c.get("/api/health").status_code == 200      # API still wins
        assert "spa-root" in c.get("/").text                # index served
        assert "spa-root" in c.get("/some/client/route").text  # SPA fallback


# --- scan runner internals (no real subprocess) -------------------------------

def test_scan_runner_idle_emit_subscribe():
    r = scan_runner.ScanRunner()
    assert r.running is False
    assert r.status()["running"] is False
    assert r.stop() is False  # nothing to stop
    r._emit("line one")
    r._emit("line two")
    assert r.recent_lines() == ["line one", "line two"]
    q = r.subscribe()  # replays buffer
    assert q.get_nowait() == "line one" and q.get_nowait() == "line two"
    r.unsubscribe(q)
