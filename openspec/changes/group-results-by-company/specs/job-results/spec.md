## ADDED Requirements

### Requirement: Results can be viewed by company
The web UI SHALL offer two views of the saved results: all roles in one list
sorted by score, and grouped by company. In the company view each company SHALL
appear once, with its role count, its best score and its roles under it, best
score first. Company names that differ only in case, accents, spacing or punctuation
SHALL group together under the first spelling seen.

#### Scenario: Three roles at one company
- **WHEN** the results hold three roles at Acme and one at Globex
- **AND** the owner picks **By company**
- **THEN** Acme shows once with "3 roles" and its three roles under it
- **AND** Globex shows once with "1 role"

#### Scenario: Name spelled two ways
- **WHEN** one role's company is `Acme Inc.` and another's is `acme inc`
- **THEN** both roles show under one company, `Acme Inc.`

#### Scenario: Flat list kept
- **WHEN** the owner picks **All roles**
- **THEN** the results show as one list sorted by score, as before

### Requirement: Company view can be sorted and collapsed
The company view SHALL sort companies by name A–Z by default, or by best score
on request. Each company SHALL collapse and expand on its own, and the owner
SHALL be able to expand or collapse every company at once. The chosen view and
sort SHALL be remembered in the browser.

#### Scenario: Sort by best score
- **WHEN** Globex's best role scores 90 and Acme's best scores 75
- **AND** the owner sorts by best score
- **THEN** Globex is listed before Acme

#### Scenario: Collapse one company
- **WHEN** the owner collapses Acme
- **THEN** Acme's roles are hidden and its header still shows its role count
- **AND** other companies stay as they were

### Requirement: Per-role actions work in both views
Marking a role Applied or Not a fit, opening its link, its extra links and
deleting it SHALL work the same in both views, and **Hide handled** SHALL
filter both. A company whose roles are all hidden SHALL not be shown.

#### Scenario: Hide handled in company view
- **WHEN** both of Globex's roles are marked not a fit
- **AND** **Hide handled** is on
- **THEN** Globex is not shown in the company view
