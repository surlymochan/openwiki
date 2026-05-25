# Operating Handbook

## Architecture Decisions

Long-lived architecture decisions are recorded in `docs/architecture.md`.

## Release Gates

The release gates are documentation review, benchmark smoke run, and owner sign-off.

## Support Handoff

The on-call handoff happens every Monday at 10:00.

## Conflict Handling

When documents disagree, the team marks the conflict explicitly and escalates to the owning document maintainer.

## Freeze Timeline

Freeze starts every Thursday at 17:00. Production deploys happen on Friday after the smoke run passes.

## Freeze Change Policy

Allowed during freeze: correct factual mistakes, add missing owner names, and clarify existing procedures without changing behavior.

Not allowed during freeze: introduce a new top-level handbook area, rename ownership domains, or change release gates without owner approval.

## Handbook Versus Implementation Notes

If handbook content conflicts with implementation notes, the handbook wins first. The owning maintainer should reconcile the mismatch by updating both sources.

