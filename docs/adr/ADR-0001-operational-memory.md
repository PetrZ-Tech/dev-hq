# ADR-0001 — Каноническая операционная память штаба

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
Штаб должен продолжать работу между чатами без повторного онбординга. ChatGPT Project Sources удобны, но являются snapshot и не синхронизируются автоматически с локальным состоянием.

## Decision
Каноническая операционная память хранится в локальном репозитории `<PROJECTS_ROOT>\dev-hq` и индексируется Codebase Memory. ChatGPT Project Sources используются как bootstrap/snapshot для новых чатов.

## Why
Локальные файлы можно версионировать, проверять и обновлять инструментами; Codebase Memory даёт быстрый поиск по структуре и контексту; Sources удобны для старта, но не подходят как единственный источник истины.

## Alternatives considered
- Только ChatGPT Sources — отклонено из-за отсутствия auto-sync.
- Только память чата — отклонено из-за слабой воспроизводимости и контекстных ограничений.
- Только Git/GitHub — отклонено: история полезна, но не заменяет living state/handoff.

## Consequences
### Positive
- Новый чат может восстановить рабочий контекст без повторного объяснения.
- Есть проверяемая локальная база правил, state, dashboard и roadmap.

### Negative / trade-offs
- Sources нужно периодически синхронизировать вручную/скриптом.
- Codebase Memory надо переиндексировать после существенных изменений.

## Verification / references
- `PROJECT_STATE.md`, `STATE_FRESHNESS.md`, `SESSION_HANDOFF.md`, `PROJECTS_REGISTRY.md`.
- Codebase Memory project: `dev-hq`.

## Supersedes
- none

## Superseded by
- none
