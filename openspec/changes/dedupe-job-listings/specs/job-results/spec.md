## ADDED Requirements

### Requirement: Jobs are identified by job key
The system SHALL identify a job by its applicant-tracking system job ID when the
URL shows one (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday),
and otherwise by its URL with scheme, `www.`, fragment, tracking parameters,
trailing slash, `/apply` suffix and Workday locale removed.

#### Scenario: Tracking link to a seen job
- **WHEN** a scan finds `https://boards.greenhouse.io/acme/jobs/123?gh_src=li`
- **AND** `https://boards.greenhouse.io/acme/jobs/123` was seen before
- **THEN** the link is not fetched or scored

#### Scenario: Board link and embedded company page in one scan
- **WHEN** a scan finds the Greenhouse board link and `https://acme.com/jobs/x?gh_jid=123`
- **THEN** only one of them is fetched and scored

### Requirement: Repeat listings show once
The saved results SHALL hold one row per job. Rows sharing a job key, or the
same company, title and location ignoring case, accents and punctuation, SHALL
be folded into the first row, which lists every link in `sources` and keeps the
furthest-along status (applied, then not a fit, then new).

#### Scenario: Same title in two cities
- **WHEN** two results have the same company and title but locations London and New York
- **THEN** both are kept as separate rows

#### Scenario: Owner marked one copy
- **WHEN** one copy of a job is marked not a fit and another copy is new
- **THEN** the folded row is not a fit and lists both links

### Requirement: Existing duplicates are cleaned up reversibly
The first time saved results are folded, the system SHALL write the previous
list to `state/results.pre-dedupe.json`, and SHALL never overwrite that file.

#### Scenario: First scan after upgrade
- **WHEN** `results.json` holds three copies of one job and a scan saves results
- **THEN** `results.json` holds one row for it and the backup holds all three
