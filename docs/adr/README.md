# Dev HQ — ADR Index

Architecture Decision Records фиксируют долгосрочные решения и причины их выбора.

| ADR | Status | Decision |
|---|---|---|
| [0010-pro](ADR-0010-project-local-verified-backups-without-automatic-deletion.md) | ACCEPTED | Project-local verified backups without automatic deletion |
| [0009-res](ADR-0009-resource-ledger-is-telemetry-not-billing.md) | ACCEPTED | Resource ledger is telemetry, not billing |
| [0007-sep](ADR-0007-separate-codex-handoff-preparation-from-execution.md) | ACCEPTED | Separate Codex handoff preparation from execution |
| [0006-adr](ADR-0006-adr-files-plus-codebase-memory-summary.md) | ACCEPTED | ADR files plus Codebase Memory summary |
| [ADR-0001](ADR-0001-operational-memory.md) | ACCEPTED | Локальный HQ + Codebase Memory — каноническая операционная память; Sources — snapshot |
| [ADR-0002](ADR-0002-security-boundaries.md) | ACCEPTED | Автономная запись только внутри `<PROJECTS_ROOT>`; системные/внешние изменения требуют подтверждения |
| [ADR-0003](ADR-0003-state-freshness-priority.md) | ACCEPTED | При конфликте live/runtime выше docs, memory и старых Sources |
| [ADR-0005](ADR-0005-quality-gate-two-layer.md) | ACCEPTED | Quality Gate сочетает механические проверки и отдельную проверку критериев задачи |

## Правила
- Новый номер = следующий свободный `ADR-XXXX`.
- `ACCEPTED` ADR не переписывать при смене курса; создавать новый и связывать через `SUPERSEDED`.
- Существенные ADR переиндексировать в Codebase Memory.

| [ADR-0011](ADR-0011-general-operation-control-and-stage-continuation.md) | ACCEPTED | General operation control and continuation of approved stages |
| [ADR-0012](ADR-0012-six-thematic-sources-over-canonical-local-rules.md) | ACCEPTED | Six thematic Sources over canonical local rules |
