# ADR-0007 — Separate Codex handoff preparation from execution

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
Dev HQ must prepare tasks for Codex from an ordinary ChatGPT chat, but Codex Native2 actions require an active outer Codex turn_token and therefore are not universally launchable from every chat.

## Decision
Always allow HQ to generate and persist a complete Codex handoff package, but perform direct Native2 transfer only when a valid active Codex turn/token is actually present. Without it, report the integration as CONTEXTUAL and provide the ready handoff artifact instead of pretending Codex was launched.

## Why
This preserves a reliable workflow from any HQ chat, avoids false claims about execution, and still uses Native2 automatically when the runtime context genuinely supports it.

## Alternatives considered
- Require the user to manually compose prompts every time
- Pretend Native2 can launch Codex from any chat
- Use browser automation as the default Codex launcher

## Consequences
### Positive
- Reliable handoff generation from every HQ chat
- No false execution claims
- Native2 remains available when context permits

### Negative / trade-offs
- A prepared handoff may still require a separate Codex/Work turn when no token exists

## Verification / references
- CODEX_HANDOFF.md; MODEL_ROUTING.md; TOOLS_REGISTRY.md

## Supersedes
- none

## Superseded by
- none
