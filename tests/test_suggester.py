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
