## 1. Reading pay

- [x] 1.1 `job_hunt/pay.py`: `extract_pay` (pattern match, as written, never guessed) and `pay_for` (stored pay, else stored listing text, else "Not given")
- [x] 1.2 Tests for salaries, ranges, day and hourly rates, markdown escapes, and figures that aren't pay

## 2. Scanner and exports

- [x] 2.1 Read pay from the whole fetched page before trimming; keep it through scoring, falling back to the snippet
- [x] 2.2 Pay column in the scan CSV and `autopilot export`; 💷 line in Telegram
- [x] 2.3 Folding repeat listings keeps a repeat's pay when the kept row has none

## 3. Web UI

- [x] 3.1 `GET /api/results` returns `pay` on every role, filled from stored text for older rows
- [x] 3.2 Pay column in All roles and By company (`payLabel`, Vitest test)

## 4. Docs

- [x] 4.1 ADR 0005, ADR index, CHANGELOG
