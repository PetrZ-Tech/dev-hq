# ADR-0012 — Six thematic Sources over canonical local rules
Status: ACCEPTED
Date: 2026-10-16
Supersedes: none; complements ADR-0001 and ADR-0003

## Context
The ChatGPT HQ project held 25 uploaded snapshots with overlapping rules and different dates. Its uploaded registry and lifecycle copies lagged behind the canonical local repository. Upload capacity was full. Repeated snapshots made current instructions harder to identify.

## Decision
Use six thematic Sources plus one concise project instruction. Keep detailed canonical policies, code, project state, ADR and roadmap in the local repository. Treat uploaded Sources as versioned snapshots, with explicit release manifests and read-back verification.

## Why
One entry point and one place per theme reduce duplication while preserving access to detailed current contracts. Ordinary project state should not require reuploading Sources every session.

## Alternatives considered
Keep all 25 snapshots: rejected because of conflicting age and duplication.
Delete local canonical documents: rejected because scripts, history and detailed contracts depend on them.
Treat Sources as live synchronization: rejected; no automatic synchronization exists.

## Consequences
The release is stored in docs/source-release-2026-10-16. Future policy changes require regenerating the affected snapshot and verifying saved content. Exact old attachments and prior project instruction remain in docs/audits/2026-10-16-sources-before.zip for rollback.
Plus/Chat architecture, authorization boundaries and cooperative Watchdog limitations remain. This is a documentation/continuity decision, not an autonomous execution system.

## Verification / References
- docs/source-release-2026-10-16/ACTIVATION_PROOF.json
- Byte comparison of all six downloaded Sources and exact saved instruction.
- New ordinary Chat acceptance: architecture before implementation, real fixture state/receipt readback, routing and recovery scenario answers.

Superseded by: none
