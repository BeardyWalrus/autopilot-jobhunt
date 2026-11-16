## ADDED Requirements

### Requirement: Health reports the build

`GET /api/health` SHALL include `revision`, the first 12 characters of the
commit the running image was built from, or `dev` when it wasn't built by the
publish workflow.

#### Scenario: Published image
- **WHEN** the image was built with `APP_REVISION=<sha>`
- **THEN** `revision` is the first 12 characters of `<sha>`

#### Scenario: Local build
- **WHEN** no revision was given at build time
- **THEN** `revision` is `dev`

### Requirement: Health reports whether the app is busy

`GET /api/health` SHALL include `busy`, true while a scan or a company job is
running and false otherwise, so a restart can wait for it.

#### Scenario: Scan running
- **WHEN** a scan is in progress
- **THEN** `busy` is true

#### Scenario: Idle
- **WHEN** no scan or company job is running
- **THEN** `busy` is false
