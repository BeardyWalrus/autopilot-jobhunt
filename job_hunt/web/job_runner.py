"""Run a short LLM job (suggest / review) in a background thread and stream its log.

Unlike scans (which run as a subprocess), these are in-process LLM calls. We
capture the "autopilot" logger's INFO output for the duration of the job and
publish each line to SSE subscribers — so the browser sees the same progress the
suggester logs ("Suggesting 8 companies…", "Reviewing companies 1-50…", etc.).

One job at a time.
"""
import logging
import queue
import threading
import time
from collections import deque
from datetime import datetime, timezone

from job_hunt.log import get_logger

logger = get_logger()
_MAX_BUFFER = 1000


class _QueueLogHandler(logging.Handler):
    def __init__(self, sink) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink(self.format(record))
        except Exception:
            pass


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=_MAX_BUFFER)
        self._subs: list[queue.Queue] = []
        self._thread: threading.Thread | None = None
        self.name: str | None = None
        self.running = False
        self.done = False
        self.ok: bool | None = None
        self.error: str | None = None
        self.result: object = None
        self.started_at: str | None = None

    def status(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "done": self.done,
            "ok": self.ok,
            "error": self.error,
            "started_at": self.started_at,
        }

    def start(self, name: str, target) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("Another suggestion job is already running.")
            self.name = name
            self.running = True
            self.done = False
            self.ok = None
            self.error = None
            self.result = None
            self._lines.clear()
            self.started_at = datetime.now(timezone.utc).isoformat()
        self._emit(f"$ {name}")
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True)
        self._thread.start()

    def _run(self, target) -> None:
        handler = _QueueLogHandler(self._emit)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        t0 = time.time()
        try:
            self.result = target()
            self.ok = True
            self._emit(f"-- done ({time.time() - t0:.0f}s) --")
        except Exception as e:  # surfaced to the browser as the final line + status
            self.ok = False
            self.error = str(e)
            self._emit(f"-- error: {e} --")
        finally:
            logger.removeHandler(handler)
            self.running = False
            self.done = True
            self._broadcast(None)

    def _emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
        self._broadcast(line)

    def _broadcast(self, item: str | None) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_MAX_BUFFER)
        with self._lock:
            for line in self._lines:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    break
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


runner = JobRunner()
