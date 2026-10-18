# Skill: Desktop Commander Remote

Use for local Windows files, folders, Excel, terminal commands and processes on the user's laptop.

## Prefer it when
- Need to read/write a local file.
- Need PowerShell/CLI on the laptop.
- Need to inspect running processes or project folders.
- Need direct structured Excel reads/edits.

## Avoid when
- The task is primarily inside a website and Browser Adapter/Chrome DevTools is better.
- GUI clicking is required; use Desktop Control Adapter when available.

## Safety
Read-only is fine. Confirm destructive or broad filesystem/system changes.

## Autonomous scope
- Autonomous write scope: `<PROJECTS_ROOT>\...`.
- Outside `Projects`, use read-only unless the user explicitly approves a change.
- System configuration changes always require confirmation even when technically permitted.
- Desktop Commander has server-side blocked commands for high-risk Windows/system operations.
