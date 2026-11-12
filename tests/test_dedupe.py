"""Duplicate job listings: canonical URLs, ATS job IDs, and folding repeats."""
import json
import types

import pytest

from job_hunt import dedupe, scanner

GH = "https://boards.greenhouse.io/acme/jobs/4012345"


# --- canonical_url / ats_job_id -------------------------------------------------

@pytest.mark.parametrize("variant", [
    "https://boards.greenhouse.io/acme/jobs/4012345/",
    "http://www.boards.greenhouse.io/acme/jobs/4012345?gh_src=abc&utm_source=li",
    "https://BOARDS.greenhouse.io/acme/jobs/4012345#apply",
])
def test_canonical_url_strips_noise(variant):
    assert dedupe.canonical_url(variant) == GH


def test_canonical_url_keeps_identifying_params_and_drops_apply():
    assert dedupe.canonical_url("https://acme.com/careers?gh_jid=77&utm_medium=x") == \
        "https://acme.com/careers?gh_jid=77"
    lever = "https://jobs.lever.co/acme/0f0e7c1a-1111-2222-3333-444455556666"
    assert dedupe.canonical_url(lever + "/apply?lever-source=LinkedIn") == lever


def test_canonical_url_workday_locale_and_non_urls():
    a = "https://acme.wd5.myworkdayjobs.com/en-US/External/job/London/Data-Scientist_R-0012345"
    b = "https://acme.wd5.myworkdayjobs.com/External/job/London/Data-Scientist_R-0012345/"
    assert dedupe.canonical_url(a) == dedupe.canonical_url(b)
    assert dedupe.canonical_url("  u1 ") == "u1"
    assert dedupe.canonical_url("www.acme.com/jobs/1/") == "https://acme.com/jobs/1"


def test_ats_job_id_for_each_board():
    assert dedupe.ats_job_id(GH) == "greenhouse:4012345"
    # A company site embedding Greenhouse is the same job as the board link.
    assert dedupe.ats_job_id("https://acme.com/careers/open?gh_jid=4012345") == "greenhouse:4012345"
    assert dedupe.ats_job_id(
        "https://jobs.lever.co/acme/0F0E7C1A-1111-2222-3333-444455556666/apply"
    ) == "lever:0f0e7c1a-1111-2222-3333-444455556666"
    assert dedupe.ats_job_id(
        "https://jobs.ashbyhq.com/acme/0f0e7c1a-1111-2222-3333-444455556666/application"
    ) == "ashby:0f0e7c1a-1111-2222-3333-444455556666"
    assert dedupe.ats_job_id("https://jobs.smartrecruiters.com/Acme/744000012345678-ml-eng") == \
        "smartrecruiters:744000012345678"
    assert dedupe.ats_job_id("https://apply.workable.com/acme/j/AB12CD34EF/") == "workable:ab12cd34ef"
    assert dedupe.ats_job_id(
        "https://acme.wd5.myworkdayjobs.com/en-GB/External/job/Leeds/ML-Engineer_JR-0099"
    ) == "workday:acme:jr-0099"
    assert dedupe.ats_job_id("https://acme.com/jobs/ml-engineer") is None


def test_job_key_falls_back_to_canonical_url():
    assert dedupe.job_key("https://acme.com/jobs/ml-eng/?utm_source=x") == "url:https://acme.com/jobs/ml-eng"
    assert dedupe.job_key(GH + "?gh_src=1") == dedupe.job_key("https://acme.com/c?gh_jid=4012345")


# --- match_key / collapse -----------------------------------------------------

def _job(url, title="Senior Data Scientist", loc="London", **kw):
    return {"url": url, "company": "Acme", "title": title, "location_remote": loc, **kw}


def test_same_title_different_location_stays_separate():
    out = dedupe.collapse_duplicates([
        _job("https://acme.com/jobs/1", loc="London"),
        _job("https://acme.com/jobs/2", loc="New York"),
    ])
    assert len(out) == 2


def test_reposts_and_tracking_links_fold_into_one_row_with_sources():
    out = dedupe.collapse_duplicates([
        _job(GH, score=80, status="new"),
        _job(GH + "?gh_src=x", score=82, status="not_applied"),
        _job("https://acme.com/jobs/other-id", title="Senior Data-Scientist ", score=78),
        _job("https://acme.com/jobs/3", title="Staff ML Engineer"),
    ])
    assert len(out) == 2
    first = out[0]
    assert first["url"] == GH and first["score"] == 80          # first row's fields kept
    assert first["status"] == "not_applied"                     # the user's decision wins
    assert first["sources"] == [GH, GH + "?gh_src=x", "https://acme.com/jobs/other-id"]


def test_collapse_refreshes_from_new_scan_but_keeps_url_and_status():
    old = [_job(GH, score=70, status="applied")]
    out = dedupe.collapse_duplicates(old, [_job(GH + "/", score=91, status="new", reason="better")])
    assert len(out) == 1
    assert out[0]["url"] == GH and out[0]["score"] == 91 and out[0]["status"] == "applied"
    assert out[0]["reason"] == "better"
    assert old[0]["score"] == 70  # inputs aren't changed


def test_collapse_bridges_two_existing_rows():
    a = _job("https://acme.com/jobs/a", title="ML Engineer", loc="Remote")
    b = {"url": GH, "company": "Acme", "title": "Different", "location_remote": "Paris"}
    bridge = _job(GH + "?utm_source=x", title="ML Engineer", loc="Remote")
    out = dedupe.collapse_duplicates([a, b], [bridge])
    assert len(out) == 1 and set(out[0]["sources"]) == {a["url"], GH, bridge["url"]}


def test_match_key_needs_company_and_title_and_skips_junk():
    assert dedupe.match_key({"url": "u"}) is None
    assert dedupe.collapse_duplicates([{"url": "u1"}, {"url": "u2"}, "junk"]) == [
        {"url": "u1"}, {"url": "u2"}]  # type: ignore[list-item]


def test_find_job_and_backup_once(tmp_path):
    jobs = dedupe.collapse_duplicates([_job(GH), _job(GH + "?gh_src=1")])
    assert dedupe.find_job(jobs, GH + "?gh_src=1") == 0
    assert dedupe.find_job(jobs, "https://boards.greenhouse.io/acme/jobs/4012345/") == 0
    assert dedupe.find_job(jobs, "https://nope.com/jobs/9") == -1

    path = tmp_path / "state" / "results.json"
    assert dedupe.backup_once(path, [1]) == tmp_path / "state" / "results.pre-dedupe.json"
    assert dedupe.backup_once(path, [2]) is None  # never overwritten
    assert json.loads((tmp_path / "state" / "results.pre-dedupe.json").read_text()) == [1]


# --- scanner wiring ---------------------------------------------------------------

def _fake_tf(links, search_urls):
    def get_contents(urls, **kwargs):
        return types.SimpleNamespace(results=[types.SimpleNamespace(url=urls[0], links=links, text="", title="")])

    def query(q, **kwargs):
        return types.SimpleNamespace(results=[types.SimpleNamespace(url=u) for u in search_urls])

    return types.SimpleNamespace(
        fetch=types.SimpleNamespace(get_contents=get_contents),
        search=types.SimpleNamespace(query=query),
    )


def test_discover_skips_seen_variants_and_collapses_links(monkeypatch):
    monkeypatch.setattr(scanner.time, "sleep", lambda s: None)
    tf = _fake_tf(
        links=[GH, GH + "?gh_src=careers", "https://x.co/jobs/new-role-abcd"],
        search_urls=["https://acme.com/jobs/open-role?gh_jid=4012345", "https://x.co/jobs/seen-one-1234/"],
    )
    company = {"name": "Acme", "careers_url": "https://x.co/careers",
               "search_domain": "x.co", "location": "Remote", "region": "EU"}
    out = scanner.discover_job_urls(tf, company, {"https://x.co/jobs/seen-one-1234?utm_source=li"})
    urls = sorted(j["url"] for j in out)
    # Three links to Greenhouse job 4012345 become one; the seen job's variant is skipped.
    assert len(urls) == 2
    assert "https://x.co/jobs/new-role-abcd" in urls
    assert sum(dedupe.job_key(u) == "greenhouse:4012345" for u in urls) == 1


def test_merge_results_folds_existing_duplicates_with_backup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner.RESULTS_FILE.parent.mkdir(exist_ok=True)
    before = [
        _job(GH, score=80, status="applied"),
        _job(GH + "?gh_src=x", score=80, status="new"),
        _job("https://acme.com/jobs/9", title="Data Engineer", status="new"),
    ]
    scanner.RESULTS_FILE.write_text(json.dumps(before))
    scanner._persist_scan([_job("https://acme.com/c?gh_jid=4012345", score=85)])
    res = json.loads(scanner.RESULTS_FILE.read_text())
    assert len(res) == 2
    assert res[0]["status"] == "applied" and res[0]["score"] == 85
    assert len(res[0]["sources"]) == 3
    backup = tmp_path / "state" / "results.pre-dedupe.json"
    assert json.loads(backup.read_text()) == before
    # Only one history row for the job, however many links it came under.
    scanner._persist_scan([_job(GH + "/", score=85)])
    hist = json.loads(scanner.JOB_HISTORY_FILE.read_text())
    assert len(hist) == 1


def test_enqueue_rescore_dedups_by_job_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scanner._enqueue_rescore([{"url": GH, "title": "a"}, {"url": GH + "?gh_src=1", "title": "a"}])
    assert len(json.loads(scanner.RESCORE_FILE.read_text())) == 1
