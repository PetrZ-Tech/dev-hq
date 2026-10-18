# Dev HQ — Full Task Lifecycle

Назначение: единый end-to-end протокол для команды «выполни задачу под ключ».

## Канонический цикл
1. `resolve` — однозначно определить project ID/path через registry.
2. `context` — поднять минимально достаточный контекст: Codebase Memory + state/context + relevant files.
3. `freshness` — проверить изменчивые факты по `STATE_FRESHNESS.md`; live/runtime выше docs.
4. `routing` — выбрать минимально достаточные tools + model/effort по `MODEL_ROUTING.md` и `RESOURCE_CONTROL.md`.
5. `checkpoint` — для широкой/рискованной правки сделать backup; для маленькой обратимой правки явно `SKIP` с причиной.
6. `execute` — выполнить задачу в разрешённой зоне; confirmation gates сохраняются.
7. `verify` — проверить фактический результат подходящим инструментом/read-back/test.
8. `quality_gate` — для code/config changes запустить `quality_gate.py` и отдельно подтвердить acceptance criteria.
9. `state_handoff` — обновить PROJECT_STATE/PROJECT_CONTEXT, если работа меняет точку продолжения; для одноразового/тривиального изменения допустим `SKIP` с причиной.
10. `adr` — создать ADR только для долговременного архитектурного решения, иначе `SKIP`.
11. `backup` — после существенного результата создать verified checkpoint; для малой обратимой правки допустим `SKIP`.
12. `memory` — переиндексировать Codebase Memory после существенных локальных изменений; для проекта без индекса сначала индексировать.
13. `report` — подготовить проверенный файл отчёта и отправить пользователю короткий итог: что сделано, чем проверено, Quality Gate, backup/state/memory и Next. Runner подтверждает подготовку файла, но не доставку сообщения.

## Поэтапное исполнение
Следовать STAGED_EXECUTION.md: для нового существенного проекта сначала согласовать полную архитектуру, ТЗ и этапы. Затем выполнять согласованный план ограниченными подэтапами: проверить результат, сохранить checkpoint/state и продолжить без обязательного повторного подтверждения каждого шага. Реальные scope/risk/manual gates сохраняются.

До потенциально долгого вызова любого инструмента зарегистрировать операцию по OPERATION_CONTROL.md. Независимый Watchdog проверяет её срок и доступные источники. Heartbeat/живой PID/updated_at не доказывают прогресс. UNKNOWN, FAILED, активные или повреждённые операции блокируют finish/prepare-report. После interruption/timeout сначала read-only recovery, без слепого повтора side effect.

Lifecycle run-record может продолжаться через этапы и чаты. При новом execute предыдущие verify/quality_gate сбрасываются: старые проверки не подтверждают новую работу. После каждой стадии фиксировать доказательства; terminal status выставлять только после всех обязательных стадий.

## Машинный run record
Канонический runner:
`python scripts/task_lifecycle.py ...`

Run-record хранится в:
`dev-hq/runtime/task-runs/<project-id>/<run-id>.json`

Он не хранит prompts, секреты или содержимое пользовательских данных. Только метаданные задачи, stages, acceptance criteria, tool/model routing и результаты проверок.

### Начало
```powershell
python scripts/task_lifecycle.py start --project <PROJECTS_ROOT>\hq-smoke-test --project-id hq-smoke-test --task "Add a tested helper" --complexity simple --model "current-default" --effort Low --risk LOW --acceptance "helper implemented" --acceptance "test passes"
```

### Отметить этап
```powershell
python scripts/task_lifecycle.py mark --run <run-id> --stage context --status PASS --note "CBM + files reviewed"
```
Statuses: `PASS | WARN | SKIP | FAIL`.

`resolve/context/freshness/routing/execute/verify/report` пропускать нельзя. Любой разрешённый `SKIP` требует непустой причины. `quality_gate=SKIP` разрешён только при явно указанном `--change-kind docs` или `--change-kind read-only` и с причиной; по умолчанию тип задачи `code`, для `code/config` Gate обязателен.

Для `verify=PASS/WARN` обязательны `--note` и `--evidence-ref` с ссылкой на фактическую проверку. `quality_gate=PASS/WARN/FAIL` записывается командой `gate` с проверками и согласованным exit code; вручную через `mark` его подтверждать нельзя. `mark --stage report` запрещён.

### Quality Gate
```powershell
python scripts/task_lifecycle.py gate --run <run-id> --criteria-ok yes
```
Runner вызывает HQ `quality_gate.py`, записывает итог и не скрывает WARN/FAIL.

### Backup
```powershell
python scripts/task_lifecycle.py backup --run <run-id>
```
Runner вызывает `backup_project.py create`; `CREATED_VERIFIED` и `SKIPPED_UNCHANGED` считаются успешным checkpoint.

### Статус / завершение
```powershell
python scripts/task_lifecycle.py status --run <run-id>
python scripts/task_lifecycle.py finish --run <run-id>
```
`finish` запрещён при `PENDING`, `FAIL` или недопустимых записях обязательных стадий. Он повторно валидирует сохранённые данные, включая старые или вручную отредактированные records. При успехе результат — `TECHNICAL_COMPLETE`; предупреждения остаются в `warnings`, `report` не становится автоматически PASS, `completed_at` остаётся null.

Затем штаб создаёт обычный UTF-8 файл отчёта внутри Projects и выполняет:
```powershell
python scripts/task_lifecycle.py prepare-report --run <run-id> --file <PROJECTS_ROOT>\<project>\docs\report.md
```
Файл должен существовать, быть непустым `.md/.txt` и не превышать 1 MB. Runner записывает путь, размер и SHA-256, выставляет `READY_TO_REPORT` и `reporting.preparation=PREPARED`. `report=PASS` здесь означает только подготовленный артефакт. `reporting.delivery=UNCONFIRMED` сохраняется: runner не наблюдает факт доставки ответа ChatGPT.

После этого штаб обязан отправить итог пользователю в текущем чате. Пользователю не требуется вручную отмечать стадии. Новый технический `mark/gate/backup` аннулирует подготовленность старого отчёта. Повторный `finish` сохраняет неизменённый подготовленный отчёт; если его файл изменился или пропал, требуется повторная подготовка.

Старые schema-v1 записи не мигрируют и не переписываются при `status`: прежний `DONE` остаётся исторической записью, а отсутствие сведений о доставке показывается как `LEGACY_UNVERIFIED / UNCONFIRMED`. Новые записи используют schema_version=2 и не создают бездоказательный `DONE`.

## Acceptance / доказательства
- Нельзя ставить `execute=PASS`, если изменение только запланировано.
- Нельзя ставить `verify=PASS` без фактической проверки.
- `quality_gate=PASS` берётся из механического runner, а не из ощущения модели.
- `backup=PASS` только после verified backup или подтверждённого dedup.
- `memory=PASS` только после успешного index/update.
- Наличие кода не заменяет runtime/test proof.

## Confirmation gates
Этот lifecycle не расширяет права штаба. По-прежнему требуют подтверждения: commit/push/deploy/publish, production/live writes, внешние сообщения/звонки/платежи, Windows/system/startup/security changes и любые необратимые/массовые действия.

## Codex / Work
Если задача выгоднее для Codex/Work, stage `routing` фиксирует это, затем используется `CODEX_HANDOFF.md`. После возврата HQ сам выполняет stages `verify → quality_gate → state_handoff → backup → memory → report`.

## Команда пользователя
`Выполни задачу под ключ <проект>: <задача>`

Штаб должен начать run-record автоматически и вести его до terminal status. Пользователю не нужно вручную управлять стадиями.

## Watchdog run identity (2026-10-16)
Lifecycle start/mark/finish/prepare-report записывают run_id и project_id в marker. Watchdog учитывает только updated_at записи этого run, а не активность других проектов или mtime. Новая задача не наследует старую window_binding; повторный сигнал того же run сохраняет её. Gate/backup сохраняют updated_at того же run, поэтому их фактическое завершение тоже видно монитору.
Вне lifecycle отдельный сигнал обязан соответствовать реальному прогрессу. Не создавай искусственный heartbeat без выполненной работы. UI UNKNOWN/DEGRADED означает недостаточную наблюдаемость, а не неисправность модели или гарантированный простой.
