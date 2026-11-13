## ADDED Requirements

### Requirement: Each role shows its pay as the listing gives it
Each saved role SHALL carry the pay (salary, day rate or hourly rate) exactly
as its listing words it, read from the listing text the scanner fetched. When
the listing gives no pay figure, the role SHALL show "Not given". A pay figure
SHALL NOT be estimated, converted or produced by a model.

#### Scenario: Salary range in the listing
- **WHEN** a role's listing says "Salary: £45,000 - £55,000 per annum"
- **THEN** the role's pay shows "£45,000 - £55,000 per annum"

#### Scenario: Day rate
- **WHEN** a role's listing says "Day rate: £500"
- **THEN** the role's pay shows "£500 a day"

#### Scenario: Salary at the end of a long listing
- **WHEN** the only pay line sits after the first 3,000 characters of the page
- **THEN** the role's pay still shows that figure

#### Scenario: No pay in the listing
- **WHEN** a role's listing says only "competitive salary"
- **THEN** the role's pay shows "Not given"

#### Scenario: Money that isn't pay
- **WHEN** a listing mentions "$40M in Series B funding" or "a £1,000 learning budget" and no salary
- **THEN** the role's pay shows "Not given"

#### Scenario: Role saved before pay was read
- **WHEN** a saved role has no stored pay but its stored listing text says "Salary £45,000 per annum"
- **THEN** the results show its pay as "£45,000 per annum" without a rescan

### Requirement: Pay appears wherever roles are listed
The web UI SHALL show a Pay column in both the All roles and By company views.
The CSV export SHALL include a Pay column after Role, and each Telegram match
SHALL include its pay.

#### Scenario: Company view
- **WHEN** the owner picks **By company**
- **THEN** every role under each company shows its pay or "Not given"

#### Scenario: Export
- **WHEN** the owner runs `autopilot export`
- **THEN** the CSV has a Pay column with each role's pay or "Not given"

#### Scenario: Repeat listing names the pay
- **WHEN** two listings of the same job fold into one row and only the second gives the pay
- **THEN** the folded row shows that pay
