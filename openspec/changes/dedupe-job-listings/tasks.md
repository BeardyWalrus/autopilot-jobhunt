## 1. Job identity

- [x] 1.1 `job_hunt/dedupe.py`: `canonical_url`, `ats_job_id`, `job_key`, `match_key`
- [x] 1.2 `collapse_duplicates` folding by job key or match key, keeping `sources` and the furthest-along status
- [x] 1.3 `find_job` and one-time `backup_once`

## 2. Scanner

- [x] 2.1 Discovery skips seen job keys and keeps one link per job key
- [x] 2.2 `results.json` merge folds existing and new rows, backs up once
- [x] 2.3 History, rescore queue, last-scan, CSV and Telegram use job keys

## 3. Web

- [x] 3.1 `GET /api/results` returns folded rows; status and delete match any link and save the folded list
- [x] 3.2 Scan tab shows "+N more links"

## 4. Docs and tests

- [x] 4.1 Tests for URL variants, each ATS, folding, backup, discovery and the API
- [x] 4.2 ADR 0002, CHANGELOG, docs
