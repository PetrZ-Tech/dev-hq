# HQ_04_PROJECTS — project resolution

Dev HQ keeps real project inventory in the user's private local `PROJECTS_REGISTRY.md`. The public repository contains only `PROJECTS_REGISTRY.example.md`.

## Resolve a project
1. Read the private local registry if it exists.
2. Resolve the exact local project path under `DEV_HQ_PROJECTS_ROOT` (default `~/Projects`).
3. Read the project's current `PROJECT_STATE.md` or `PROJECT_CONTEXT.md` before substantial work.
4. Check Git state and the actual filesystem when freshness matters.
5. Use Codebase Memory or another index only as context; current files and live checks have higher priority.

## New projects
Before implementation, define:
- purpose and user outcome;
- architecture and boundaries;
- complete technical specification;
- development stages;
- acceptance criteria and tests;
- security/secrets approach;
- deployment target if relevant;
- decision points that require user approval.

Then bootstrap the local project, create `PROJECT_STATE.md`, initialize Git, and execute stage by stage.

## Registry hygiene
- Never place API keys, tokens, passwords, cookies or private keys in the registry.
- Keep machine-specific paths and private infrastructure only in the ignored local registry/environment files.
- Mark old data as stale rather than silently treating it as current.
- If the registry and live state disagree, verify live state and then update the private registry.
