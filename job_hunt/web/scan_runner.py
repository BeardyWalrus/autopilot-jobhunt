"""Run scans as a subprocess and stream their output.

The scan is launched as `python -m job_hunt.main scan` in the project directory,
exactly as the CLI runs it. Running it out-of-process (rather than calling
run_scan in a thread) buys three things:

- **Live log**: we read the child's stdout line by line — and the scanner now
  logs per-batch progress at INFO, so the browser sees real activity.
- **Real stop**: terminating the process actually stops the scan.
- **Isolation**: the long scan can't wedge the web server's event loop or share
  its module-level logger/state.

Only one scan runs at a time.
"""
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from job_hunt.web.paths import project_dir

_MAX_BUFFER = 2000  # keep the last N log lines for late-joining viewers


def _subprocess_env() -> dict:
    """Env for the scan child: make job_hunt importable regardless of cwd.

    The child runs with cwd=project_dir (so it reads that project's config),
    which means `python -m job_hunt.main` can't rely on cwd to find the package.
    Prepend the directory that contains the job_hunt package to PYTHONPATH — a
    no-op when it's already installed (Docker), essential when running from source.
    """
    import job_hunt
    pkg_parent = str(Path(job_hunt.__file__).resolve().parent.parent)
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pkg_parent + (os.pathsep + existing if existing else "")
    return env


class ScanRunner:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lines: deque[str] = deque(maxlen=_MAX_BUFFER)
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._exit_code: int | None = None
        self._reader: threading.Thread | None = None

    # --- state ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict:
        return {
            "running": self.running,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "exit_code": self._exit_code,
            "line_count": len(self._lines),
            "last_line": self._lines[-1] if self._lines else None,
        }

    def recent_lines(self, limit: int = _MAX_BUFFER) -> list[str]:
        with self._lock:
            return list(self._lines)[-limit:]

    # --- control -------------------------------------------------------------

    def start(self, extra_args: list[str] | None = None) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("A scan is already running.")
            self._lines.clear()
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._finished_at = None
            self._exit_code = None
            cmd = [sys.executable, "-m", "job_hunt.main", "scan", *(extra_args or [])]
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(project_dir()),
                env=_subprocess_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        self._emit(f"$ {' '.join(cmd)}")
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def stop(self) -> bool:
        with self._lock:
            if not self.running:
                return False
            assert self._proc is not None
            self._proc.terminate()
        self._emit("-- stop requested --")
        return True

    # --- internals -----------------------------------------------------------

    def _pump(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._emit(line.rstrip("\n"))
        code = proc.wait()
        self._exit_code = code
        self._finished_at = datetime.now(timezone.utc).isoformat()
        self._emit(f"-- scan finished (exit {code}) --")
        self._broadcast(None)  # sentinel: closes open SSE streams

    def _emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
        self._broadcast(line)

    def _broadcast(self, item: str | None) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=_MAX_BUFFER)
        with self._lock:
            # Replay what's already buffered so a late viewer sees the whole run.
            for line in self._lines:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    break
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


# One shared runner for the process.
runner = ScanRunner()
