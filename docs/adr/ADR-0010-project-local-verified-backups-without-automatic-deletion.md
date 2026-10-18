# ADR-0010 — Project-local verified backups without automatic deletion

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
HQ needs rollback checkpoints before broad or risky local changes, but Windows/system areas and secrets must remain protected.

## Decision
Store verified ZIP checkpoints only under <PROJECTS_ROOT>\_hq_backups; exclude secrets and common local data by default; verify manifest hashes after creation; do not use Task Scheduler or automatically delete/restore archives.

## Why
This gives a safe rollback point inside the autonomous workspace while respecting system boundaries and the rule that deletion/overwrite requires explicit approval.

## Alternatives considered
- Windows Task Scheduler
- Cloud backup outside Projects
- Git-only rollback

## Consequences
### Positive
- Verified rollback checkpoints
- No system changes
- No secret files by default
- Works with dirty trees

### Negative / trade-offs
- Backups exist only while the laptop/storage is available
- No unattended schedule when ChatGPT is not working
- Restore remains manual/confirmed

## Verification / references
- BACKUP_POLICY.md||scripts/backup_project.py||SECURITY_BOUNDARIES.md

## Supersedes
- none

## Superseded by
- none
