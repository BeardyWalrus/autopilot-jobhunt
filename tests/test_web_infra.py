"""Web infra: scheduler, server launcher, SPA serving, scan-runner internals."""
import json
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


def test_write_schedule_preserves_existing_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"candidate": {"name": "Ada"}}))
    scheduler.write_schedule(True, "06:30")
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["candidate"]["name"] == "Ada"  # other keys are not clobbered
    assert cfg["schedule"] == {"enabled": True, "time": "06:30"}


class _FakeNow:
    def strftime(self, fmt):
        return "2026-01-01" if "%Y" in fmt else "02:00"


class _FakePopen:
    """Stands in for subprocess.Popen: yields the given stdout lines, then ends."""
    def __init__(self, lines):
        self.stdout = iter(lines)
        self._done = False
        self.terminated = False

    def poll(self):
        return 0 if self._done else None  # None = still running

    def wait(self):
        self._done = True
        return 0

    def terminate(self):
        self.terminated = True
        self._done = True


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


def test_scheduler_tick_skips_when_scan_running(monkeypatch):
    # Time matches, but a scan is already running -> the scheduled scan is skipped
    # (never overlaps a manual scan), and the once-a-day guard is still consumed.
    monkeypatch.setattr(scheduler, "read_schedule", lambda: {"enabled": True, "time": "02:00"})
    monkeypatch.setattr(type(scheduler.runner), "running", property(lambda self: True))
    started = []
    monkeypatch.setattr(scheduler.runner, "start", lambda: started.append(1))
    sched = scheduler.DailyScheduler()
    sched._tick(_FakeNow())
    assert started == [] and sched._last_fired_date == "2026-01-01"


def test_scheduler_read_schedule_tolerates_bad_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text("{ not json")
    assert scheduler.read_schedule() == {"enabled": False, "time": "02:00"}


def test_scheduler_start_is_idempotent_and_stops():
    sched = scheduler.DailyScheduler(poll_seconds=1000)  # long poll: won't tick before we stop
    sched.start()
    t = sched._thread
    assert t is not None and t.is_alive()
    sched.start()  # already alive -> no new thread
    assert sched._thread is t
    sched.stop()
    t.join(timeout=5)
    assert not t.is_alive()


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


def test_scan_runner_start_pumps_output_to_completion(monkeypatch):
    r = scan_runner.ScanRunner()
    fake = _FakePopen(["[10:00] scanning...\n", "1 job saved\n"])
    monkeypatch.setattr(scan_runner.subprocess, "Popen", lambda *a, **k: fake)
    monkeypatch.setattr(scan_runner, "_subprocess_env", lambda: {})
    q = r.subscribe()  # a live viewer should receive streamed lines
    r.start()
    r._reader.join(timeout=5)
    assert not r._reader.is_alive()
    lines = r.recent_lines()
    assert any("scanning" in ln for ln in lines)
    assert any("1 job saved" in ln for ln in lines)
    assert any("scan finished (exit 0)" in ln for ln in lines)
    st = r.status()
    assert st["running"] is False and st["exit_code"] == 0
    # the subscriber got a stream ending in the None sentinel
    drained = []
    while True:
        item = q.get_nowait()
        drained.append(item)
        if item is None:
            break
    assert "$ " in drained[0] and drained[-1] is None


def test_scan_runner_rejects_second_start_and_stops(monkeypatch):
    r = scan_runner.ScanRunner()
    fake = _FakePopen([])
    r._proc = fake  # pretend a scan is already running (poll() -> None)
    assert r.running is True
    with pytest.raises(RuntimeError):
        r.start()
    assert r.stop() is True and fake.terminated is True
    assert r.running is False  # terminate() flipped poll() to a code


def test_subprocess_env_injects_log_level(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOPILOT_HOME", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    (tmp_path / "config.json").write_text(json.dumps({"log_level": "debug"}))
    env = scan_runner._subprocess_env()
    assert env["LOG_LEVEL"] == "DEBUG"  # read from config.json, upper-cased


def test_subprocess_env_respects_explicit_log_level(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AUTOPILOT_HOME", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    (tmp_path / "config.json").write_text(json.dumps({"log_level": "DEBUG"}))
    env = scan_runner._subprocess_env()
    assert env["LOG_LEVEL"] == "WARNING"  # an explicit env var wins over config
