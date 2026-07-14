"""Protocol-agnostic tool layer — underlying scan/draft/export/suggest mocked."""
from job_hunt import tools

CFG = {"candidate": {"resume_path": "resume/r.md"}}


def _resume(tmp_path):
    (tmp_path / "resume").mkdir(exist_ok=True)
    (tmp_path / "resume" / "r.md").write_text("Senior ML engineer")


def test_tool_scan_reports_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: {})
    monkeypatch.setattr(tools, "load_companies", lambda: [{"name": "A"}])
    monkeypatch.setattr(tools, "run_scan", lambda cfg, comps: None)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "last_scan.json").write_text('[{"score": 90}, {"score": 0}]')
    out = tools.tool_scan()
    assert "2 jobs found" in out and "1 scored" in out


def test_tool_scan_no_results_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: {})
    monkeypatch.setattr(tools, "load_companies", lambda: [])
    monkeypatch.setattr(tools, "run_scan", lambda cfg, comps: None)
    assert "No results file" in tools.tool_scan()


def test_tool_draft(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: {})
    seen = {}
    monkeypatch.setattr(tools, "draft_application", lambda cfg, ref: seen.setdefault("ref", ref))
    out = tools.tool_draft("#2")
    assert "output" in out and seen["ref"] == "#2"


def test_tool_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tools, "export_jobs", lambda min_score, days: None)
    assert "Export complete" in tools.tool_export(min_score=60, days=7)


def test_tool_suggest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _resume(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: CFG)
    monkeypatch.setattr(tools, "load_companies", lambda: [])
    monkeypatch.setattr(tools, "suggest_companies", lambda cfg, resume, existing, count: [
        {"name": "Cohere", "region": "NA", "location": "Toronto",
         "careers_url": "https://cohere.com", "search_domain": "cohere.com",
         "reason": "NLP", "exists": False}])
    out = tools.tool_suggest_companies(count=3)
    assert "Cohere" in out and "NLP" in out


def test_tool_suggest_no_resume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: CFG)
    assert "No resume" in tools.tool_suggest_companies()


def test_tool_review_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _resume(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: CFG)
    monkeypatch.setattr(tools, "load_companies", lambda: [{"name": "Acme Bank"}])
    monkeypatch.setattr(tools, "review_companies", lambda cfg, resume, comps: [
        {"name": "Acme Bank", "reason": "finance, not ML"}])
    out = tools.tool_review_companies()
    assert "Acme Bank" in out and "finance" in out


def test_tool_review_none_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _resume(tmp_path)
    monkeypatch.setattr(tools, "load_config", lambda: CFG)
    monkeypatch.setattr(tools, "load_companies", lambda: [{"name": "OpenAI"}])
    monkeypatch.setattr(tools, "review_companies", lambda cfg, resume, comps: [])
    assert "none flagged" in tools.tool_review_companies()
