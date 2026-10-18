# ADR-0003 — Приоритет свежести состояния

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
README, старый handoff, Codebase Memory и live-система могут расходиться. Без строгого приоритета штаб рискует выдавать TARGET/старую документацию за текущее состояние.

## Decision
При конфликте использовать приоритет: live/runtime → локальные файлы + tests/build → PROJECT_STATE/PROJECT_CONTEXT → Codebase Memory → Git/GitHub → README/docs → ChatGPT Sources/старые чаты.

## Why
Чем ближе источник к фактически исполняемой системе и свежей проверке, тем выше его доказательная ценность. Документация описывает намерение и прошлое состояние, а не гарантирует текущее.

## Alternatives considered
- Считать README источником истины — отклонено: он может устареть.
- Считать Codebase Memory всегда самым свежим — отклонено: индекс требует переиндексации.
- Усреднять конфликтующие источники — отклонено: конфликт надо разрешать, а не смешивать.

## Consequences
### Positive
- Меньше ложных утверждений о готовности/production/live.
- Появляются явные маркеры `VERIFIED LIVE`, `VERIFIED LOCAL`, `RECORDED`, `TARGET`, `STALE`.

### Negative / trade-offs
- Live-dependent ответы иногда требуют дополнительной read-only проверки.

## Verification / references
- `STATE_FRESHNESS.md`.
- `PROJECT_DASHBOARD.md` следует тем же правилам.

## Supersedes
- none

## Superseded by
- none
