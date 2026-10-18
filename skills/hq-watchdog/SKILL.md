---
name: hq-watchdog
description: Inspect Dev HQ task state, registered-operation deadlines and uncertain outcomes; use for waiting, stalls, interruption and read-only recovery diagnostics.
---

# HQ Watchdog

Read the current local `WATCHDOG.md` and `OPERATION_CONTROL.md` in `<PROJECTS_ROOT>\dev-hq` before diagnostics. Use `TASK_LIFECYCLE.md` for registration/result commands and `SESSION_HANDOFF.md` for resuming a saved run.

- Inspect `runtime/hq-status.json` or `http://127.0.0.1:32110/api/status`; use `/hq-status` for the monitor and POST `/api/recheck` for a read-only refresh.
- Keep tool availability, UI observation and current-task evidence separate. States include WORKING, WAITING, IDLE, STALLED, ERROR, OFFLINE, UNKNOWN, WAITING_RESULT and CHECK_REQUIRED.
- Register potentially long operations before calling tools. Monitor coverage is registered operations only; no transparent interception is guaranteed.
- Treat WAITING_RESULT as expected waiting, CHECK_REQUIRED as overdue needing diagnosis, and UNKNOWN as insufficient outcome evidence. A live PID or heartbeat is not meaningful progress or success.
- Record real progress, explicit waiting for input and result evidence through lifecycle commands. Observations must not fabricate progress. Correlate only the current project/run and PID creation identity.
- After interruption read the saved run/checkpoint and inspect unresolved operations before continuing. Resolve unknown side effects through read-only evidence before retry; preserve any existing result.
- Never auto-click Retry, restart ChatGPT/tools, or claim an unavailable recovery executor. Keep logs metadata-only, bounded and free of secrets/message content.
- Keep polling cheap: baseline 10 seconds, RAM target below 100 MB, average CPU below 1%, bounded 100-event log. An optional monitor failure must not stop other HQ tools.

Follow `STAGED_EXECUTION.md`: continue approved ordinary stages after verify/checkpoint; ask only for actual missing decisions or permissions. Keep technical completion, report preparation and real user delivery separate.
