## Context

`_fetch_details_batch` fetches each posting as markdown and keeps
`text[:3000]` as `content`; `score_jobs` sends 1,500 characters of that to the
model. Saved results (`state/results.json`) keep `content`, so roles already
saved still have some listing text. The owner pays per token for Claude, and
asked to see "the pay" for each role. The rule from the brief: never guess a
figure; show nothing or "not given" when the listing has none.

## Goals / Non-Goals

**Goals:** show each role's pay as the listing states it; say "Not given"
otherwise; no extra model cost; pay for roles already saved without a rescan.

**Non-Goals:** converting currencies or periods (day rate to yearly), sorting or
filtering by pay, estimating pay from market data, reading pay from job boards'
structured data (`schema.org` `baseSalary`) — a possible later addition.

## Decisions

### 1. Read pay by pattern, not by asking the model
See [ADR 0005](../../../docs/adr/0005-read-pay-from-the-listing-text.md).

- **Add a `PAY:` line to the scoring prompt:** a few tokens per role on every
  provider, but the model only sees 1,500 characters (often before the salary
  line), and models fill gaps with plausible figures, which is the one thing we
  must not do.
- **A separate model call per role:** more tokens on the owner's key for a job
  a pattern does well.
- **Pattern matching on the fetched text (chosen):** free, deterministic,
  testable, and it can only ever return text that is in the listing.

### 2. Read from the whole page at fetch time
- **From the stored 3,000 characters:** misses pay at the foot of long postings.
- **From the full fetched text before trimming (chosen):** one regex pass per
  page; the result is stored as `pay` so it survives the trim. Stored `content`
  is still used as a fallback for roles saved before this change.

### 3. Only count figures that read like pay
A money figure counts when it has a period (`per annum`, `/day`, `an hour`), a
pay word just before it in the same sentence (`Salary`, `Compensation`, `OTE`,
`Day rate`, `Up to`), a pay hint after it (`pro rata`, `DOE`, `+ benefits`),
or is a range. It must sit in a plausible band for its period (yearly
5,000–2,000,000; daily 40–5,000; hourly 5–1,000). Figures next to `funding`,
`raised`, `budget`, `stipend`, `allowance`, `bonus` and the like, and amounts
in millions, are skipped. Look-back stops at the sentence boundary, so "We
raised $40M." doesn't hide the salary in the next sentence. The first figure
that passes wins.

### 4. Keep the listing's own words
The shown text is the matched span with spacing tidied and markdown escapes
removed, plus a leading "Up to" / "From" when the listing has one and "a day" /
"an hour" when the period came from a word before the figure ("Day rate: £500"
shows as "£500 a day"). Nothing is converted.

### 5. "Not given" as one shared label
`job_hunt.pay.NOT_GIVEN` in the backend and `PAY_NOT_GIVEN` in the frontend.
The stored field is empty when no pay was found; the label is applied when
showing, exporting or sending, so it never ends up stored as if it were a figure.

## Risks / Trade-offs

- A pattern can miss unusual wording (`120'000 CHF`, figures with no currency
  and no pay word): those roles show "Not given", which is honest.
- A pattern can pick a figure that isn't the role's pay (a referral bonus
  worded without "bonus"). The exclusion list and per-period bands keep this
  rare; the column tooltip says it is the listing's figure.
