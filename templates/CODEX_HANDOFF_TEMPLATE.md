# Codex Handoff — {{PROJECT_ID}}

Generated: `{{GENERATED_AT}}`
Target: `Codex / Work`
Recommended model: `{{MODEL}}`
Recommended reasoning: `{{EFFORT}}`

## Project
- ID: `{{PROJECT_ID}}`
- Path: `{{PROJECT_PATH}}`
- Branch: `{{BRANCH}}`
- Freshness: `{{FRESHNESS}}`
- Working tree: `{{GIT_STATE}}`

## Task
{{TASK}}

## Goal
{{GOAL}}

## Current context
{{CONTEXT}}

## Relevant files
{{FILES}}

## In scope
{{IN_SCOPE}}

## Out of scope
{{OUT_OF_SCOPE}}

## Constraints / guardrails
{{CONSTRAINTS}}

## Acceptance criteria
{{ACCEPTANCE}}

## Verification
{{VERIFICATION}}

## Execution rules
- Read the listed state/context and relevant files before editing.
- Preserve unrelated user changes.
- Do not read or expose secrets unnecessarily.
- Do not commit, push, deploy, publish, migrate, seed, activate production workflows or make system changes unless explicitly authorized in this handoff.
- Prefer the smallest correct change.

## Final response format
Return only:
1. `Changed` — what changed and where.
2. `Checks` — exact commands/tests and outcomes.
3. `Open` — anything not completed.
4. `Risks` — remaining technical or runtime risks.
