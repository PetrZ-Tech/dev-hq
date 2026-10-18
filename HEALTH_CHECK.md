# Dev HQ Health Check

Use this checklist when Dev HQ appears unavailable or stale.

## Read-only baseline
1. Confirm the repository directory exists.
2. Run `git status --short` if the directory is a Git repository.
3. Confirm Python is available.
4. Run `python -m pytest -q` when diagnosing the HQ code itself.
5. Check whether the watchdog is listening on the configured port.
6. Open `http://127.0.0.1:<port>/healthz` or `/hq-status`.
7. Check only the external connectors actually configured for this environment.

## Interpretation
- A missing optional connector is not an HQ failure.
- `UNKNOWN` means evidence is insufficient, not that work definitely failed.
- A timeout does not prove that an external side effect was not executed.
- Recover the same lifecycle operation before retrying an unknown side effect.

## Safe repair order
1. Read current state/run.
2. Inspect local process/port evidence.
3. Inspect exact external operation identity read-only if one exists.
4. Repair only the confirmed failed layer.
5. Re-run targeted tests/checks.
6. Update state with verified evidence.
