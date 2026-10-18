# Tools Registry

Dev HQ does not require a fixed plugin stack. The repository provides routing rules and optional skill adapters; each user connects only the tools available in their ChatGPT account and local environment.

| Capability | Status | Typical use |
|---|---|---|
| HQ Watchdog | BUILT-IN | Local task/operation diagnostics and status UI |
| Local files / terminal | OPTIONAL | Project files, commands, processes, local diagnostics |
| Browser / computer use | OPTIONAL | Websites and GUI-only workflows |
| Browser developer tools | OPTIONAL | DOM, console, network and frontend diagnostics |
| Source-control connector | OPTIONAL | Remote repositories, issues, pull requests and CI |
| Codebase index / memory | OPTIONAL | Fast repository context; never replaces current files |
| Automation-platform connector | OPTIONAL | Workflow inspection/edit/run with exact execution identity |
| Documentation source | OPTIONAL | Current framework/SDK/API documentation |
| Public research source | OPTIONAL | Fresh web research |
| Email/calendar/storage connectors | OPTIONAL | Account-specific workflows when explicitly relevant |
| Design connector | OPTIONAL | Design files and implementation context |
| External coding executor | OPTIONAL | Delegated coding when a handoff is justified |

## Routing

- Prefer the most direct connector that can safely perform the requested operation.
- Do not use browser automation as a workaround when a direct connector already covers the action.
- Prefer current local files over an index when they disagree.
- For external writes, production actions, messages, payments or destructive changes, follow `SECURITY_BOUNDARIES.md` and explicit authorization rules.
- Before long/failure-prone operations, register the exact tool/call identity in the lifecycle run.

## Skills

`skills/*/SKILL.md` contains optional adapters for specific tools. A skill being present in this repository does **not** mean that the corresponding external tool is installed or connected.

## Local inventory

Users may keep their actual installed-tool inventory in a private ignored local file, for example `TOOLS_REGISTRY.local.md`.
