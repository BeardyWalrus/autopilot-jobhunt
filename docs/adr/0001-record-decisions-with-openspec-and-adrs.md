# 0001. Start every feature with an OpenSpec change and record lasting decisions as ADRs

- **Status:** Accepted
- **Date:** 2026-11-05
- **OpenSpec change:** none (this sets up the process itself)

## Context

Features here are planned and built with Claude across many sessions, and no
single session remembers why an earlier choice was made. An OpenSpec change
captures what a feature does, and its `design.md` holds the reasoning, but
that `design.md` is archived with the change once it ships, so the reasoning
behind a lasting choice is easy to lose.

## Decision

- Every new feature or change in behaviour starts with an OpenSpec change
  (`proposal.md`, `tasks.md`, spec deltas and a `design.md` that lists each
  decision with the options weighed), written and agreed before any code.
- Any decision in that `design.md` that will outlive the change also gets an
  ADR in `docs/adr/`, linked both ways.
- The rule lives in `CLAUDE.md`, so every Claude session follows it.

The same rule applies across MoodMark, local-docker and autopilot-jobhunt.

## Alternatives

- **OpenSpec only:** the reasoning in `design.md` gets archived with the
  change and is hard to find later.
- **ADRs only:** records why, but leaves no current description of what the
  app does.
- **No written process:** each session plans differently, and decisions get
  quietly undone.

## Consequences

- A little more writing before each feature, in exchange for a plan to agree
  on first and a record that survives the change.
- Bug fixes, refactors and doc changes that don't change behaviour skip the
  OpenSpec change.
- `docs/adr/README.md` has to be kept up to date as ADRs are added.
