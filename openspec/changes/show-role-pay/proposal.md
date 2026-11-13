## Why

The owner wants to see each role's pay so he can judge roles at a glance and
guess which to go for. Today the scanner never records pay: it fetches each
posting's text, keeps the first 3,000 characters and asks the model for a
score, title, stack, location and reason. Pay often sits near the end of a long
posting, past what we keep.

## What Changes

- Each role gets a **pay** field: the salary, day rate or hourly rate exactly
  as the listing words it (`£45,000 - £55,000 per annum`, `$500/day`,
  `€60k–€70k`). When the listing gives no figure, the role shows **Not given**.
  A figure is never estimated, converted or guessed.
- Pay is read by pattern matching on the posting text the scanner already
  fetches, from the **whole page** before it is trimmed. No extra model call,
  so it adds nothing to the per-token bill.
- Roles saved before this change get their pay from their stored listing text
  when the results are shown, so the owner doesn't need to rescan.
- The Scan tab shows a **Pay** column in both **All roles** and **By company**.
- The CSV export (`autopilot export` and the scan's own CSV) gains a **Pay**
  column after Role, and each Telegram match gets a 💷 pay line.
- When repeat listings fold into one row, a listing that names the pay fills in
  a row that has none.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `job-results`: each saved role carries and shows its pay, or "Not given".

## Impact

- New `job_hunt/pay.py` (`extract_pay`, `pay_for`) and `tests/test_pay.py`.
- `job_hunt/scanner.py`: read pay at fetch time, keep it through scoring, add it
  to the CSV and Telegram message. `job_hunt/main.py`: Pay in `autopilot export`.
- `job_hunt/dedupe.py`: folding keeps a repeat listing's pay.
- `job_hunt/web/routes.py`: `GET /api/results` returns `pay` on every role.
- `frontend/src/components/Scan.jsx`, `frontend/src/util.js` (`payLabel`) and
  its Vitest test.
- No new dependency, no new config, no model prompt change.
- ADR [0005](../../../docs/adr/0005-read-pay-from-the-listing-text.md).
