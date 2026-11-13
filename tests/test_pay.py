"""Pay read from listing text: copied as written, never guessed."""
import csv
import json
import types

import pytest

from job_hunt import dedupe, main, scanner
from job_hunt.pay import NOT_GIVEN, extract_pay, pay_for


@pytest.mark.parametrize("text, expected", [
    ("Salary: £45,000 - £55,000 per annum plus benefits", "£45,000 - £55,000 per annum"),
    ("We raised $40M in Series B funding. The base salary range is $150,000—$180,000 USD.",
     "$150,000—$180,000 USD"),
    ("Day rate: £500", "£500 a day"),
    ("£450-£550 per day inside IR35", "£450-£550 per day"),
    ("Compensation: €60k–€70k", "€60k–€70k"),
    ("$85/hour", "$85/hour"),
    ("Hourly rate: $40", "$40 an hour"),
    ("Salary range: 45,000 - 55,000", "45,000 - 55,000"),
    ("**£45k - £55k** + benefits", "£45k - £55k"),
    ("\\$120,000 - \\$140,000 a year", "$120,000 - $140,000 a year"),
    ("The pay range is 120,000 - 150,000 USD per year", "120,000 - 150,000 USD per year"),
    ("£40-50k", "£40-50k"),
    ("Up to £65,000 DOE", "Up to £65,000"),
    ("Salary from £42,000", "From £42,000"),
    ("Pension 5% and £300 wellness allowance. Salary £38,000", "£38,000"),
    ("OTE £90,000", "£90,000"),
    ("$25 - $30 an hour", "$25 - $30 an hour"),
    ("Base pay £70k + equity", "£70k"),
    ("£55,000 (pro rata)", "£55,000"),
    ("Salary: £50,000 (per annum)", "£50,000 per annum"),
    ("£500 bonus and salary £30,000", "£30,000"),
])
def test_reads_pay_as_written(text, expected):
    assert extract_pay(text) == expected


@pytest.mark.parametrize("text", [
    "Competitive salary and a £1,000 learning budget",
    "Competitive salary plus a £5,000 relocation package",
    "Founded in 2015, 200 employees, 3 offices",
    "We have 10,000 customers and $2 million ARR",
    "We are backed by $50M from investors",
    "Join 2,500 colleagues across 12 countries",
    "In 2024 we grew 300%",
    "$1,000 home office stipend",
    "",
    None,
])
def test_no_figure_means_no_pay(text):
    assert extract_pay(text) is None


def test_pay_for_prefers_scanned_pay_then_listing_text():
    assert pay_for({"pay": "£60k"}) == "£60k"
    # Saved before pay was read: falls back to the stored listing text.
    assert pay_for({"pay": "", "content": "Salary: £48,000"}) == "£48,000"
    assert pay_for({"snippet": "£400 per day"}) == "£400 per day"
    assert pay_for({"content": "Competitive salary"}) == NOT_GIVEN
    assert pay_for({}) == NOT_GIVEN


def test_fetch_reads_pay_from_the_whole_page(monkeypatch):
    # Pay at the very end of a long page, past the 3,000 characters we keep.
    long_page = "About us. " * 400 + "Salary: £70,000 - £80,000 per annum"
    page = types.SimpleNamespace(url="u1", text=long_page, title="Data Engineer")
    monkeypatch.setattr(scanner, "_fetch_with_ratelimit",
                        lambda tf, urls, **kw: types.SimpleNamespace(results=[page]))
    job = {"url": "u1", "title": "x"}
    assert scanner._fetch_details_batch(object(), [job]) == 1
    assert job["pay"] == "£70,000 - £80,000 per annum"
    assert "£70,000" not in job["content"]


def test_scored_job_keeps_pay_and_falls_back_to_snippet(monkeypatch):
    raw = "JOB: 1\nSCORE: 90\nTITLE: T\nWORTH: yes\nREASON: r\n---\nJOB: 2\nSCORE: 90\nTITLE: U\nWORTH: yes\nREASON: r"
    monkeypatch.setattr(scanner, "chat_with_llm", lambda *a, **k: raw)
    jobs = [
        {"company": "A", "location": "L", "title": "T", "url": "u1", "pay": "£50k"},
        {"company": "B", "location": "L", "title": "U", "url": "u2", "snippet": "£300 per day"},
    ]
    out = {j["url"]: j["pay"] for j in scanner.score_jobs(jobs, "cv", {})}
    assert out == {"u1": "£50k", "u2": "£300 per day"}


def test_telegram_and_csv_show_pay(tmp_path, monkeypatch):
    base = {"title": "t", "location": "London"}
    jobs = [{**base, "company": "Acme", "extracted_title": "MLE", "url": "u", "score": 88,
             "pay": "£60,000 a year"},
            {**base, "company": "Globex", "extracted_title": "SRE", "url": "v", "score": 70}]
    msg = scanner.format_telegram_message(jobs, "01 Jan 2026")
    assert "💷 £60,000 a year" in msg and f"💷 {NOT_GIVEN}" in msg

    monkeypatch.chdir(tmp_path)
    rows = list(csv.DictReader(scanner._export_to_csv(jobs, "t").open(encoding="utf-8")))
    assert [r["Pay"] for r in rows] == ["£60,000 a year", NOT_GIVEN]
    assert main._job_to_row(jobs[0])["Pay"] == "£60,000 a year"
    assert main.EXPORT_FIELDS.index("Pay") == main.EXPORT_FIELDS.index("Role") + 1


def test_folding_keeps_pay_from_a_repeat_listing():
    rows = [{"company": "Acme", "title": "MLE", "location": "London", "url": "a"},
            {"company": "Acme", "title": "MLE", "location": "London", "url": "b", "pay": "£55k"}]
    (folded,) = dedupe.collapse_duplicates(rows)
    assert folded["pay"] == "£55k" and folded["url"] == "a"


def test_results_api_adds_pay(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from job_hunt.web.app import create_app

    monkeypatch.delenv("AUTOPILOT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "results.json").write_text(json.dumps([
        {"url": "u1", "score": 90, "pay": "£80k"},
        {"url": "u2", "score": 80, "content": "Salary £45,000 per annum"},
        {"url": "u3", "score": 70, "content": "Great team"},
    ]))
    monkeypatch.setattr("job_hunt.web.app.scheduler.start", lambda: None)
    monkeypatch.setattr("job_hunt.web.app.scheduler.stop", lambda: None)
    with TestClient(create_app()) as c:
        jobs = c.get("/api/results").json()["jobs"]
    assert [j["pay"] for j in jobs] == ["£80k", "£45,000 per annum", NOT_GIVEN]
