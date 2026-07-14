"""Resolve the project files the web app reads and writes.

Everything lives under one project directory — the same layout the CLI uses
(config.json, companies.json, resume/, state/, output/). It defaults to the
current working directory but can be pinned with AUTOPILOT_HOME, which is how
the Docker image points at a mounted volume.
"""
import os
from pathlib import Path


def project_dir() -> Path:
    return Path(os.getenv("AUTOPILOT_HOME", ".")).resolve()


def config_path() -> Path:
    return project_dir() / "config.json"


def companies_path() -> Path:
    return project_dir() / "companies.json"


def last_scan_path() -> Path:
    return project_dir() / "state" / "last_scan.json"


def job_history_path() -> Path:
    return project_dir() / "state" / "job_history.json"


def seen_jobs_path() -> Path:
    return project_dir() / "state" / "seen_jobs.json"


def default_resume_path() -> Path:
    return project_dir() / "resume" / "YOUR_RESUME.md"


def resume_path(config: dict) -> Path:
    """The resume file from config.candidate.resume_path, resolved under the
    project dir (relative paths are the norm, absolute paths pass through)."""
    rel = config.get("candidate", {}).get("resume_path") or "resume/YOUR_RESUME.md"
    p = Path(rel)
    return p if p.is_absolute() else (project_dir() / p)
