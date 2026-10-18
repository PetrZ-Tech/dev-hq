# ADR-0006 — ADR files plus Codebase Memory summary

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
Decision memory needs both human-readable canonical files and fast cross-session retrieval.

## Decision
Keep full canonical decisions in local docs/adr files and maintain a concise repository-level Codebase Memory ADR summary for retrieval.

## Why
Local ADR files are inspectable and durable; Codebase Memory makes the accepted rationale quickly discoverable in future chats.

## Alternatives considered
- Only Codebase Memory
- Only local ADR files

## Consequences
### Positive
- Human-readable canonical history
- Fast retrieval across chats

### Negative / trade-offs
- Requires reindex/summary refresh after important ADR changes

## Verification / references
- DECISION_MEMORY.md; docs/adr/README.md

## Supersedes
- none

## Superseded by
- none
