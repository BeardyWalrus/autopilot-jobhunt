"""
Protocol-agnostic tool layer.

These functions contain zero MCP/OpenAI/Google dependencies.
The MCP server, future OpenAI tool adapter, and future Gemini function adapter
all import from here — one place to update, all adapters benefit.
"""
from pathlib import Path

from job_hunt.drafter import draft_application
from job_hunt.main import export_jobs, load_companies, load_config
from job_hunt.scanner import run_scan
from job_hunt.suggester import review_companies, suggest_companies


def tool_scan(config_path: str = "config.json", companies_path: str = "companies.json") -> str:
    """
    Discover new jobs, score them, send Telegram notification.
    Returns a summary string.
    """
    import json
    import os
    old_cwd = Path.cwd()
    project_root = Path(config_path).parent.resolve()
    os.chdir(project_root)
    try:
        config = load_config()
        companies = load_companies()
        run_scan(config, companies)
        last_scan = Path("state/last_scan.json")
        if last_scan.exists():
            jobs = json.loads(last_scan.read_text())
            scored = [j for j in jobs if j.get("score")]
            return f"Scan complete. {len(jobs)} jobs found, {len(scored)} scored."
        return "Scan complete. No results file written."
    finally:
        os.chdir(old_cwd)


def tool_draft(job_ref: str, config_path: str = "config.json") -> str:
    """
    Draft a tailored resume + cover letter for a job.
    job_ref: '#1', '1', or a full job URL.
    Returns path to output directory.
    """
    import os
    old_cwd = Path.cwd()
    project_root = Path(config_path).parent.resolve()
    os.chdir(project_root)
    try:
        config = load_config()
        draft_application(config, job_ref)
        return "Application drafted in output/ directory."
    finally:
        os.chdir(old_cwd)


def tool_suggest_companies(count: int = 8, config_path: str = "config.json") -> str:
    """
    Suggest companies to scan, based on the candidate's resume + profile.
    Returns a human-readable list (best-guess careers URLs — review before adding).
    """
    import os
    old_cwd = Path.cwd()
    project_root = Path(config_path).parent.resolve()
    os.chdir(project_root)
    try:
        config = load_config()
        resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
        if not resume_path.exists():
            return f"No resume found at {resume_path}. Add your resume first."
        resume = resume_path.read_text(encoding="utf-8")
        try:
            existing = load_companies()
        except SystemExit:
            existing = []
        suggestions = suggest_companies(config, resume, existing, count)
        if not suggestions:
            return "No suggestions returned. Try again or check your LLM settings."
        lines = [f"{len(suggestions)} suggested companies (best-guess URLs — review before adding):", ""]
        for s in suggestions:
            tag = " [already tracked]" if s.get("exists") else ""
            lines.append(f"- {s['name']} ({s['region']}, {s['location']}){tag}")
            lines.append(f"    {s['careers_url'] or s['search_domain']}")
            if s.get("reason"):
                lines.append(f"    {s['reason']}")
        return "\n".join(lines)
    finally:
        os.chdir(old_cwd)


def tool_review_companies(config_path: str = "config.json") -> str:
    """
    Review the tracked companies against the resume and flag poor-fit ones to
    remove or disable. Returns a human-readable list of flagged companies.
    """
    import os
    old_cwd = Path.cwd()
    project_root = Path(config_path).parent.resolve()
    os.chdir(project_root)
    try:
        config = load_config()
        resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
        if not resume_path.exists():
            return f"No resume found at {resume_path}. Add your resume first."
        resume = resume_path.read_text(encoding="utf-8")
        companies = load_companies()
        flagged = review_companies(config, resume, companies)
        if not flagged:
            return f"Reviewed {len(companies)} companies — none flagged as a poor fit."
        lines = [f"{len(flagged)} of {len(companies)} companies look like a poor fit:", ""]
        for f in flagged:
            lines.append(f"- {f['name']} — {f['reason']}")
        return "\n".join(lines)
    finally:
        os.chdir(old_cwd)


def tool_export(min_score: int = 0, days: int = 0, config_path: str = "config.json") -> str:
    """
    Export jobs to CSV.
    Returns path to exported CSV.
    """
    import os
    old_cwd = Path.cwd()
    project_root = Path(config_path).parent.resolve()
    os.chdir(project_root)
    try:
        export_jobs(min_score=min_score, days=days)
        return "Export complete. Check output/ directory."
    finally:
        os.chdir(old_cwd)
