# Decision Memory

Use Architecture Decision Records (ADRs) to preserve the reasoning behind durable technical choices.

## When to create an ADR
Create one for decisions that are expensive to reverse or likely to matter later: architecture, storage, security boundaries, protocols, deployment, major dependencies, long-term workflow rules.

Do not create ADRs for routine implementation details, cosmetic edits or temporary debugging steps.

## Workflow
1. Resolve the project and read current state.
2. Check existing `docs/adr/` records for overlap.
3. Capture Context, Decision, Why, Alternatives, Consequences and Verification/references.
4. Use `scripts/create_adr.py` when appropriate.
5. Update the ADR index.
6. Reindex optional codebase memory if the project uses one.

An accepted historical ADR should not be silently rewritten to hide a changed decision. Create a new ADR and mark the old one superseded where appropriate.
