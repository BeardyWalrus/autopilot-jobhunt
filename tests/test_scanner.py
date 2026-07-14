"""Scanner pipeline — TinyFish + LLM mocked, filesystem in tmp_path."""
import json
import types

import pytest

from job_hunt import scanner


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(scanner.time, "sleep", lambda *_: None)


# --- pure helpers --------------------------------------------------------------

def test_is_job_url():
    assert scanner.is_job_url("https://x.co/jobs/ml-engineer-123")
    assert scanner.is_job_url("https://boards.greenhouse.io/acme/jobs/456789")
    assert not scanner.is_job_url("https://x.co/about")


def test_is_ats_listing():
    assert scanner.is_ats_listing("https://jobs.lever.co/acme")
    assert not scanner.is_ats_listing("https://x.co/careers")


def test_build_search_query_defaults():
    expected = (
        'site:x.co (senior OR staff OR principal OR lead) '
        '("data scientist" OR "ML engineer" OR "machine learning engineer" '
        'OR "AI engineer" OR MLOps OR "deep learning")'
    )
    assert scanner.build_search_query("x.co", {}) == expected


def test_build_search_query_empty_string_fields_fall_back_to_defaults():
    same_as_absent = scanner.build_search_query("x.co", {})
    out = scanner.build_search_query(
        "x.co", {"search_seniority": "", "search_keywords": ""}
    )
    assert out == same_as_absent


def test_build_search_query_custom_fields():
    out = scanner.build_search_query(
        "x.co",
        {
            "search_seniority": "junior OR entry",
            "search_keywords": '"full stack developer" OR "react developer"',
        },
    )
    assert out == 'site:x.co (junior OR entry) ("full stack developer" OR "react developer")'


def test_build_candidate_profile():
    cfg = {"candidate": {"name": "Ada", "profile": "ML eng", "seeking": "remote",
                         "not_suitable": "junior"}}
    out = scanner._build_candidate_profile(cfg)
    assert "- Ada" in out and "Seeking: remote" in out and "NOT suitable: junior" in out


def test_format_telegram_message():
    jobs = [{"company": "Acme", "title": "T", "extracted_title": "ML Eng", "location": "NY",
             "location_remote": "Remote", "stack": "Python", "reason": "fits", "url": "u"}]
    msg = scanner.format_telegram_message(jobs, "01 Jan 2026")
    assert "ML Eng" in msg and "Apply" in msg and "1 matches" in msg


# --- state ---------------------------------------------------------------------

def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scanner.load_state() == {"seen_urls": []}
    scanner.save_state({"seen_urls": ["a", "b"]})
    assert scanner.load_state()["seen_urls"] == ["a", "b"]


# --- score_jobs ----------------------------------------------------------------

def test_score_jobs_empty():
    assert scanner.score_jobs([], "resume", {}) == []


def test_score_jobs_parses_and_filters(monkeypatch):
    jobs = [{"company": "Acme", "location": "Remote", "title": "MLE", "url": "u1"},
            {"company": "Beta", "location": "NY", "title": "SWE", "url": "u2"}]
    raw = json.dumps([
        {"job_number": 1, "score": 90, "title": "ML Engineer", "worth_applying": True,
         "stack": "Python", "reason": "great"},
        {"job_number": 2, "score": 20, "title": "Frontend", "worth_applying": False},
    ])
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: "noise " + raw + " tail")
    out = scanner.score_jobs(jobs, "resume", {"candidate": {"min_score": 55}})
    assert len(out) == 1 and out[0]["score"] == 90 and out[0]["extracted_title"] == "ML Engineer"


def test_score_jobs_no_json(monkeypatch):
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: "sorry no json")
    assert scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}], "r", {}) == []


def test_score_jobs_llm_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(scanner, "chat_with_llm", boom)
    assert scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}], "r", {}) == []


# --- discover / fetch (fake TinyFish) -----------------------------------------

def _fake_tf(links=None, search_urls=None, contents=None):
    links = links or []
    search_urls = search_urls or []
    contents = contents or {}

    def get_contents(urls, **kwargs):
        results = []
        for u in urls:
            results.append(types.SimpleNamespace(
                url=u, links=links, text=contents.get(u, "JD text"), title="Fetched Title"))
        return types.SimpleNamespace(results=results, errors=[])

    def query(q, **kwargs):
        return types.SimpleNamespace(results=[types.SimpleNamespace(url=u) for u in search_urls])

    return types.SimpleNamespace(
        fetch=types.SimpleNamespace(get_contents=get_contents),
        search=types.SimpleNamespace(query=query),
    )


def test_discover_job_urls(monkeypatch):
    tf = _fake_tf(links=["https://x.co/jobs/ml-engineer-abcd"],
                  search_urls=["https://x.co/jobs/staff-ai-wxyz"])
    company = {"name": "Acme", "careers_url": "https://x.co/careers",
               "search_domain": "x.co", "location": "Remote", "region": "EU"}
    out = scanner.discover_job_urls(tf, company, set())
    urls = {j["url"] for j in out}
    assert "https://x.co/jobs/ml-engineer-abcd" in urls
    assert "https://x.co/jobs/staff-ai-wxyz" in urls
    assert all(j["company"] == "Acme" for j in out)


def test_fetch_job_details(monkeypatch):
    tf = _fake_tf(contents={"https://x.co/jobs/1": "Full job description here"})
    jobs = [{"url": "https://x.co/jobs/1", "title": "old"}]
    out = scanner.fetch_job_details(tf, jobs)
    assert out[0]["content"].startswith("Full job") and out[0]["title"] == "Fetched Title"


def test_fetch_job_details_reports_progress(monkeypatch, caplog):
    # 12 jobs → 2 batches; INFO progress lines should surface (not stay silent).
    tf = _fake_tf(contents={f"https://x.co/jobs/{i}": "JD" for i in range(12)})
    jobs = [{"url": f"https://x.co/jobs/{i}", "title": "t"} for i in range(12)]
    with caplog.at_level("INFO", logger="autopilot"):
        out = scanner.fetch_job_details(tf, jobs, label="Acme")
    assert len(out) == 12
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "[Acme]" in msgs and "batch 1/2" in msgs and "batch 2/2" in msgs


# --- incremental persistence ---------------------------------------------------

def test_persist_scan_writes_and_dedups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jobs = [{"url": "u1", "score": 90}, {"url": "u2", "score": 80}]
    added = scanner._persist_scan(jobs)
    assert added == 2
    assert len(json.loads(scanner.LAST_SCAN_FILE.read_text())) == 2
    assert len(json.loads(scanner.JOB_HISTORY_FILE.read_text())) == 2

    # Second checkpoint with one overlapping URL: last_scan is replaced wholesale,
    # history only gains the genuinely new row.
    added2 = scanner._persist_scan([{"url": "u2", "score": 80}, {"url": "u3", "score": 70}])
    assert added2 == 1
    assert len(json.loads(scanner.LAST_SCAN_FILE.read_text())) == 2
    assert {j["url"] for j in json.loads(scanner.JOB_HISTORY_FILE.read_text())} == {"u1", "u2", "u3"}


def test_persist_scan_tolerates_corrupt_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner.JOB_HISTORY_FILE.parent.mkdir(exist_ok=True)
    scanner.JOB_HISTORY_FILE.write_text("{not json")
    added = scanner._persist_scan([{"url": "u1", "score": 90}])
    assert added == 1
    assert json.loads(scanner.JOB_HISTORY_FILE.read_text())[0]["url"] == "u1"


def test_run_scan_persists_before_company_failure(scan_setup, monkeypatch):
    # First company succeeds, second raises mid-fetch. The checkpoint means the
    # first company's results are already on disk — a crash doesn't lose them.
    cfg, companies = scan_setup
    companies = companies + [{"name": "Boom", "careers_url": "c", "search_domain": "y.co",
                              "location": "NY", "region": "NA"}]

    def flaky_batch(tf, batch):
        if batch and batch[0].get("company") == "Boom":
            raise RuntimeError("network died")
        return len(batch)

    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen, cand=None: [
        {"url": f"https://x.co/{co['name']}", "title": "MLE", "company": co["name"],
         "location": co["location"], "region": co["region"]}])
    monkeypatch.setattr(scanner, "_fetch_details_batch", flaky_batch)
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)
    saved = json.loads(scanner.LAST_SCAN_FILE.read_text())
    assert any(j["company"] == "Acme" for j in saved)  # survived the later failure


def test_run_scan_checkpoints_each_batch(scan_setup, monkeypatch):
    # 15 jobs -> 2 batches (10 + 5). The 2nd batch's fetch dies. The 1st batch's
    # 10 URLs must already be marked seen (per-batch checkpoint), so a re-run
    # would not re-download them — recovery granularity is 10, not the company.
    cfg, companies = scan_setup
    jobs = [{"url": f"https://x.co/jobs/{n}", "title": "MLE", "company": "Acme",
             "location": "Remote", "region": "EU"} for n in range(15)]
    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen, cand=None: jobs)

    def batch_fetch(tf, batch):
        if any(j["url"].endswith("/14") for j in batch):  # a job only in batch 2
            raise RuntimeError("fetch died on batch 2")
        return len(batch)

    monkeypatch.setattr(scanner, "_fetch_details_batch", batch_fetch)
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)

    seen = set(json.loads(scanner.STATE_FILE.read_text())["seen_urls"])
    assert "https://x.co/jobs/0" in seen and "https://x.co/jobs/9" in seen  # batch 1 checkpointed
    assert "https://x.co/jobs/14" not in seen  # failed batch 2 not marked seen -> will retry


# --- export --------------------------------------------------------------------

def test_export_to_csv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    jobs = [{"company": "Acme", "extracted_title": "MLE", "url": "u", "score": 88,
             "worth_applying": True, "scan_date": "2026-01-01"}]
    path = scanner._export_to_csv(jobs, "test")
    text = path.read_text()
    assert "Acme" in text and "MLE" in text and "Yes" in text


# --- run_scan integration ------------------------------------------------------

@pytest.fixture
def scan_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "resume.md").write_text("Senior ML engineer, 10 YOE.")
    monkeypatch.setattr(scanner, "TinyFish", lambda **_: object())
    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen, cand=None: [
        {"url": "https://x.co/jobs/1", "title": "MLE", "company": co["name"],
         "location": co["location"], "region": co["region"]}])
    monkeypatch.setattr(scanner, "_fetch_details_batch", lambda tf, batch: len(batch))
    monkeypatch.setattr(scanner, "score_jobs", lambda jobs, resume, cfg: [
        {**jobs[0], "score": 90, "extracted_title": "MLE", "reason": "fit", "stack": "Py"}])
    cfg = {"tinyfish_api_key": "k", "candidate": {"name": "Ada", "resume_path": "resume.md",
                                                  "min_score": 55, "top_n": 5}}
    companies = [{"name": "Acme", "careers_url": "c", "search_domain": "x.co",
                  "location": "Remote", "region": "EU"}]
    return cfg, companies


def test_run_scan_no_telegram_writes_csv(scan_setup, monkeypatch):
    sent = []
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: sent.append(a))
    cfg, companies = scan_setup
    scanner.run_scan(cfg, companies)
    assert not sent  # no telegram configured
    assert json.loads(scanner.LAST_SCAN_FILE.read_text())[0]["score"] == 90
    from pathlib import Path
    assert list(Path("output").glob("jobs_*.csv"))


def test_run_scan_with_telegram(scan_setup, monkeypatch):
    sent = []
    monkeypatch.setattr(scanner, "send_telegram", lambda tok, chat, msg: sent.append(msg) or True)
    cfg, companies = scan_setup
    cfg["telegram"] = {"token": "t", "chat_id": "c"}
    scanner.run_scan(cfg, companies)
    assert sent and "matches" in sent[0]


def test_run_scan_scoring_failure_fallback(scan_setup, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("score boom")

    monkeypatch.setattr(scanner, "score_jobs", boom)
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    cfg, companies = scan_setup
    scanner.run_scan(cfg, companies)
    saved = json.loads(scanner.LAST_SCAN_FILE.read_text())
    assert saved  # unscored fallback saved
