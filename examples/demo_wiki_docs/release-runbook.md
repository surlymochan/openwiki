# Release Runbook

## Release Gates

Before production deploy, complete all three gates:

1. Documentation review
2. Benchmark smoke run
3. Owner sign-off

## Rollback

If a production issue appears, pause rollout and use the previous stable build.

## Timeline

- Freeze starts every Thursday at 17:00.
- Production deploys happen on Friday after the smoke run passes.
