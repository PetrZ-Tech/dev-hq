# Dev HQ — Project Bootstrap

Назначение: единый безопасный workflow создания нового локального проекта в `<PROJECTS_ROOT>`.

## Пользовательская команда
Основная команда: `Создай новый проект <название>`.
Алиасы: `Новый проект <название>`, `Заведи проект <название>`, `Bootstrap project <название>`.

## Минимальные входные данные
Обязательны:
- название проекта;
- краткая цель/назначение, если она не очевидна из текущего запроса.

Опционально:
- slug/ID;
- aliases;
- stack;
- Git branch (`main` по умолчанию).

Если название и цель понятны — не задавать лишних вопросов.

## Что создаётся локально
Локальный генератор `scripts/bootstrap_project.py` создаёт:
- папку проекта внутри `<PROJECTS_ROOT>`;
- `.gitignore`;
- `README.md`;
- `PROJECT_STATE.md`;
- `AGENTS.md`;
- `docs/VISION.md`;
- `docs/ARCHITECTURE.md`;
- `docs/adr/README.md`;
- `docs/adr/ADR_TEMPLATE.md`;
- локальный Git repository с указанной branch.

`.codebase-memory/`, `.env*`, build/cache/log артефакты по умолчанию исключаются из Git.

## Полный workflow штаба
1. Проверить `PROJECTS_REGISTRY.md`: нет ли уже такого ID/alias/path.
2. Сформировать slug и путь только внутри `<PROJECTS_ROOT>`.
3. Выполнить `bootstrap_project.py --dry-run` и проверить план.
4. Если команда пользователя явно просит создать проект и конфликтов нет — выполнить реальное создание без дополнительного подтверждения: это разрешённая рабочая зона.
5. Проверить созданные файлы и `git status`/branch.
6. Индексировать новый проект в Codebase Memory.
7. Добавить проект в `PROJECTS_REGISTRY.md` с фактическим path, branch и именем индекса.
8. Обновить `PROJECT_DASHBOARD.md`.
9. Обновить `PROJECT_STATE.md` самого HQ и при необходимости `CHANGELOG.md`.
10. Для существенного нового проекта заполнить/уточнить `docs/VISION.md` и `docs/ARCHITECTURE.md`: полная end-to-end архитектура, этапы, подэтапы, зависимости, риски, acceptance criteria, deployment/rollback и confirmation points по `STAGED_EXECUTION.md`.
11. До реализации согласовать с пользовательом архитектуру, полное ТЗ, этапы и критерии приёмки. После согласования выполнять план подэтапами с verify/checkpoint и продолжением без повторного подтверждения каждого обычного шага по STAGED_EXECUTION.md. До потенциально долгих действий регистрировать операции по OPERATION_CONTROL.md; реальные scope/risk/manual gates сохраняются.

## Decision Memory по умолчанию
Новый проект сразу получает ADR-контур, но без фиктивных решений. Первый ADR создаётся только когда появляется реальный долгосрочный trade-off: архитектура, security boundary, стек, storage/protocol, deployment, memory/state или другое решение, которое важно объяснить будущему чату.

## Что bootstrap НЕ делает автоматически
- не создаёт GitHub repository;
- не делает commit/push;
- не устанавливает зависимости;
- не создаёт production-инфраструктуру;
- не создаёт/не записывает секреты;
- не активирует n8n workflow;
- не меняет Windows/system settings.

Для remote repository, публикации, production и системных действий действуют обычные подтверждения `SECURITY_BOUNDARIES.md`.

## Freshness / state
Новый проект стартует как `BOOTSTRAPPED / NOT YET VERIFIED`.
Наличие файлов не считается доказательством рабочего приложения. После первого реального build/test/runtime-check обновить `PROJECT_STATE.md` фактическими VERIFIED результатами.

## CLI
Dry-run:
```powershell
python <PROJECTS_ROOT>\dev-hq\scripts\bootstrap_project.py --name "Voice AI Assistant" --purpose "Личный голосовой AI-помощник" --stack "Python + n8n + telephony" --dry-run
```

Создание:
```powershell
python <PROJECTS_ROOT>\dev-hq\scripts\bootstrap_project.py --name "Voice AI Assistant" --purpose "Личный голосовой AI-помощник" --stack "Python + n8n + telephony"
```

## Проверки
Успешный bootstrap обязан подтвердить:
- target path находится внутри `<PROJECTS_ROOT>`;
- target directory до создания отсутствовал;
- обязательные файлы созданы;
- ADR index/template созданы;
- Git repository и branch созданы;
- никаких секретов/remote/push не создано;
- после MCP-индексации имя Codebase Memory записано в registry.
