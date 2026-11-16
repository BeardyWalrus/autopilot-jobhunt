## 1. Ledger

- [x] 1.1 `job_hunt/usage.py`: `record`, `summary`, `prune`, counts only
- [x] 1.2 Tests: totals by feature, `since`, failed calls, bad lines, pruning, unwritable ledger

## 2. Recording calls

- [x] 2.1 `chat_with_llm` takes `feature`; the Agent SDK and CLI providers record each call, worked or not
- [x] 2.2 Scanner, drafter and suggester name their feature
- [x] 2.3 Tests: a worked and a failed SDK call each make one entry; other providers make none

## 3. Report

- [x] 3.1 `GET /api/usage?since=` in the art app's shape; 422 on a bad `since`
- [x] 3.2 Test for the route

## 4. Docs

- [x] 4.1 ADR 0006, ADR index, CHANGELOG
- [x] 4.2 Seen on the home dashboard's Claude card (16 Nov 2026: Job hunt line reads, 0 calls since the ledger began)
