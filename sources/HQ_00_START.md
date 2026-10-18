# HQ_00_START — entry and freshness

## Purpose
Dev HQ is a stage-based development workflow for ChatGPT. Use the most direct available tool, verify results, and keep reusable rules separate from private machine/project state.

## Source map
- `HQ_01_EXECUTION.md` — architecture-first execution, lifecycle, operation control, recovery.
- `HQ_02_TOOLS.md` — tool and model routing.
- `HQ_03_QUALITY_SAFETY.md` — verification, permissions and quality gates.
- `HQ_04_PROJECTS.md` — project resolution and registry rules.
- `HQ_05_OPERATIONS.md` — local startup, state, ADR, handoff and backup routines.

Read only the source sections relevant to the current task.

## Freshness priority
When facts conflict, prefer:
1. live/runtime evidence;
2. current local files and checks;
3. current project state/context;
4. dated codebase memory/index;
5. Git/remote repository;
6. documentation;
7. old Sources/chat context.

Use explicit labels when useful: `VERIFIED LIVE`, `VERIFIED LOCAL`, `RECORDED`, `TARGET`, `STALE`.

## Entering a task
1. Resolve the project through the private local registry if one exists.
2. Read its current `PROJECT_STATE.md` or `PROJECT_CONTEXT.md`.
3. Inspect Git/files/runtime only as needed for freshness.
4. Reuse recorded context instead of asking the user to repeat it.
5. Do not claim a file/service is missing merely because one command failed.
6. Do not carry old project statuses forward without verification.
