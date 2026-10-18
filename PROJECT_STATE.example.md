# PROJECT_STATE — local template

Copy this file into a managed project as `PROJECT_STATE.md`.

Last verified: `[YYYY-MM-DD HH:MM TZ]`
Status: `TARGET | IN_PROGRESS | BLOCKED | VERIFIED | DONE`

## Verified current
- `[fact verified by a concrete check]`

## Changed this session
- `[change]`

## Checks
- `[command/check]` -> `PASS | WARN | FAIL`

## Open / not done
- `[remaining item]`

## Current lifecycle run
- Run ID: `[replace here]`
- Last verified checkpoint: `[replace here]`
- Unresolved operations: `[none or identifiers]`

## Next
- `[first safe next action]`

## Guardrails
- Keep secrets out of Git.
- Do not confuse planned state with verified runtime state.
- Do not repeat an unresolved external side effect without recovery.
