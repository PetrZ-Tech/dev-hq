# HQ_02_TOOLS — tool routing

Use the most direct tool that can safely perform the task. Connected tools are optional; Dev HQ must degrade gracefully when a specific connector is unavailable.

## Routing rules
- Local files / terminal / processes -> authorized desktop or filesystem connector.
- Git hosting, issues and pull requests -> Git provider connector when available.
- Automation workflows -> automation-platform connector when available.
- Browser-only websites -> browser or computer-use tool.
- Library/framework documentation -> current documentation source.
- Public research -> current web/research source.
- Codebase context -> local code index plus current files; current files win on conflicts.
- GUI-only desktop actions -> desktop-control connector only when necessary.

Do not use a browser workaround when a direct connector already provides the needed operation.

## Model routing
Use the ChatGPT model/configuration appropriate to task complexity and the user's available plan. Do not hardcode a model that may not exist for another user. Do not claim that a model was switched unless the active configuration is actually known.

## Long operations
Before a potentially long or failure-prone tool call, register it in the lifecycle run with:
- tool and operation kind;
- expected duration;
- exact identity/reference if available;
- whether it can cause an external side effect;
- action key when idempotency matters.

A reachable tool, running process or heartbeat proves liveness only, not successful progress.
