"""Read a role's pay (salary, day rate or hourly rate) from its listing text.

Pay is copied from the posting exactly as it is written there
("£45,000 - £55,000 per annum", "$500/day", "€60k–€70k"), never worked out,
converted or estimated. When the listing gives no figure we say so instead of
guessing. No model is called: this is plain pattern matching on text the
scanner has already fetched, so it costs nothing per role and can't invent a
number. See ADR 0005 (docs/adr/0005-read-pay-from-the-listing-text.md).

A money-looking figure only counts as pay when it reads like pay: a period
("per annum", "/day", "an hour"), a pay word just before it ("Salary:",
"Compensation", "OTE", "Day rate") or a range of yearly-sized amounts. Amounts
near words like "funding", "raised", "budget" or "stipend", and amounts in
millions, are skipped.
"""
from __future__ import annotations

import re

NOT_GIVEN = "Not given"

_CUR_SYM = r"(?:US\$|CA\$|C\$|A\$|AU\$|NZ\$|[£$€])"
_CUR_CODE = r"(?:GBP|USD|EUR|CAD|AUD|NZD|CHF)"
_NUM = r"\d{1,3}(?:[,.]\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d+)?"
_AMOUNT = (
    rf"(?:{_CUR_CODE}\s?)?{_CUR_SYM}?\s?(?:{_NUM})\s?(?:[kK]\b)?"
    rf"(?:\s?{_CUR_CODE}\b)?"
)
_RANGE_SEP = r"\s*(?:-|–|—|to|and)\s*"
_PERIOD = (
    r"(?:per\s+annum|p\.?\s?a\.?(?![a-z])|pa\b|a\s+year|per\s+year|/\s?(?:year|yr|annum)"
    r"|annually|yearly|annual"
    r"|per\s+day|a\s+day|/\s?day|daily|day\s+rate"
    r"|per\s+hour|an\s+hour|/\s?(?:hour|hr)|hourly"
    r"|per\s+month|a\s+month|/\s?(?:month|mo)\b|monthly)"
)
_PAY_WORDS = (
    r"(?:salary|pay|compensation|remuneration|base|OTE|on[- ]target|package"
    r"|day\s+rate|daily\s+rate|hourly\s+rate|rate|earn(?:ing)?s?|wage|range|up\s+to)"
)

# One figure or a range, then an optional period within a few characters.
_PAY_RE = re.compile(
    rf"(?P<amount>{_AMOUNT}(?:{_RANGE_SEP}{_AMOUNT})?)"
    rf"(?P<tail>[ \t,]*(?:\(\s*)?(?:{_PERIOD}))?",
    re.IGNORECASE,
)
_HAS_CURRENCY_RE = re.compile(rf"{_CUR_SYM}|{_CUR_CODE}", re.IGNORECASE)
_PAY_WORD_BEFORE_RE = re.compile(rf"{_PAY_WORDS}[^.\n]{{0,25}}$", re.IGNORECASE)
_NOT_PAY_RE = re.compile(
    r"funding|raised|raise|series\s+[a-f]\b|revenue|valuation|budget|stipend|allowance"
    r"|bonus|equity|arr\b|investment|investors|grant|donat|customers|users|turnover"
    r"|reimburs|relocation|learning|training|wellness|pension|401",
    re.IGNORECASE,
)
_PAY_HINT_AFTER_RE = re.compile(
    r"^\s*\(?\s*(?:pro[- ]rata|doe\b|depending\s+on\s+experience|gross|base|basic"
    r"|\+\s*benefits|plus\s+benefits|\+\s*bonus|plus\s+bonus|\+\s*equity|ote\b)",
    re.IGNORECASE,
)
_EXTRAS_AFTER_RE = re.compile(r"^\s*(?:\+|plus\b|and\b|&|,)")
_QUALIFIER_RE = re.compile(r"(up\s+to|from|starting\s+(?:at|from))\s*$", re.IGNORECASE)
_BIG_SUFFIX_RE = re.compile(r"^\s?(?:m\b|mn\b|bn\b|b\b|million|billion)", re.IGNORECASE)
_NUMBER_RE = re.compile(rf"(?P<n>{_NUM})\s?(?P<k>[kK]\b)?")

# Plausible ranges per period, in whole currency units.
_LIMITS = {
    "year": (5_000, 2_000_000),
    "month": (500, 200_000),
    "day": (40, 5_000),
    "hour": (5, 1_000),
}


def _clean(text: str) -> str:
    """Undo markdown escaping and emphasis so figures read as plain text."""
    text = text.replace("\\$", "$").replace("\\-", "-").replace(" ", " ")
    return re.sub(r"[*_`]+", "", text)


def _values(amount: str) -> list[float]:
    out = []
    for m in _NUMBER_RE.finditer(amount):
        raw = m.group("n")
        # "45,000" / "60.000" are thousands separators; "12.50" is a decimal.
        if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", raw):
            val = float(re.sub(r"[,.]", "", raw))
        elif re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+\.\d{1,2}", raw):
            val = float(raw.replace(",", ""))
        else:
            val = float(raw.replace(",", ""))
        if m.group("k"):
            val *= 1000
        out.append(val)
    # "£45-55k" gives the first figure in thousands too.
    if len(out) == 2 and re.search(r"[kK]\b", amount) and out[0] < 1000 <= out[1]:
        out[0] *= 1000
    return out


def _period(tail: str) -> str | None:
    t = (tail or "").lower()
    if not t.strip(" \t,("):
        return None
    if re.search(r"day|daily", t):
        return "day"
    if re.search(r"hour|hr", t):
        return "hour"
    if re.search(r"month|mo\b", t):
        return "month"
    return "year"


def _pay_word_period(before: str) -> str | None:
    b = before.lower()
    if re.search(r"day\s+rate|daily\s+rate", b):
        return "day"
    if "hourly" in b:
        return "hour"
    return None


def extract_pay(text: str | None) -> str | None:
    """The first pay figure in ``text``, as written in the listing, or None."""
    if not text:
        return None
    text = _clean(text)
    for m in _PAY_RE.finditer(text):
        amount = m.group("amount").strip()
        tail = m.group("tail") or ""
        after = re.split(r"[.!?;](?:\s|$)|\n", text[m.end():m.end() + 25])[0]
        if _BIG_SUFFIX_RE.match(text[m.end("amount"):m.end("amount") + 9]):
            continue
        # Only look back within the same sentence, so "We raised $40M." doesn't
        # disqualify the salary in the next sentence.
        before = re.split(r"[.!?;](?:\s|$)|\n", text[max(0, m.start() - 80):m.start()])[-1]
        # What follows "+" or "plus" is another perk ("£70k + equity"), not
        # what this figure is for.
        lead = _PAY_WORD_BEFORE_RE.search(before)
        context = (before[lead.start():] if lead else before[-40:]) + amount + ("" if _EXTRAS_AFTER_RE.match(after) else after)
        if _NOT_PAY_RE.search(context):
            continue
        values = _values(amount)
        if not values or any(v <= 0 for v in values):
            continue
        has_currency = bool(_HAS_CURRENCY_RE.search(amount))
        pay_word = bool(_PAY_WORD_BEFORE_RE.search(before) or _PAY_HINT_AFTER_RE.match(after))
        is_range = len(values) == 2
        period = _period(tail) or (_pay_word_period(before) if pay_word else None)

        if period is None:
            # No period: only a yearly-sized figure that is clearly pay.
            if not (has_currency or pay_word):
                continue
            if not (pay_word or is_range):
                continue
            period = "year"
        elif not (has_currency or pay_word):
            continue

        low, high = _LIMITS[period]
        if not all(low <= v <= high for v in values):
            continue
        if is_range and values[1] < values[0]:
            continue
        found = re.sub(r"\s+", " ", text[m.start():m.end()]).strip(" \t,(")
        if found.count("(") > found.count(")"):
            found = re.sub(r"\s*\(\s*", " ", found)
        if not tail and period in ("day", "hour"):
            found += " a day" if period == "day" else " an hour"
        qualifier = _QUALIFIER_RE.search(before)
        if qualifier:
            found = f"{qualifier.group(1).capitalize()} {found}"
        return found[:80]
    return None


def pay_for(job: dict) -> str:
    """The pay to show for a saved role: what the scan read, else what its
    stored listing text gives (for roles saved before pay was read), else
    "Not given"."""
    pay = job.get("pay")
    if isinstance(pay, str) and pay.strip():
        return pay.strip()
    for field in ("content", "snippet"):
        found = extract_pay(job.get(field))
        if found:
            return found
    return NOT_GIVEN
