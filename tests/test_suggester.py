"""Company suggester — LLM mocked, tolerant block parsing."""
from job_hunt import suggester

BLOCK = """Here are some companies:

NAME: Cohere
CAREERS_URL: https://cohere.com/careers
DOMAIN: cohere.com
LOCATION: Toronto, Canada
REGION: NA
REASON: NLP-focused, hires ML engineers
---
NAME: Hugging Face
CAREERS_URL: https://huggingface.co/careers
DOMAIN: huggingface.co
LOCATION: Remote
REGION: Global
REASON: open-source ML
"""


def test_parse_suggestions_block():
    recs = suggester._parse_suggestions(BLOCK)
    assert len(recs) == 2
    assert recs[0]["name"] == "Cohere" and recs[0]["search_domain"] == "cohere.com"
    assert recs[1]["location"] == "Remote" and recs[1]["region"] == "Global"


def test_parse_derives_domain_from_url():
    recs = suggester._parse_suggestions("NAME: Acme\nCAREERS_URL: https://acme.io/jobs\nREGION: EU")
    assert recs[0]["search_domain"] == "acme.io"


def test_parse_skips_nameless_blocks():
    recs = suggester._parse_suggestions("DOMAIN: x.com\nREGION: EU\n---\nNAME: Real\nDOMAIN: real.com")
    assert [r["name"] for r in recs] == ["Real"]


def test_suggest_companies_marks_existing(monkeypatch):
    monkeypatch.setattr(suggester, "chat_with_llm", lambda *a, **k: BLOCK)
    existing = [{"name": "Cohere", "search_domain": "cohere.com"}]
    out = suggester.suggest_companies({"candidate": {"name": "Ada"}}, "resume text", existing, 5)
    by_name = {s["name"]: s for s in out}
    assert by_name["Cohere"]["exists"] is True
    assert by_name["Hugging Face"]["exists"] is False


# --- review_companies ----------------------------------------------------------

REVIEW_OUT = """NAME: Acme Bank
REASON: finance, not ML
---
NAME: Robotics Co
REASON: hardware-focused
"""


def test_parse_review():
    recs = suggester._parse_review(REVIEW_OUT)
    assert [r["name"] for r in recs] == ["Acme Bank", "Robotics Co"]
    assert recs[0]["reason"] == "finance, not ML"


def test_review_companies_flags_by_name(monkeypatch):
    monkeypatch.setattr(suggester, "chat_with_llm", lambda *a, **k: "NAME: Acme Bank\nREASON: finance")
    companies = [
        {"name": "Acme Bank", "search_domain": "acmebank.com"},
        {"name": "OpenAI", "search_domain": "openai.com"},
    ]
    flagged = suggester.review_companies({"candidate": {"name": "Ada"}}, "resume", companies)
    assert len(flagged) == 1
    assert flagged[0]["name"] == "Acme Bank" and flagged[0]["index"] == 0


def test_review_companies_ignores_unmatched_names(monkeypatch):
    # Model names a company that isn't in the list — it must be dropped, not crash.
    monkeypatch.setattr(suggester, "chat_with_llm", lambda *a, **k: "NAME: Ghost Corp\nREASON: n/a")
    flagged = suggester.review_companies({"candidate": {}}, "r", [{"name": "OpenAI", "search_domain": "openai.com"}])
    assert flagged == []
