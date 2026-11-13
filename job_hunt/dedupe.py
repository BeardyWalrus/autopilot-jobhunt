"""Tell when two job listings are the same job, and fold repeats into one.

The same posting reaches a scan under many URLs: a careers-page link and a
search hit, tracking parameters (``utm_*``, ``gh_src``, ``lever-source``), a
trailing slash or ``/apply``, ``http`` vs ``https``, a Workday locale segment.
Matching on the exact URL string let each of those through as a new job.

Two jobs are treated as the same when either

* they share a **job key**: the ATS's own job ID where we can read one from the
  URL (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday req ID),
  otherwise the canonical URL; or
* they share a **match key**: the same company, title and location once case,
  accents and punctuation are ignored. This catches a job reposted under a new
  ID. Jobs with the same title in different locations stay separate.

Folded rows keep one primary ``url`` (the first one seen) and list every link in
``sources``, so nothing is lost and the user can still open each posting.
See ADR 0002 (docs/adr/0002-collapse-duplicate-job-listings.md).
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only say where a click came from, never which job.
_TRACKING_PARAMS = {
    "gh_src", "source", "src", "ref", "referer", "referrer", "lever-source",
    "lever-origin", "lever-via", "trk", "trackingid", "fbclid", "gclid",
    "mc_cid", "mc_eid", "ccuid", "iis", "iisn", "codes", "jobpipeline",
    "utm", "_ga", "share", "shared", "from",
}
_TRACKING_PREFIXES = ("utm_", "_hs", "hs_", "pk_", "mtm_")
_APPLY_SUFFIX_RE = re.compile(r"/(apply|application|applynow)$", re.IGNORECASE)
_WORKDAY_LOCALE_RE = re.compile(r"^/[a-z]{2}-[A-Z]{2}(?=/)")

_GREENHOUSE_RE = re.compile(r"greenhouse\.io/.*?/jobs/(\d+)", re.IGNORECASE)
_GH_JID_RE = re.compile(r"[?&]gh_jid=(\d+)", re.IGNORECASE)
_LEVER_RE = re.compile(
    r"lever\.co/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_ASHBY_RE = re.compile(
    r"ashbyhq\.com/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_SMARTRECRUITERS_RE = re.compile(r"smartrecruiters\.com/[^/]+/(\d{6,})", re.IGNORECASE)
_WORKABLE_RE = re.compile(r"workable\.com/[^/]+/j/([A-Z0-9]{6,})", re.IGNORECASE)
_WORKDAY_REQ_RE = re.compile(r"_([A-Za-z]{0,4}-?\d[\w-]*)/?$")

_STATUS_RANK = {"applied": 2, "not_applied": 1, "new": 0}


def canonical_url(url: str) -> str:
    """The URL with everything that doesn't identify the job stripped off.

    Lower-cases the host, drops ``www.``, the fragment, tracking parameters, a
    trailing slash or ``/apply``, and Workday's locale segment; forces https.
    Strings that aren't URLs come back trimmed but otherwise unchanged.
    """
    raw = (url or "").strip()
    if "://" not in raw and not raw.lower().startswith("www."):
        return raw
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = re.sub(r"/{2,}", "/", parts.path or "")
    if "myworkdayjobs.com" in host:
        path = _WORKDAY_LOCALE_RE.sub("", path)
    path = path.rstrip("/")
    path = _APPLY_SUFFIX_RE.sub("", path)
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
        and not k.lower().startswith(_TRACKING_PREFIXES)
    )
    return urlunsplit(("https", host, path, urlencode(query), ""))


def ats_job_id(url: str) -> str | None:
    """The applicant-tracking system's own ID for the job, if the URL shows one."""
    u = url or ""
    for name, rx in (
        ("greenhouse", _GREENHOUSE_RE),
        ("greenhouse", _GH_JID_RE),
        ("lever", _LEVER_RE),
        ("ashby", _ASHBY_RE),
        ("smartrecruiters", _SMARTRECRUITERS_RE),
        ("workable", _WORKABLE_RE),
    ):
        m = rx.search(u)
        if m:
            return f"{name}:{m.group(1).lower()}"
    parts = urlsplit(u if "://" in u else f"https://{u}")
    host = (parts.hostname or "").lower()
    if host.endswith("myworkdayjobs.com") and "/job/" in parts.path:
        m = _WORKDAY_REQ_RE.search(parts.path)
        if m:
            tenant = host.split(".")[0]
            return f"workday:{tenant}:{m.group(1).lower()}"
    return None


def job_key(url: str) -> str:
    """One key per posting: the ATS job ID when we can read it, else the canonical URL."""
    return ats_job_id(url) or f"url:{canonical_url(url)}"


def _norm_text(s: object) -> str:
    text = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def match_key(job: dict) -> str | None:
    """Same company, same title, same location, ignoring case and punctuation."""
    title = _norm_text(job.get("extracted_title") or job.get("title"))
    company = _norm_text(job.get("company"))
    if not title or not company:
        return None
    location = _norm_text(job.get("location_remote") or job.get("location"))
    return f"match:{company}|{title}|{location}"


def job_urls(job: dict) -> list[str]:
    """Every link we hold for a job: its primary URL first, then its other sources."""
    urls: list[str] = []
    for u in [job.get("url"), *(job.get("sources") or [])]:
        if isinstance(u, str) and u and u not in urls:
            urls.append(u)
    return urls


def _keys(job: dict) -> set[str]:
    keys = {job_key(u) for u in job_urls(job)}
    mk = match_key(job)
    if mk:
        keys.add(mk)
    return keys


def _absorb(kept: dict, other: dict, refresh: bool) -> None:
    """Fold ``other`` into ``kept``: keep kept's primary URL, gather every link,
    and keep the furthest-along status (applied > not a fit > new)."""
    urls = job_urls(kept)
    for u in job_urls(other):
        if u not in urls:
            urls.append(u)
    has_status = "status" in kept or "status" in other
    status = max(
        (kept.get("status", "new"), other.get("status", "new")),
        key=lambda s: _STATUS_RANK.get(s, 0),
    )
    primary = kept.get("url") or other.get("url")
    if refresh:
        kept.update({k: v for k, v in other.items() if k not in ("url", "sources", "status")})
    elif not kept.get("pay") and other.get("pay"):
        kept["pay"] = other["pay"]  # a repeat listing that names the pay fills the gap
    kept["url"] = primary
    if has_status:
        kept["status"] = status
    if len(urls) > 1:
        kept["sources"] = urls


def collapse_duplicates(jobs: list[dict], new_jobs: list[dict] | None = None) -> list[dict]:
    """Fold repeat listings into one row each, keeping order of first appearance.

    ``jobs`` are folded together keeping the first row's fields. ``new_jobs``
    (a fresh scan) are then folded in; when one matches an existing row it
    refreshes that row's scored fields but never its URL or the user's status.
    Input dicts are copied, not changed.
    """
    ordered: list[dict] = []
    index: dict[str, dict] = {}

    def add(job: dict, refresh: bool) -> None:
        if not isinstance(job, dict):
            return
        entry = dict(job)
        keys = _keys(entry)
        hits: list[dict] = []
        for k in keys:
            hit = index.get(k)
            if hit is not None and not any(hit is h for h in hits):
                hits.append(hit)
        if not hits:
            ordered.append(entry)
            target = entry
        else:
            # The earliest row wins; if this job bridges two rows, fold them too.
            hits.sort(key=lambda h: next(i for i, o in enumerate(ordered) if o is h))
            target = hits[0]
            for extra in hits[1:]:
                _absorb(target, extra, refresh=False)
                ordered[:] = [o for o in ordered if o is not extra]
            _absorb(target, entry, refresh=refresh)
        for k in _keys(target):
            index[k] = target

    for j in jobs:
        add(j, refresh=False)
    for j in new_jobs or []:
        add(j, refresh=True)
    return ordered


def find_job(jobs: list[dict], url: str) -> int:
    """Index of the row holding ``url`` (as its primary link or a source), or -1."""
    wanted = job_key(url)
    for i, j in enumerate(jobs):
        if isinstance(j, dict) and any(u == url or job_key(u) == wanted for u in job_urls(j)):
            return i
    return -1


def backup_once(path: Path, data: object) -> Path | None:
    """Save ``data`` next to ``path`` as ``<name>.pre-dedupe.json`` the first time
    duplicates are folded, so the clean-up can be undone. Never overwrites."""
    backup = path.with_name(f"{path.stem}.pre-dedupe.json")
    if backup.exists():
        return None
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(data, indent=2))
    return backup
