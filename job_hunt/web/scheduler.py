"""A small daily scheduler — no external dependency.

Reads the schedule from config.json under a "schedule" key:

    "schedule": {"enabled": true, "time": "02:00"}   # local time, 24h HH:MM

A background thread wakes every 30s; when the wall-clock minute matches and the
job hasn't already fired today, it starts a scan through the shared ScanRunner
(skipped if a scan is already running). Manual scans and the schedule share the
same runner, so they can never overlap.
"""
import json
import threading
from datetime import datetime

from job_hunt.log import get_logger
from job_hunt.web.paths import config_path
from job_hunt.web.scan_runner import runner

logger = get_logger()


def read_schedule() -> dict:
    try:
        cfg = json.loads(config_path().read_text())
    except Exception:
        return {"enabled": False, "time": "02:00"}
    sched = cfg.get("schedule") or {}
    return {"enabled": bool(sched.get("enabled")), "time": str(sched.get("time", "02:00"))}


def write_schedule(enabled: bool, at_time: str) -> dict:
    cfg = {}
    if config_path().exists():
        cfg = json.loads(config_path().read_text())
    cfg["schedule"] = {"enabled": bool(enabled), "time": at_time}
    config_path().write_text(json.dumps(cfg, indent=2))
    return {"enabled": bool(enabled), "time": at_time}


class DailyScheduler:
    def __init__(self, poll_seconds: int = 30) -> None:
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fired_date: str | None = None
        self.next_run: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._poll):
            try:
                self._tick(datetime.now())
            except Exception as e:  # a bad config must not kill the scheduler
                logger.error(f"Scheduler tick failed: {e}")

    def _tick(self, now: datetime) -> None:
        sched = read_schedule()
        if not sched["enabled"]:
            self.next_run = None
            return
        today = now.strftime("%Y-%m-%d")
        if now.strftime("%H:%M") == sched["time"] and self._last_fired_date != today:
            self._last_fired_date = today
            if runner.running:
                logger.info("Scheduled scan skipped — a scan is already running.")
                return
            logger.info(f"Scheduled scan firing at {sched['time']}")
            runner.start()


scheduler = DailyScheduler()
