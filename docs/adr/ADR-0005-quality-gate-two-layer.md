# ADR-0005 — Двухслойный Quality Gate

Status: `ACCEPTED`
Date: `2026-10-09`
Decision owners: `Dev HQ`

## Context
Успешный build/test не доказывает, что выполнена именно задача пользователя. С другой стороны, субъективная ручная оценка без механических проверок тоже недостаточна.

## Decision
Quality Gate состоит из двух слоёв: механический runner (`scripts/quality_gate.py`) проверяет Git hygiene, secrets и доступные test/typecheck/lint/build; штаб отдельно подтверждает критерии текущей задачи. Итоговый статус: `PASS`, `WARN` или `FAIL`.

## Why
Механика хорошо проверяет воспроизводимые технические факты, а соответствие конкретному запросу требует контекста задачи. Разделение уменьшает ложные `PASS`.

## Alternatives considered
- Только build/tests — не покрывает acceptance criteria.
- Только ручной review — плохо воспроизводится.
- Любой dirty tree = FAIL — создаёт шум во время нормальной разработки.

## Consequences
### Positive
- `PASS` означает больше, чем просто успешный build.
- `WARN` позволяет честно показать неполную проверку без ложного провала.

### Negative / trade-offs
- Для полного `PASS` нужен и технический прогон, и подтверждение критериев задачи.

## Verification / references
- `QUALITY_GATE.md`.
- `scripts/quality_gate.py`.
- Smoke tests: `hq-smoke-test` → PASS; HQ без automated checks → WARN; путь вне Projects → FAIL.

## Supersedes
- none

## Superseded by
- none
