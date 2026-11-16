"""A ledger of every Claude call this app makes on the Claude plan (ADR 0006).

One JSON line per call in the project's state folder (`/data/state` in
Docker), so it survives image updates. It holds only what the call cost:
when, which feature, the model, tokens in and out, the API-rate estimate the
provider gives, how long it took and whether it worked. Never a prompt, a
reply, the resume or a listing.

GET /api/usage reads it back as totals by feature, in the same shape as the
art app (open-call-finder), so the home dashboard can show this app's share
of the plan.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from job_hunt.log import get_logger

logger = get_logger()

FILE_NAME = "claude_usage.jsonl"
KEEP_DAYS = 90
TOKEN_KEYS = ("input", "output", "cache_read", "cache_create")

_lock = threading.Lock()


def ledger_path() -> Path:
    """`state/claude_usage.jsonl` in the project folder (AUTOPILOT_HOME, else
    the working directory, like the other state files)."""
    return Path(os.getenv("AUTOPILOT_HOME", ".")).resolve() / "state" / FILE_NAME


def tokens_from(raw: Any) -> dict[str, int]:
    """A provider's usage dict in the four counts the ledger keeps."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, name in (("input", "input_tokens"), ("output", "output_tokens"),
                      ("cache_read", "cache_read_input_tokens"),
                      ("cache_create", "cache_creation_input_tokens")):
        try:
            out[key] = max(0, int(raw.get(name) or 0))
        except (TypeError, ValueError):
            out[key] = 0
    return out


def record(
    *,
    feature: str,
    model: str,
    ok: bool,
    tokens: dict[str, int] | None = None,
    cost_estimate_usd: float | None = None,
    duration_ms: int = 0,
    error: str = "",
    path: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Add one call to the ledger. A write that fails is logged, never raised:
    the call itself already happened."""
    tokens = tokens or {}
    entry = {
        "at": (now or datetime.now()).isoformat(timespec="seconds"),
        "feature": feature or "other",
        "model": model or "",
        "ok": bool(ok),
        **{k: int(tokens.get(k, 0) or 0) for k in TOKEN_KEYS},
        "cost_estimate_usd": cost_estimate_usd,
        "duration_ms": int(duration_ms),
        "error": (error or "")[:200] or None,
    }
    target = path or ledger_path()
    with _lock:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning(f"usage: could not write the ledger: {e}")


def _read(path: Path, since: datetime) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        logger.warning(f"usage: could not read the ledger: {e}")
        return []
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
            if datetime.fromisoformat(entry["at"]) >= since:
                out.append(entry)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"calls": 0, "failed": 0, **{k: 0 for k in TOKEN_KEYS}, "cost_estimate_usd": 0.0}
    for e in entries:
        out["calls"] += 1
        if not e.get("ok"):
            out["failed"] += 1
        for k in TOKEN_KEYS:
            out[k] += int(e.get(k, 0) or 0)
        out["cost_estimate_usd"] += float(e.get("cost_estimate_usd") or 0.0)
    out["cost_estimate_usd"] = round(out["cost_estimate_usd"], 4)
    return out


def summary(path: Path | None = None, since: datetime | None = None,
            now: datetime | None = None) -> dict[str, Any]:
    """Totals since `since` (default the last 7 days), overall and by feature."""
    now = now or datetime.now()
    since = since or now - timedelta(days=7)
    entries = _read(path or ledger_path(), since)
    by_feature: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_feature.setdefault(str(e.get("feature") or "other"), []).append(e)
    return {
        "app": "autopilot-jobhunt",
        "since": since.isoformat(timespec="seconds"),
        "now": now.isoformat(timespec="seconds"),
        "total": _totals(entries),
        "by_feature": {name: _totals(items) for name, items in sorted(by_feature.items())},
        "last_call_at": entries[-1]["at"] if entries else None,
    }


def prune(path: Path | None = None, now: datetime | None = None) -> int:
    """Drop calls older than KEEP_DAYS. Returns how many were dropped."""
    target = path or ledger_path()
    if not target.exists():
        return 0
    cutoff = (now or datetime.now()) - timedelta(days=KEEP_DAYS)
    with _lock:
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        kept = []
        for line in lines:
            try:
                if datetime.fromisoformat(json.loads(line)["at"]) >= cutoff:
                    kept.append(line)
            except (ValueError, KeyError, TypeError):
                continue
        dropped = len(lines) - len(kept)
        if dropped:
            try:
                target.write_text("".join(k + "\n" for k in kept), encoding="utf-8")
            except OSError as e:
                logger.warning(f"usage: could not prune the ledger: {e}")
                return 0
        return dropped
