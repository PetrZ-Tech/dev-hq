# Dev HQ Watchdog

The Watchdog is an optional local diagnostic process. It reads Dev HQ lifecycle/runtime metadata and exposes a localhost status page. It does not retry external actions, continue a stopped ChatGPT turn, or modify remote systems.

## Start

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-hq.ps1
```

Default UI: `http://127.0.0.1:32110/hq-status`.

## Optional tool checks
By default only the Watchdog itself is required. Add optional localhost tool checks with:

```text
DEV_HQ_TOOL_PORTS=Tool A:32101,Tool B:32102
```

Enable Desktop Commander process monitoring only when relevant:

```text
DEV_HQ_WATCH_DESKTOP_COMMANDER=true
```

A desktop-control MCP endpoint may be configured with `DEV_HQ_DESKTOP_CONTROL_PORT` for optional UI observation.

## States
- `WORKING` — registered work is active.
- `WAITING` — explicit user/input dependency.
- `WAITING_RESULT` — registered operation has not produced a result yet.
- `CHECK_REQUIRED` — result/deadline needs read-only verification.
- `STALLED` — task activity is stale according to local evidence.
- `ERROR` — a confirmed error state.
- `OFFLINE` — a configured required local check is unavailable.
- `UNKNOWN` — evidence is insufficient.

Liveness is not progress. A reachable port, heartbeat or process does not prove that the task advanced.
