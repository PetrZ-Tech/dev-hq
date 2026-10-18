# Session Handoff Protocol

Цель: после существенной рабочей сессии следующий чат должен продолжить проект без повторного расследования состояния.

## Когда handoff обязателен
Создавать/обновлять handoff, если за сессию произошло хотя бы одно:
- изменён код, workflow, схема БД, интеграция или инфраструктура;
- пройден важный тест/build/deploy/execution;
- изменился статус этапа;
- принято архитектурное решение;
- изменился следующий логичный шаг;
- обнаружено, что документация или память устарели.

Для одноразового вопроса без изменений handoff не нужен.

## Где хранить
Предпочтительный проектный файл: `PROJECT_STATE.md`.
Если проект уже использует `PROJECT_CONTEXT.md` как живой state-файл — обновлять его, не создавать дубликат без необходимости.
Если ни одного нет — создать `PROJECT_STATE.md` в корне проекта.

## Минимальный handoff
State-файл должен содержать:
- `Last verified`: дата/время и чем проверено;
- `Status`: текущий этап/состояние;
- `Verified current`: только подтверждённые факты;
- `Changed this session`: что изменено;
- `Checks`: тесты/build/execution IDs и результат;
- `Open / not done`: что ещё не реализовано;
- `Next`: один ближайший рабочий шаг;
- `Important guardrails`: ограничения проекта;
- ссылки на ключевые файлы/workflow IDs без секретов.

## Завершение существенной сессии
1. Проверить результат фактическим инструментом.
2. Обновить `PROJECT_STATE.md` / `PROJECT_CONTEXT.md`.
3. Если изменился общий статус проекта — обновить `PROJECTS_REGISTRY.md`.
4. Переиндексировать репозиторий проекта в Codebase Memory.
5. Если менялись правила самого штаба — переиндексировать `dev-hq`.
6. ChatGPT Sources обновлять только для существенных HQ-правил/реестров, а не после каждой рабочей сессии проекта.

## Начало следующей сессии
Для зарегистрированного проекта:
1. Разрешить проект через `PROJECTS_REGISTRY.md`.
2. Получить Codebase Memory проекта.
3. Прочитать project state/context file.
4. Если задача зависит от live-состояния — перепроверить live-систему по `STATE_FRESHNESS.md`.
5. Не заставлять пользователя повторно пересказывать уже записанный контекст.

## Важное
Handoff — не журнал всей переписки. Он должен быть короткой операционной точкой входа, пригодной для следующего чата.


## Lifecycle continuity and unresolved operations (2026-10-16)
Before leaving a substantial task, save project_id/run_id, the exact run-record path, the last verified stage, checkpoint/result references, unfinished operations and their action keys, diagnostic evidence, blockers and the first safe next step. A timestamp or process being alive is not a verified checkpoint. Distinguish TECHNICAL_COMPLETE, READY_TO_REPORT and actual user delivery; old DONE is not delivery proof.

At the start of the next session, read that exact run via task_lifecycle.py status and the current project state. Check available result files/execution status and the operation registry before creating a replacement run or retrying anything. Preserve unresolved side-effect action keys across sessions: the built-in duplicate guard is run-local and is not a cross-run guarantee. Resolve unknown outcomes through read-only evidence first. Reuse the existing run when resuming the same task, and continue from the first actually unfinished stage.

Apply STAGED_EXECUTION.md and OPERATION_CONTROL.md: approved work continues after relevant tests and a saved checkpoint; repeated confirmation of every normal substep is not required. Preserve real scope/risk/manual gates. If the laptop, tool or source is unavailable, record uncertainty instead of inventing completion. Watchdog can diagnose but does not autonomously resume a stopped ChatGPT turn.
