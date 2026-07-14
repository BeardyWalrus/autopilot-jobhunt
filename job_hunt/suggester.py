"""Suggest companies to scan, based on the candidate's resume + profile.

An LLM reads the resume and proposes real companies that hire for the
candidate's roles/skills. Output is parsed tolerantly (same philosophy as the
scorer) so weak local models still return usable suggestions.

Note: the LLM's careers_url is a best guess and may be wrong — suggestions are
meant to be reviewed before being added to companies.json.
"""
import re

from job_hunt.llm_utils import chat_with_llm
from job_hunt.log import get_logger
from job_hunt.scanner import _build_candidate_profile

logger = get_logger()

SUGGEST_PROMPT = """You are a career researcher helping a candidate find companies to apply to.

CANDIDATE PROFILE:
{profile}

RESUME:
{resume}
{avoid_clause}
Suggest {count} REAL companies that frequently hire for this candidate's roles and
skills and would be a strong fit. Prefer companies actually known to hire in the
candidate's field and target regions.

For EACH company output one block in EXACTLY this format. Separate blocks with a
line containing only three dashes (---). Output nothing else.

NAME: company name
CAREERS_URL: best-guess careers page URL (https://...)
DOMAIN: primary domain, e.g. company.com
LOCATION: HQ city, country (or Remote)
REGION: one of EU, NA, APAC, LATAM, MEA, Global
REASON: one sentence on why it fits this candidate

Only suggest real companies."""

_ALIASES = {
    "name": "name", "company": "name",
    "careers_url": "careers_url", "careers": "careers_url", "url": "careers_url",
    "domain": "search_domain", "search_domain": "search_domain", "website": "search_domain",
    "location": "location", "hq": "location",
    "region": "region",
    "reason": "reason", "why": "reason",
}
_KV_RE = re.compile(r"^\s*([A-Za-z_ ]+?)\s*[:=]\s*(.*)$")


def _normalize(rec: dict) -> dict | None:
    name = (rec.get("name") or "").strip()
    if not name:
        return None
    domain = (rec.get("search_domain") or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain).strip("/")
    url = (rec.get("careers_url") or "").strip()
    if not domain and url:
        m = re.search(r"https?://([^/]+)", url)
        if m:
            domain = m.group(1).lower()
    return {
        "name": name,
        "careers_url": url,
        "search_domain": domain,
        "location": (rec.get("location") or "").strip() or "Unknown",
        "region": (rec.get("region") or "").strip() or "Global",
        "reason": (rec.get("reason") or "").strip(),
    }


def _parse_suggestions(raw: str) -> list[dict]:
    records: list[dict] = []
    cur: dict = {}

    def flush() -> None:
        if cur:
            norm = _normalize(cur)
            if norm:
                records.append(norm)
            cur.clear()

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if set(s) <= {"-", "="} and len(s) >= 3:
            flush()
            continue
        m = _KV_RE.match(s)
        if not m:
            continue
        key = _ALIASES.get(m.group(1).strip().lower())
        if key is None:
            continue
        if key == "name" and ("name" in cur):
            flush()
        cur[key] = m.group(2).strip()
    flush()
    return records


def suggest_companies(
    config: dict, resume: str, existing: list[dict] | None = None, count: int = 8, on_token=None
) -> list[dict]:
    """Return up to `count` suggested companies. Each dict has the companies.json
    fields plus `reason` and `exists` (already tracked, matched by domain)."""
    existing = existing or []
    avoid_clause = ""
    if existing:
        names = sorted({c.get("name", "") for c in existing if c.get("name")})
        if names:
            joined = ", ".join(names)[:2000]
            avoid_clause = f"\nThe candidate already tracks these — do NOT suggest them again:\n{joined}\n"

    prompt = SUGGEST_PROMPT.format(
        profile=_build_candidate_profile(config),
        resume=resume[:3000],
        count=count,
        avoid_clause=avoid_clause,
    )
    provider = config.get("llm_provider") or "openrouter"
    logger.info(f"Suggesting {count} companies from your resume via {provider}...")
    raw = chat_with_llm(config, messages=[{"role": "user", "content": prompt}],
                        temperature=0.4, on_token=on_token)
    suggestions = _parse_suggestions(raw)

    existing_domains = {c.get("search_domain", "").lower() for c in existing if c.get("search_domain")}
    existing_names = {c.get("name", "").lower() for c in existing if c.get("name")}
    for s in suggestions:
        s["exists"] = (
            (s["search_domain"] and s["search_domain"] in existing_domains)
            or s["name"].lower() in existing_names
        )
    logger.info(f"Parsed {len(suggestions)} company suggestions")
    return suggestions


REVIEW_PROMPT = """You are reviewing a candidate's list of companies they scan for jobs.
Identify companies that are a POOR FIT — unlikely to have roles matching this
candidate's profile and resume — that they should remove or disable.

CANDIDATE PROFILE:
{profile}

RESUME:
{resume}

COMPANIES:
{companies_text}

For EACH poor-fit company, output one block, separated by a line of three dashes (---):

NAME: exact company name from the list above
REASON: one sentence on why it's a poor fit for this candidate

List ONLY poor-fit companies. If a company is a plausible fit, leave it out.
Output nothing else."""


def _parse_review(raw: str) -> list[dict]:
    records: list[dict] = []
    cur: dict = {}

    def flush() -> None:
        name = (cur.get("name") or "").strip()
        if name:
            records.append({"name": name, "reason": (cur.get("reason") or "").strip()})
        cur.clear()

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if set(s) <= {"-", "="} and len(s) >= 3:
            flush()
            continue
        m = _KV_RE.match(s)
        if not m:
            continue
        key = _ALIASES.get(m.group(1).strip().lower())
        if key not in ("name", "reason"):
            continue
        if key == "name" and "name" in cur:
            flush()
        cur[key] = m.group(2).strip()
    flush()
    return records


def review_companies(
    config: dict, resume: str, companies: list[dict], batch_size: int = 50, on_token=None
) -> list[dict]:
    """Flag poor-fit companies to disable/remove.

    Returns a list of {index, name, search_domain, reason} — index is the
    position in `companies`, so the caller can disable or remove precisely.
    Reviews in batches so large lists stay within a small model's context.
    """
    profile = _build_candidate_profile(config)
    provider = config.get("llm_provider") or "openrouter"
    logger.info(f"Reviewing {len(companies)} companies against your resume via {provider}...")
    flagged: list[dict] = []
    for start in range(0, len(companies), batch_size):
        batch = companies[start:start + batch_size]
        companies_text = "\n".join(
            f"{i + 1}. {c.get('name', '?')} — {c.get('search_domain', '')} "
            f"— {c.get('location', '')} — {c.get('region', '')}"
            for i, c in enumerate(batch)
        )
        prompt = REVIEW_PROMPT.format(
            profile=profile, resume=resume[:2500], companies_text=companies_text
        )
        logger.info(f"Reviewing companies {start + 1}-{start + len(batch)} of {len(companies)}...")
        raw = chat_with_llm(config, messages=[{"role": "user", "content": prompt}],
                            temperature=0.2, on_token=on_token)
        by_name = {c.get("name", "").strip().lower(): j for j, c in enumerate(batch)}
        for rec in _parse_review(raw):
            j = by_name.get(rec["name"].strip().lower())
            if j is not None:
                c = batch[j]
                flagged.append({
                    "index": start + j,
                    "name": c.get("name", ""),
                    "search_domain": c.get("search_domain", ""),
                    "reason": rec["reason"],
                })
    logger.info(f"Flagged {len(flagged)} poor-fit companies")
    return flagged
