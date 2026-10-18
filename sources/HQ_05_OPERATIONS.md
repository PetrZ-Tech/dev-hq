# HQ_05_OPERATIONS — local operation routines

## Start Dev HQ locally
Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-hq.ps1
```

The local watchdog UI is normally available at `http://127.0.0.1:32110/hq-status`. Optional external tool health checks are configured through environment variables; missing optional tools must not prevent core HQ use.

## Common intents
- Continue/status project -> resolve project -> current state -> fresh checks -> next action.
- What is stuck? -> inspect lifecycle run and registered operations; distinguish blocker from backlog.
- Check HQ -> perform safe health diagnostics.
- New project -> architecture/specification first, then bootstrap when agreed.
- Record/explain decision -> ADR workflow in `DECISION_MEMORY.md`.
- Prepare external coding handoff -> `CODEX_HANDOFF.md`; preparing a handoff does not execute it.
- Check before commit -> quality gate only; no commit/push unless explicitly requested.
- Backup project -> create/verify/list using `scripts/backup_project.py`; restore/delete are separate actions.

## Project bootstrap
On explicit request, validate project ID/path, dry-run `scripts/bootstrap_project.py`, create only a new project directory, read back the scaffold/Git state, then add the project to the user's private local registry.

Bootstrap creates project documentation and Git scaffolding. It does not prove that an application works and does not automatically create a remote repository, install dependencies, deploy infrastructure or add secrets.

## State and decisions
`PROJECT_STATE.md` answers "where are we now?". ADRs answer "why was this long-term decision made?". Git answers "what changed?". Runtime evidence answers "what is actually running?".

Use ADRs for durable architecture/security/storage/protocol/deployment trade-offs, not routine implementation details.

## Backup
`scripts/backup_project.py` stores verified local checkpoints under the configured projects root. It excludes Git metadata, caches, dependencies/build output, runtime/handoffs, secrets, credentials and local databases.

Backups do not replace source control or secret management. Restore/overwrite/prune operations require their own explicit scope.

## Reporting
After substantial work, report:
1. what changed;
2. how it was verified;
3. what remains open;
4. where the result is located;
5. the first safe next action.
