# ADR-0009 — Resource ledger is telemetry, not billing

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
HQ needs cost and limit awareness without inventing unavailable token or allowance figures.

## Decision
Keep a local event ledger for known resource-heavy actions, while treating platform Usage/Allowance as the only source for exact billing or remaining limits.

## Why
Local tools can reliably record which resource/model/tool was used, but they cannot infer exact account allowance or monetary cost when the platform does not expose it.

## Alternatives considered
- Estimate tokens/cost from model names and task size
- Do not track resource usage at all

## Consequences
### Positive
- Prevents fabricated usage numbers
- Preserves useful cross-session resource telemetry
- Allows exact credits/tokens when a tool returns them

### Negative / trade-offs
- Local ledger is incomplete unless events are explicitly logged
- Exact account limits still require platform Usage access

## Verification / references
- RESOURCE_CONTROL.md||scripts/resource_tracker.py||MODEL_ROUTING.md

## Supersedes
- none

## Superseded by
- none
