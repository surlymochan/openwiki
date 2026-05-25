# Architecture

## Decision Records

Long-lived architecture decisions should be documented in `docs/architecture.md`.

## Service Boundaries

- API service owns request validation.
- Search service owns indexing and retrieval.
- Worker service owns asynchronous jobs.

## Design Rule

When handbook content conflicts with implementation notes, the handbook wins until the owner updates both sources.
