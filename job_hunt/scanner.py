import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from tinyfish import RateLimitError, TinyFish

from job_hunt.llm_utils import chat_with_llm
from job_hunt.log import get_logger
from job_hunt.notifier import send_telegram

logger = get_logger()


class ScoringError(RuntimeError):
    """Raised when the LLM can't be reached or its scoring output can't be parsed.

    run_scan catches this per batch and saves those jobs unscored, so a transient
    LLM problem never silently drops jobs (they'd otherwise be marked seen and
    never retried).
    """


def _telegram_configured(tg: dict) -> bool:
    """True only when Telegram has a real token AND chat_id.

    The shipped config template seeds telegram.token / chat_id with placeholder
    values (e.g. "YOUR_TELEGRAM_BOT_TOKEN"), which are truthy. Treat those — and
    the `your_..._here` env-style placeholders — as unconfigured so the scan
    doesn't try to send to Telegram when it was never actually set up.
    """
    def real(val) -> bool:
        if not isinstance(val, str):
            return bool(val)
        v = val.strip()
        if not v:
            return False
        return not (v.startswith("YOUR_") or v.endswith("_HERE") or v.endswith("_here"))

    return real(tg.get("token")) and real(tg.get("chat_id"))


STATE_FILE = Path("state/seen_jobs.json")
LAST_SCAN_FILE = Path("state/last_scan.json")
JOB_HISTORY_FILE = Path("state/job_history.json")
# Cumulative, status-carrying results shown in the web UI. Unlike last_scan.json
# (which is overwritten each run, for the CLI's `draft N`), this accumulates
# across runs and keeps each job until it's marked applied/not-a-fit or deleted.
RESULTS_FILE = Path("state/results.json")
RESULT_STATUSES = ("new", "applied", "not_applied")

JOB_URL_RE = re.compile(
    r"/(job|jobs|opening|openings|position|positions|vacancy|vacancies|role|roles|apply)"
    r"/[a-zA-Z0-9_%@.-]{4,}",
    re.IGNORECASE,
)
ATS_JOB_RE = re.compile(
    r"(greenhouse\.io/.+/jobs/\d+"
    r"|lever\.co/[^/]+/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
    r"|myworkdayjobs\.com/[^?#]+"
    r"|smartrecruiters\.com/[^/]+/[A-Z0-9]+"
    r"|ashbyhq\.com/[^/]+/[a-f0-9-]{32,})",
    re.IGNORECASE,
)
ATS_LISTING_RE = re.compile(
    r"^https?://(jobs\.lever\.co|boards\.greenhouse\.io|apply\.workable\.com"
    r"|jobs\.smartrecruiters\.com)/[^/?#]+/?(\?.*)?$",
    re.IGNORECASE,
)

DEFAULT_SEARCH_SENIORITY = "senior OR staff OR principal OR lead"
DEFAULT_SEARCH_KEYWORDS = (
    '"data scientist" OR "ML engineer" OR "machine learning engineer" '
    'OR "AI engineer" OR MLOps OR "deep learning"'
)


DEFAULT_SCORE_BATCH_SIZE = 5


def _score_batch_size(config: dict) -> int:
    """How many jobs to score per LLM call. Smaller batches mean a shorter prompt
    and fewer output tokens per call, which weak/local models complete and format
    far more reliably (a large batch is the usual cause of unparseable output).

    Read from config `score_batch_size` (or candidate.score_batch_size), clamped
    to 1–20; defaults to 5.
    """
    raw = config.get("score_batch_size")
    if raw is None:
        raw = config.get("candidate", {}).get("score_batch_size")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SCORE_BATCH_SIZE
    return max(1, min(20, n))


def build_search_query(domain: str, candidate: dict) -> str:
    seniority = candidate.get("search_seniority") or DEFAULT_SEARCH_SENIORITY
    keywords = candidate.get("search_keywords") or DEFAULT_SEARCH_KEYWORDS
    return f'site:{domain} ({seniority}) ({keywords})'

SCORE_PROMPT = """You are evaluating job postings for a candidate.

CANDIDATE:
{candidate_profile}

RESUME SUMMARY:
{resume_summary}

JOBS TO SCORE:
{jobs_text}

For EACH job, output one block in EXACTLY this format. Separate blocks with a
line containing only three dashes (---). Do not add anything else — no preamble,
no explanations, no markdown.

JOB: 1
SCORE: 0-100
TITLE: extracted job title
STACK: key tech from the posting, comma-separated, max 6 items
LOCATION: location + remote policy
WORTH: yes or no
REASON: one sentence on why it fits or doesn't fit the candidate
---

Scoring: 80-100 near-perfect; 60-79 good fit; 40-59 partial; <40 poor.
Set WORTH to yes only if SCORE is at least {min_score}.
Score every job in the list."""

EXPORT_FIELDS = [
    "Company", "Role", "Location", "Application URL",
    "Score (%)", "Stack", "Region", "Reason", "Worth Applying", "Scan Date",
]


def _build_candidate_profile(config: dict) -> str:
    cand = config.get("candidate", {})
    name = cand.get("name", "the candidate")
    profile = cand.get("profile", "")
    seeking = cand.get("seeking", "")
    not_suitable = cand.get("not_suitable", "")

    lines = [f"- {name}"]
    if profile:
        lines.append(f"- {profile}")
    if seeking:
        lines.append(f"- Seeking: {seeking}")
    if not_suitable:
        lines.append(f"- NOT suitable: {not_suitable}")
    return "\n".join(lines)


def is_job_url(url: str) -> bool:
    return bool(JOB_URL_RE.search(url)) or bool(ATS_JOB_RE.search(url))


def is_ats_listing(url: str) -> bool:
    return bool(ATS_LISTING_RE.match(url))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_urls": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


_FETCH_URL_DELAY = 2.5


def _fetch_with_ratelimit(tf: TinyFish, urls: list[str], **kwargs):
    for attempt in range(2):
        try:
            resp = tf.fetch.get_contents(urls, **kwargs)
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return resp
        except RateLimitError:
            logger.warning("Fetch rate-limited — waiting 65s before retry...")
            time.sleep(65)
        except Exception as e:
            logger.error(f"Fetch error for {urls[:1]}: {e}")
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return None
    return None


def _fetch_links(tf: TinyFish, urls: list[str]) -> dict[str, list[str]]:
    result = {}
    for i in range(0, len(urls), 10):
        batch = urls[i: i + 10]
        resp = _fetch_with_ratelimit(tf, batch, format="markdown", links=True)
        if resp:
            for r in resp.results:
                result[r.url] = r.links
    return result


def discover_job_urls(
    tf: TinyFish, company: dict, seen_urls: set, candidate: dict | None = None
) -> list[dict]:
    found_urls: set[str] = set()

    logger.debug(f"  [{company['name']}] Fetching careers page: {company['careers_url']}")
    resp = _fetch_with_ratelimit(tf, [company["careers_url"]], format="markdown", links=True)
    if resp and resp.results:
        links = resp.results[0].links
        direct = [link for link in links if is_job_url(link) and link not in seen_urls]
        ats_pages = list({link for link in links if is_ats_listing(link)})
        found_urls.update(direct)
        logger.debug(f"  [{company['name']}] Careers page: {len(direct)} direct job links, {len(ats_pages)} ATS listing pages")

        if ats_pages:
            logger.debug(f"  [{company['name']}] Expanding {len(ats_pages)} ATS listing page(s)...")
            ats_link_map = _fetch_links(tf, ats_pages[:5])
            ats_jobs = 0
            for page_links in ats_link_map.values():
                for link in page_links:
                    if is_job_url(link) and link not in seen_urls:
                        found_urls.add(link)
                        ats_jobs += 1
            logger.debug(f"  [{company['name']}] ATS expansion: {ats_jobs} additional job links")

    query = build_search_query(company["search_domain"], candidate or {})
    logger.debug(f"  [{company['name']}] Search query: {query}")
    for attempt in range(2):
        try:
            resp = tf.search.query(query, language="en")
            search_new = 0
            for r in resp.results:
                if is_job_url(r.url) and r.url not in seen_urls:
                    found_urls.add(r.url)
                    search_new += 1
            logger.debug(f"  [{company['name']}] Search: {len(resp.results)} results, {search_new} new job URLs")
            time.sleep(13)
            break
        except RateLimitError:
            logger.warning(f"  [{company['name']}] Search rate-limited — waiting 60s...")
            time.sleep(62)
        except Exception as e:
            logger.error(f"  [{company['name']}] Search error: {e}")
            time.sleep(13)
            break

    new = [
        {
            "url": u,
            "title": u.split("/")[-1].replace("-", " ").title(),
            "snippet": "",
            "company": company["name"],
            "location": company["location"],
            "region": company["region"],
        }
        for u in found_urls
    ]
    return new


def _fetch_details_batch(tf: TinyFish, batch: list[dict]) -> int:
    """Fetch + enrich one batch (<=10 jobs) in place.

    Returns the number of jobs whose content was fetched, or -1 if the fetch
    call itself failed (jobs are left unenriched but still usable). Kept separate
    from fetch_job_details so run_scan can drive batching itself and checkpoint
    after each batch.
    """
    urls = [j["url"] for j in batch]
    logger.debug(f"    Batch URLs: {[j['title'][:40] for j in batch]}")
    resp = _fetch_with_ratelimit(tf, urls, format="markdown")
    if not resp:
        return -1
    fetched = {r.url: r for r in resp.results}
    got = 0
    for job in batch:
        r = fetched.get(job["url"])
        if r and r.text:
            job["content"] = r.text[:3000]
            job["title"] = r.title or job["title"]
            got += 1
            logger.debug(f"      Fetched '{job['title']}' — {len(r.text)} chars")
        else:
            logger.debug(f"      No content for: {job['url']}")
    return got


def fetch_job_details(tf: TinyFish, jobs: list[dict], label: str = "") -> list[dict]:
    total = len(jobs)
    total_batches = (total + 9) // 10
    prefix = f"  [{label}] " if label else "  "
    for i in range(0, total, 10):
        batch = jobs[i: i + 10]
        batch_num = i // 10 + 1
        # INFO (not DEBUG) so the long, rate-limit-paced fetch loop reports live
        # progress instead of going silent for minutes after "fetching details...".
        logger.info(
            f"{prefix}Fetching details: batch {batch_num}/{total_batches} "
            f"({min(i + len(batch), total)}/{total} jobs)..."
        )
        got = _fetch_details_batch(tf, batch)
        if got < 0:
            logger.warning(f"{prefix}Batch {batch_num}/{total_batches} returned no content — keeping URLs unenriched")
        else:
            logger.info(f"{prefix}Batch {batch_num}/{total_batches} done — {got}/{len(batch)} enriched")
    return jobs


# Map the many key spellings a model might emit onto our canonical field names.
_FIELD_ALIASES = {
    "job": "job_number", "job_number": "job_number", "number": "job_number", "num": "job_number",
    "score": "score", "rating": "score",
    "title": "title", "role": "title", "position": "title",
    "stack": "stack", "tech": "stack", "technologies": "stack", "skills": "stack",
    "location": "location_remote", "location_remote": "location_remote",
    "remote": "location_remote", "remote_policy": "location_remote",
    "worth": "worth_applying", "worth_applying": "worth_applying", "apply": "worth_applying",
    "reason": "reason", "why": "reason", "notes": "reason",
}
_TRUTHY = {"yes", "true", "y", "1", "worth applying", "apply", "worth"}
_KV_RE = re.compile(r"^\s*([A-Za-z_#][A-Za-z_ ]*?)\s*[:=]\s*(.*)$")


def _coerce_int(val: object, default: int = 0) -> int:
    m = re.search(r"-?\d+", str(val))
    return int(m.group()) if m else default


def _coerce_bool(val: object) -> bool:
    return str(val).strip().lower() in _TRUTHY


def _normalize_record(rec: dict, fallback_number: int) -> dict:
    """Coerce one raw record into our canonical schema.

    worth_applying is left as None when the model didn't say — the caller then
    derives it from score vs. min_score, so a model that scores well but forgets
    the WORTH line still surfaces the job.
    """
    worth = rec.get("worth_applying")
    return {
        "job_number": _coerce_int(rec.get("job_number", fallback_number), fallback_number),
        "score": max(0, min(100, _coerce_int(rec.get("score", 0)))),
        "title": (str(rec.get("title", "")).strip() or "?"),
        "stack": str(rec.get("stack", "")).strip(),
        "location_remote": str(rec.get("location_remote", "")).strip(),
        "worth_applying": (_coerce_bool(worth) if worth is not None else None),
        "reason": str(rec.get("reason", "")).strip(),
    }


def _parse_block_format(raw: str) -> list[dict]:
    """Parse the documented `KEY: value` block format, tolerantly.

    Unknown lines are ignored; a `---` (or blank-run) separator or a fresh `JOB:`
    line starts a new record. Case-insensitive keys, `:` or `=` accepted.
    """
    records: list[dict] = []
    cur: dict = {}

    def flush() -> None:
        if cur:
            records.append(_normalize_record(cur, len(records) + 1))
            cur.clear()

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if set(s) <= {"-", "=", "*", "_"} and len(s) >= 3:  # separator rule
            flush()
            continue
        m = _KV_RE.match(s)
        if not m:
            continue
        raw_key = m.group(1).strip().lower().lstrip("#").strip()
        key = _FIELD_ALIASES.get(raw_key)
        if key is None:
            continue
        if key == "job_number" and ("job_number" in cur or "score" in cur):
            flush()  # a new JOB: line begins the next record
        cur[key] = m.group(2).strip()
    flush()
    return records


def _parse_scored_output(raw: str) -> list[dict]:
    """Turn the scorer's raw output into normalized records.

    Tolerant by design so weak local models (e.g. small Ollama models) don't
    silently score nothing: tries a JSON array first (strong models emit one
    even when asked for blocks), then falls back to the `KEY: value` block format.
    """
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, list) and data:
                recs = []
                for i, d in enumerate(data, 1):
                    if isinstance(d, dict):
                        aliased = {
                            _FIELD_ALIASES.get(str(k).strip().lower(), str(k).strip().lower()): v
                            for k, v in d.items()
                        }
                        recs.append(_normalize_record(aliased, i))
                if recs:
                    return recs
        except Exception:
            pass
    return _parse_block_format(raw)


def score_jobs(jobs: list[dict], resume: str, config: dict) -> list[dict]:
    if not jobs:
        return []

    jobs_text = "\n\n".join(
        f"JOB {i + 1}:\nCompany: {j['company']} | Location: {j['location']}\n"
        f"Title: {j['title']}\nURL: {j['url']}\n"
        f"Content:\n{j.get('content', j.get('snippet', ''))[:1500]}"
        for i, j in enumerate(jobs)
    )

    min_score = config.get("candidate", {}).get("min_score", 55)
    candidate_profile = _build_candidate_profile(config)

    prompt = SCORE_PROMPT.format(
        candidate_profile=candidate_profile,
        resume_summary=resume[:2500],
        jobs_text=jobs_text,
        min_score=min_score,
    )

    provider = config.get("llm_provider") or "openrouter"
    logger.debug(f"  Scoring {len(jobs)} job(s) via LLM (min_score={min_score})...")
    t0 = time.time()
    try:
        raw = chat_with_llm(
            config,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
    except Exception as e:
        # Let the caller's batch handler preserve these jobs unscored rather than
        # losing them: score_jobs returning [] would mark them seen and drop them.
        raise ScoringError(f"{provider} LLM call failed: {e}") from e
    elapsed = time.time() - t0

    scored = _parse_scored_output(raw)
    if not scored:
        # Surface WHAT came back at ERROR level (not DEBUG) so the failure is
        # debuggable from the normal scan log — the output is short here by
        # definition, so printing it is cheap and diagnostic.
        preview = raw.strip()
        logger.error(
            f"  Could not parse any scored jobs from the {provider} LLM output "
            f"({len(raw)} chars). Raw output: {preview[:500]!r}"
        )
        if len(preview) < 20:
            logger.error(
                "  The model returned almost nothing — likely an empty response. "
                "Common causes: a 'reasoning' model that spent its whole token budget "
                "thinking and returned empty content (raise max_tokens or switch to a "
                "non-reasoning model), a small local model that can't follow the scoring "
                "format, or a hit quota / rate limit."
            )
        # Raise so the batch is saved unscored (see caller) instead of silently
        # dropped — a parse failure shouldn't cost us the jobs permanently.
        raise ScoringError(f"{provider} returned unparseable scoring output ({len(raw)} chars)")
    logger.debug(f"  LLM scoring complete in {elapsed:.1f}s — {len(scored)} results parsed")

    results = []
    for item in scored:
        score = item["score"]
        title = item["title"]
        reason = item["reason"]
        # If the model didn't explicitly mark worth, fall back to the threshold —
        # a good score with a missing/garbled WORTH line still surfaces the job.
        worth = item["worth_applying"]
        if worth is None:
            worth = score >= min_score
        logger.debug(f"    [{score:3d}] {title} — {reason[:80]}")
        if not worth:
            continue
        idx = item["job_number"] - 1
        if 0 <= idx < len(jobs):
            job = jobs[idx].copy()
            job.update(
                {
                    "score": score,
                    "extracted_title": title,
                    "stack": item["stack"],
                    "location_remote": item["location_remote"] or job["location"],
                    "reason": reason,
                }
            )
            results.append(job)

    passing = len(results)
    logger.debug(f"  {passing}/{len(scored)} jobs passed min_score threshold")
    return sorted(results, key=lambda x: x["score"], reverse=True)


def format_telegram_message(top_jobs: list[dict], date_str: str) -> str:
    lines = [f"<b>Job Hunt — {date_str}</b>", f"<i>{len(top_jobs)} matches found</i>\n"]
    for i, job in enumerate(top_jobs, 1):
        lines.append(
            f"<b>#{i}</b> | {job['company']} | {job.get('extracted_title', job['title'])}\n"
            f"📍 {job.get('location_remote', job['location'])}\n"
            f"🔧 {job.get('stack', 'N/A')}\n"
            f"✅ {job.get('reason', '')}\n"
            f"<a href=\"{job['url']}\">Apply</a>\n"
        )
    lines.append('Reply "apply to #N" to draft application.')
    return "\n".join(lines)


def _export_to_csv(jobs: list[dict], label: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path("output") / f"jobs_{date_str}.csv"
    out_path.parent.mkdir(exist_ok=True)

    def _row(j: dict) -> dict:
        worth = j.get("worth_applying")
        return {
            "Company": j.get("company", ""),
            "Role": j.get("extracted_title") or j.get("title", ""),
            "Location": j.get("location_remote") or j.get("location", ""),
            "Application URL": j.get("url", ""),
            "Score (%)": j.get("score", ""),
            "Stack": j.get("stack", ""),
            "Region": j.get("region", ""),
            "Reason": j.get("reason", ""),
            "Worth Applying": "Yes" if worth else ("No" if worth is False else ""),
            "Scan Date": j.get("scan_date", ""),
        }

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for j in jobs:
            writer.writerow(_row(j))

    logger.info(f"Results exported to CSV ({label}): {out_path}")
    return out_path


def _merge_results(all_scored_jobs: list[dict]) -> None:
    """Merge this run's jobs into the cumulative results store (results.json).

    New jobs are appended with status "new"; jobs already present keep their
    status (applied / not_applied / new) but have their scored fields refreshed.
    Nothing is ever removed here — the user removes results in the UI. Seeds from
    last_scan.json on first use so existing installs don't lose their last run.
    """
    existing: list[dict] = []
    if RESULTS_FILE.exists():
        try:
            existing = json.loads(RESULTS_FILE.read_text())
        except Exception:
            existing = []
    elif LAST_SCAN_FILE.exists():
        # Migration: fold the previous run (about to be overwritten) into the store.
        try:
            for j in json.loads(LAST_SCAN_FILE.read_text()):
                if isinstance(j, dict):
                    existing.append({**j, "status": j.get("status", "new")})
        except Exception:
            existing = []

    by_url: dict[str, dict] = {}
    ordered: list[dict] = []
    for j in existing:
        url = j.get("url") if isinstance(j, dict) else None
        if url and url not in by_url:
            by_url[url] = j
            ordered.append(j)
    for job in all_scored_jobs:
        url = job.get("url")
        if not url:
            continue
        if url in by_url:
            prev = by_url[url]
            status = prev.get("status", "new")
            prev.update(job)
            prev["status"] = status  # refresh score/title/etc. but keep the user's status
        else:
            entry = {**job, "status": job.get("status", "new")}
            by_url[url] = entry
            ordered.append(entry)

    RESULTS_FILE.write_text(json.dumps(ordered, indent=2))


def _persist_scan(all_scored_jobs: list[dict]) -> int:
    """Write last_scan.json, merge into results.json, and append to job_history.json.

    Idempotent and safe to call repeatedly mid-scan: history and results are
    deduped by URL, so incremental checkpoints leave a complete, up-to-date record
    on disk even if a later company crashes the run. Returns new history rows.
    """
    LAST_SCAN_FILE.parent.mkdir(exist_ok=True)
    # Merge into the cumulative store BEFORE overwriting last_scan, so the first
    # run after an upgrade can still recover the previous run from last_scan.json.
    _merge_results(all_scored_jobs)
    LAST_SCAN_FILE.write_text(json.dumps(all_scored_jobs, indent=2))

    history: list[dict] = []
    if JOB_HISTORY_FILE.exists():
        try:
            history = json.loads(JOB_HISTORY_FILE.read_text())
        except Exception:
            history = []
    existing_urls = {j["url"] for j in history}
    new_entries = [j for j in all_scored_jobs if j["url"] not in existing_urls]
    if new_entries:
        history.extend(new_entries)
        JOB_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    return len(new_entries)


def run_scan(config: dict, companies: list[dict]) -> None:
    scan_start = time.time()
    # A company is scanned unless explicitly disabled ("enabled": false). The key
    # is optional, so existing companies.json files scan exactly as before.
    active = [c for c in companies if c.get("enabled", True)]
    skipped = len(companies) - len(active)
    companies = active
    total = len(companies)
    suffix = f" ({skipped} disabled, skipped)" if skipped else ""
    logger.info(f"=== Scan started — {total} companies to check{suffix} ===")
    logger.info(f"Candidate: {config.get('candidate', {}).get('name', 'unknown')}")
    logger.info(f"Min score: {config.get('candidate', {}).get('min_score', 55)} | Top N: {config.get('candidate', {}).get('top_n', 5)}")
    provider = config.get("llm_provider") or "openrouter"
    model_by_provider = {
        "openrouter": config.get("openrouter_model", "default"),
        "anthropic": config.get("anthropic_model", "default"),
        "claude_cli": config.get("claude_cli_model") or "claude default",
        "ollama": config.get("ollama_model", "llama3.1"),
    }
    logger.info(f"LLM provider: {provider} | Model: {model_by_provider.get(provider, 'default')}")

    try:
        tf = TinyFish(api_key=config["tinyfish_api_key"])
        logger.debug("TinyFish client initialised")
    except Exception as e:
        logger.error(f"TinyFish init error: {e}")
        return

    resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
    resume = resume_path.read_text()
    logger.debug(f"Resume loaded: {resume_path} ({len(resume)} chars)")

    min_score = config.get("candidate", {}).get("min_score", 55)
    top_n = config.get("candidate", {}).get("top_n", 5)
    batch_size = _score_batch_size(config)

    state = load_state()
    seen_urls: set = set(state.get("seen_urls", []))
    logger.info(f"State loaded — {len(seen_urls)} previously seen URLs")

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    all_scored_jobs: list[dict] = []
    errors: list[str] = []
    companies_scanned = 0
    companies_with_jobs = 0

    def _checkpoint() -> None:
        """Flush seen URLs + results to disk so an interrupted scan keeps its work."""
        state["seen_urls"] = list(seen_urls)
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        _persist_scan(all_scored_jobs)

    for idx, company in enumerate(companies, 1):
        logger.info(f"[{idx}/{total}] Scanning {company['name']}...")
        try:
            new_jobs = discover_job_urls(tf, company, seen_urls, config.get("candidate", {}))
            if not new_jobs:
                logger.info("  No new job URLs found")
                companies_scanned += 1
                continue

            num_batches = (len(new_jobs) + batch_size - 1) // batch_size
            logger.info(
                f"  {len(new_jobs)} new job URL(s) — fetching + scoring in "
                f"{num_batches} batch(es) of {batch_size}..."
            )
            # Process each batch end-to-end — fetch, score, then checkpoint — and
            # only mark its URLs "seen" once its results are on disk. An interrupted
            # scan therefore re-does at most the current batch, not the whole
            # company, and never marks a job seen without saving it. Smaller batches
            # also give the LLM a shorter prompt to score, which weak/local models
            # parse far more reliably (see _score_batch_size).
            company_scored: list[dict] = []
            for i in range(0, len(new_jobs), batch_size):
                batch = new_jobs[i: i + batch_size]
                batch_num = i // batch_size + 1
                lbl = f"  [{company['name']}] Batch {batch_num}/{num_batches}"

                logger.info(f"{lbl}: fetching {len(batch)} job(s)...")
                got = _fetch_details_batch(tf, batch)
                if got < 0:
                    logger.warning(f"{lbl}: fetch returned no content — scoring URLs unenriched")

                logger.info(f"{lbl}: scoring {len(batch)} job(s)...")
                try:
                    batch_scored = score_jobs(batch, resume, config)
                except Exception as score_err:
                    logger.error(f"{lbl}: scoring failed ({score_err}) — saving unscored")
                    errors.append(f"⚠️ Scoring failed for {company['name']} batch {batch_num}: {score_err}")
                    batch_scored = batch

                if batch_scored:
                    for job in batch_scored:
                        job["scan_date"] = scan_date
                    all_scored_jobs.extend(batch_scored)
                    company_scored.extend(batch_scored)
                    logger.info(f"{lbl}: {len(batch_scored)} saved")

                # Mark seen + flush to disk only after this batch is fully handled.
                seen_urls.update(j["url"] for j in batch)
                _checkpoint()

            if company_scored:
                companies_with_jobs += 1
                titles = [j.get("extracted_title") or j.get("title", "?") for j in company_scored[:3]]
                logger.info(f"  {len(company_scored)} job(s) saved for {company['name']}: {', '.join(titles)}{' ...' if len(company_scored) > 3 else ''}")

            companies_scanned += 1

        except Exception as company_err:
            msg = f"❌ {company['name']}: {company_err}"
            errors.append(msg)
            logger.error(f"  Company scan failed: {company_err}")
            # Persist what we have before moving on, so one company's failure
            # doesn't cost us every result gathered so far.
            _checkpoint()
            continue

        # Per-batch _checkpoint() above already flushed this company's work; the
        # loop just needs to move on. A final _checkpoint() runs after the loop.
        logger.debug(
            f"  {company['name']} done — {len(all_scored_jobs)} jobs, {len(seen_urls)} seen URLs on disk"
        )

    logger.info("All companies scanned — finalising results")
    _checkpoint()
    logger.debug(f"Final save: {len(all_scored_jobs)} total jobs → {LAST_SCAN_FILE}")

    top_jobs = sorted(
        [j for j in all_scored_jobs if j.get("score", 0) >= min_score],
        key=lambda x: x.get("score", 0), reverse=True
    )[:top_n]

    elapsed = time.time() - scan_start
    logger.info(
        f"=== Scan complete — {companies_scanned}/{total} companies, "
        f"{len(all_scored_jobs)} jobs found, {len(top_jobs)} top matches "
        f"({elapsed / 60:.1f} min) ==="
    )

    if top_jobs:
        logger.info("Top matches:")
        for j in top_jobs:
            logger.info(f"  [{j.get('score', '?'):3}] {j.get('extracted_title') or j.get('title')} @ {j['company']} — {j.get('reason', '')[:80]}")

    date_str = datetime.now().strftime("%d %b %Y")
    tg = config.get("telegram", {})
    telegram_configured = _telegram_configured(tg)

    # Always persist results to CSV when there are scored jobs — this is the
    # durable record regardless of whether Telegram is configured.
    csv_path = _export_to_csv(all_scored_jobs, "scan results") if all_scored_jobs else None

    if errors and telegram_configured:
        error_msg = f"<b>Job Hunt Errors — {date_str}</b>\n" + "\n".join(errors)
        send_telegram(tg["token"], tg["chat_id"], error_msg)

    if not top_jobs:
        logger.info("No matching jobs found today.")
        if telegram_configured:
            msg = f"<b>Job Hunt — {date_str}</b>\nNo new matches today."
            send_telegram(tg["token"], tg["chat_id"], msg)
        return

    msg = format_telegram_message(top_jobs, date_str)
    logger.info("\n" + msg)

    # Telegram is an optional notification on top of the CSV. When it's not
    # configured we simply skip it — no error, the CSV already holds the results.
    if telegram_configured:
        sent = send_telegram(tg["token"], tg["chat_id"], msg)
        if sent:
            logger.info(f"Telegram notification sent. Results also saved to CSV: {csv_path}")
        else:
            logger.warning(f"Telegram send failed — results saved to CSV: {csv_path}")
    else:
        logger.info(f"Telegram not configured — results saved to CSV: {csv_path}")
        logger.info("Add telegram.token and telegram.chat_id to config.json to enable notifications.")
