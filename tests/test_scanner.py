"""Scanner pipeline — TinyFish + LLM mocked, filesystem in tmp_path."""
import json
import types

import pytest

from job_hunt import scanner

# Captured before any fixture stubs it, so tests can restore the genuine scorer.
_REAL_SCORE_JOBS = scanner.score_jobs


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


def test_score_batch_size_default_and_clamp():
    assert scanner._score_batch_size({}) == 5                       # default
    assert scanner._score_batch_size({"score_batch_size": 3}) == 3  # top-level
    assert scanner._score_batch_size({"candidate": {"score_batch_size": 8}}) == 8
    assert scanner._score_batch_size({"score_batch_size": 0}) == 1  # clamped low
    assert scanner._score_batch_size({"score_batch_size": 99}) == 20  # clamped high
    assert scanner._score_batch_size({"score_batch_size": "oops"}) == 5  # non-int -> default


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


def test_score_jobs_no_json_raises(monkeypatch, caplog):
    # Unparseable output must raise (so the caller preserves the jobs unscored)
    # and log the raw output at ERROR level so it's debuggable from the scan log.
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: "sorry no json")
    with pytest.raises(scanner.ScoringError):
        scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}], "r", {})
    assert "sorry no json" in caplog.text


def test_score_jobs_empty_output_hints(monkeypatch, caplog):
    # A near-empty response gets a targeted "the model returned almost nothing" hint.
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: "  \n")
    with pytest.raises(scanner.ScoringError):
        scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}], "r", {})
    assert "returned almost nothing" in caplog.text


def test_score_jobs_llm_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(scanner, "chat_with_llm", boom)
    with pytest.raises(scanner.ScoringError):
        scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}], "r", {})


# --- tolerant output parsing ---------------------------------------------------

BLOCK_OUTPUT = """Sure! Here are the results:

JOB: 1
SCORE: 90
TITLE: ML Engineer
STACK: Python, PyTorch
LOCATION: Remote (EU)
WORTH: yes
REASON: strong LLM match
---
JOB: 2
SCORE: 20
TITLE: Frontend Dev
WORTH: no
REASON: not ML
"""


def test_parse_block_format():
    recs = scanner._parse_scored_output(BLOCK_OUTPUT)
    assert len(recs) == 2
    assert recs[0]["score"] == 90 and recs[0]["title"] == "ML Engineer"
    assert recs[0]["worth_applying"] is True and recs[1]["worth_applying"] is False
    assert recs[0]["location_remote"] == "Remote (EU)"


def test_parse_json_still_works():
    raw = json.dumps([{"job_number": 1, "score": 77, "title": "MLE", "worth_applying": True}])
    recs = scanner._parse_scored_output("prefix " + raw)
    assert len(recs) == 1 and recs[0]["score"] == 77 and recs[0]["worth_applying"] is True


def test_parse_tolerates_messy_values():
    # scores with units, '=' separators, alias keys, code fences
    raw = "```\nRole = Staff MLE\nrating: 82/100\nApply = yes\nwhy: fits\n```"
    recs = scanner._parse_scored_output(raw)
    assert len(recs) == 1
    assert recs[0]["score"] == 82 and recs[0]["title"] == "Staff MLE"
    assert recs[0]["worth_applying"] is True and recs[0]["reason"] == "fits"


def test_score_jobs_block_format(monkeypatch):
    jobs = [{"company": "Acme", "location": "Remote", "title": "MLE", "url": "u1"},
            {"company": "Beta", "location": "NY", "title": "SWE", "url": "u2"}]
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: BLOCK_OUTPUT)
    out = scanner.score_jobs(jobs, "resume", {"candidate": {"min_score": 55}})
    assert len(out) == 1 and out[0]["score"] == 90 and out[0]["extracted_title"] == "ML Engineer"
    assert out[0]["location_remote"] == "Remote (EU)"


def test_score_jobs_missing_worth_falls_back_to_threshold(monkeypatch):
    # No WORTH line at all; score 88 >= min_score 55 -> still surfaced.
    raw = "JOB: 1\nSCORE: 88\nTITLE: MLE\nREASON: fits"
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: raw)
    out = scanner.score_jobs([{"company": "A", "location": "L", "title": "T", "url": "u"}],
                             "r", {"candidate": {"min_score": 55}})
    assert len(out) == 1 and out[0]["score"] == 88


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


def test_merge_results_accumulates_and_preserves_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner._persist_scan([{"url": "u1", "score": 90}, {"url": "u2", "score": 80}])
    res = json.loads(scanner.RESULTS_FILE.read_text())
    assert {j["url"] for j in res} == {"u1", "u2"}
    assert all(j["status"] == "new" for j in res)  # default status

    # user marks u1 applied (as the web layer would)
    res[0]["status"] = "applied"
    scanner.RESULTS_FILE.write_text(json.dumps(res))

    # a later scan re-scores u1 and finds a new u3 — u2 must NOT be dropped, and
    # u1 keeps its "applied" status while its score is refreshed.
    scanner._persist_scan([{"url": "u1", "score": 95}, {"url": "u3", "score": 70}])
    res2 = {j["url"]: j for j in json.loads(scanner.RESULTS_FILE.read_text())}
    assert set(res2) == {"u1", "u2", "u3"}  # previous run's u2 preserved
    assert res2["u1"]["status"] == "applied" and res2["u1"]["score"] == 95
    assert res2["u3"]["status"] == "new"


def test_merge_results_seeds_from_last_scan_on_upgrade(tmp_path, monkeypatch):
    # An install with a last_scan.json but no results.json (pre-upgrade) must not
    # lose that run: the first new scan folds it into the results store.
    monkeypatch.chdir(tmp_path)
    scanner.LAST_SCAN_FILE.parent.mkdir(exist_ok=True)
    scanner.LAST_SCAN_FILE.write_text(json.dumps([{"url": "old", "score": 88}]))
    scanner._persist_scan([{"url": "fresh", "score": 90}])
    urls = {j["url"] for j in json.loads(scanner.RESULTS_FILE.read_text())}
    assert urls == {"old", "fresh"}


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
    # 15 jobs at the default batch size of 5 -> 3 batches. The last batch's fetch
    # dies; the first two batches' URLs must already be marked seen (per-batch
    # checkpoint), so a re-run would not re-download them.
    cfg, companies = scan_setup
    jobs = [{"url": f"https://x.co/jobs/{n}", "title": "MLE", "company": "Acme",
             "location": "Remote", "region": "EU"} for n in range(15)]
    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen, cand=None: jobs)

    def batch_fetch(tf, batch):
        if any(j["url"].endswith("/14") for j in batch):  # a job only in the last batch
            raise RuntimeError("fetch died on the last batch")
        return len(batch)

    monkeypatch.setattr(scanner, "_fetch_details_batch", batch_fetch)
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)

    seen = set(json.loads(scanner.STATE_FILE.read_text())["seen_urls"])
    assert "https://x.co/jobs/0" in seen and "https://x.co/jobs/9" in seen  # earlier batches checkpointed
    assert "https://x.co/jobs/14" not in seen  # failed last batch not marked seen -> will retry


def test_run_scan_honours_configured_batch_size(scan_setup, monkeypatch):
    cfg, companies = scan_setup
    cfg["score_batch_size"] = 3
    jobs = [{"url": f"https://x.co/jobs/{n}", "title": "MLE", "company": "Acme",
             "location": "Remote", "region": "EU"} for n in range(7)]
    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen, cand=None: jobs)
    monkeypatch.setattr(scanner, "_fetch_details_batch", lambda tf, batch: len(batch))
    sizes = []
    monkeypatch.setattr(scanner, "score_jobs", lambda batch, resume, c: sizes.append(len(batch)) or [])
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)
    assert sizes == [3, 3, 1]  # 7 jobs at batch size 3


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


def test_run_scan_skips_disabled_company(scan_setup, monkeypatch):
    cfg, companies = scan_setup
    companies = [
        companies[0],  # Acme, enabled (no flag)
        {"name": "Disabled Co", "careers_url": "c", "search_domain": "d.co",
         "location": "NY", "region": "NA", "enabled": False},
    ]
    scanned = []
    monkeypatch.setattr(scanner, "discover_job_urls",
                        lambda tf, co, seen, cand=None: (scanned.append(co["name"]), [])[1])
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)
    assert "Acme" in scanned and "Disabled Co" not in scanned


def test_run_scan_no_telegram_writes_csv(scan_setup, monkeypatch):
    sent = []
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: sent.append(a))
    cfg, companies = scan_setup
    scanner.run_scan(cfg, companies)
    assert not sent  # no telegram configured
    assert json.loads(scanner.LAST_SCAN_FILE.read_text())[0]["score"] == 90
    from pathlib import Path
    assert list(Path("output").glob("jobs_*.csv"))


def test_telegram_configured_helper():
    assert scanner._telegram_configured({"token": "t", "chat_id": "c"})
    # unset / partial
    assert not scanner._telegram_configured({})
    assert not scanner._telegram_configured({"token": "t"})
    assert not scanner._telegram_configured({"token": "t", "chat_id": ""})
    assert not scanner._telegram_configured({"token": "  ", "chat_id": "c"})
    # shipped placeholders must count as unconfigured
    assert not scanner._telegram_configured(
        {"token": "YOUR_TELEGRAM_BOT_TOKEN", "chat_id": "YOUR_TELEGRAM_CHAT_ID"}
    )
    assert not scanner._telegram_configured(
        {"token": "your_token_here", "chat_id": "12345"}
    )


def test_run_scan_placeholder_telegram_not_sent(scan_setup, monkeypatch):
    sent = []
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: sent.append(a) or True)
    cfg, companies = scan_setup
    cfg["telegram"] = {"token": "YOUR_TELEGRAM_BOT_TOKEN", "chat_id": "YOUR_TELEGRAM_CHAT_ID"}
    scanner.run_scan(cfg, companies)
    assert not sent  # placeholders → treated as unconfigured, nothing sent
    from pathlib import Path
    assert list(Path("output").glob("jobs_*.csv"))


def test_run_scan_with_telegram(scan_setup, monkeypatch):
    sent = []
    monkeypatch.setattr(scanner, "send_telegram", lambda tok, chat, msg: sent.append(msg) or True)
    cfg, companies = scan_setup
    cfg["telegram"] = {"token": "t", "chat_id": "c"}
    scanner.run_scan(cfg, companies)
    assert sent and "matches" in sent[0]


def test_run_scan_parse_failure_queues_for_rescore(scan_setup, monkeypatch):
    # A parse failure (real LLM output that can't be parsed) must NOT silently
    # drop the batch: the jobs go to the rescore queue to be retried, not into
    # results as unscored noise.
    cfg, companies = scan_setup
    # scan_setup stubs score_jobs; here we want the real one, fed unparseable output.
    monkeypatch.setattr(scanner, "score_jobs", _REAL_SCORE_JOBS)
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: "the model said no")
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    scanner.run_scan(cfg, companies)
    assert json.loads(scanner.LAST_SCAN_FILE.read_text()) == []  # nothing saved unscored
    queued = json.loads(scanner.RESCORE_FILE.read_text())
    assert queued and queued[0]["company"] == "Acme"  # queued to rescore instead


def test_run_scan_scoring_failure_queues_for_rescore(scan_setup, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("score boom")

    monkeypatch.setattr(scanner, "score_jobs", boom)
    monkeypatch.setattr(scanner, "send_telegram", lambda *a: True)
    cfg, companies = scan_setup
    scanner.run_scan(cfg, companies)
    assert json.loads(scanner.LAST_SCAN_FILE.read_text()) == []
    assert len(json.loads(scanner.RESCORE_FILE.read_text())) == 1  # queued


def test_rescore_queued_recovers_and_gives_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {"candidate": {"min_score": 55}}
    scanner._save_rescore_queue([
        {"url": "u1", "company": "Acme", "location": "L", "title": "MLE"},
        {"url": "u2", "company": "Beta", "location": "L", "title": "SWE", "_rescore_attempts": 2},
    ])
    # u1 scores fine; u2's batch keeps failing (already at 2 attempts -> gives up).
    def fake_score(batch, resume, config):
        if any(j["url"] == "u2" for j in batch):
            raise scanner.ScoringError("still broken")
        return [{**batch[0], "score": 88, "extracted_title": "MLE", "reason": "fit", "stack": "Py"}]
    monkeypatch.setattr(scanner, "score_jobs", fake_score)
    monkeypatch.setattr(scanner, "_score_batch_size", lambda c: 1)  # one job per batch

    summary = scanner.rescore_queued(cfg, "resume")
    assert summary == {"attempted": 2, "recovered": 1, "gave_up": 1, "remaining": 0}
    # u1 recovered into results with its score; u2 saved unscored; queue emptied.
    results = {j["url"]: j for j in json.loads(scanner.RESULTS_FILE.read_text())}
    assert results["u1"]["score"] == 88 and "_rescore_attempts" not in results["u1"]
    assert results["u2"] and "score" not in results["u2"]
    assert json.loads(scanner.RESCORE_FILE.read_text()) == []


def test_rescore_queued_requeues_below_attempt_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner._save_rescore_queue([{"url": "u1", "company": "A", "location": "L", "title": "T"}])
    monkeypatch.setattr(scanner, "score_jobs",
                        lambda *a, **k: (_ for _ in ()).throw(scanner.ScoringError("nope")))
    summary = scanner.rescore_queued({"candidate": {}}, "r")
    assert summary["remaining"] == 1 and summary["recovered"] == 0
    q = json.loads(scanner.RESCORE_FILE.read_text())
    assert q[0]["_rescore_attempts"] == 1  # requeued with an incremented attempt count


def test_enqueue_rescore_dedups_and_keeps_attempts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner._enqueue_rescore([{"url": "u1", "title": "a"}])
    scanner._save_rescore_queue([{**json.loads(scanner.RESCORE_FILE.read_text())[0], "_rescore_attempts": 2}])
    scanner._enqueue_rescore([{"url": "u1", "title": "a"}, {"url": "u2", "title": "b"}])
    q = {j["url"]: j for j in json.loads(scanner.RESCORE_FILE.read_text())}
    assert set(q) == {"u1", "u2"}
    assert q["u1"]["_rescore_attempts"] == 2  # existing entry (and its count) preserved
