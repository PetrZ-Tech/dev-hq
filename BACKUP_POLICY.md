# Dev HQ — Automatic Backup

Назначение: безопасные checkpoint-backup локальных проектов внутри `<PROJECTS_ROOT>` без изменения Windows/system areas.

## Где хранятся backup
`<PROJECTS_ROOT>\_hq_backups\<project-id>\`

Каждый backup — ZIP с `manifest.json`. Manifest содержит project ID, source path, timestamp, режим, список файлов, размеры, SHA-256 и общий content fingerprint.

## Пользовательские команды
- `Сделай backup <проект>` — создать checkpoint проекта.
- `Проверь backup <проект>` — проверить последний backup и manifest/hash integrity.
- `Покажи backup <проект>` — показать последние архивы без изменений.

## Что сохраняется
По умолчанию сохраняются project source/config/docs/state/workflow-файлы, включая незакоммиченные изменения.

Автоматически исключаются:
- `.git`, `.codebase-memory`, `node_modules`, `.next`, `dist`, `build`, `coverage`, caches/venv;
- generated HQ `handoffs/`, `runtime/` и `_hq_backups`;
- `.env*`, private keys, certificates, credentials/secrets directories;
- common local DB/data files (`*.db`, `*.sqlite*`) без отдельного явного решения;
- очень большие файлы сверх default max-file-size.

`.env.example` разрешён: он считается шаблоном без секретов, но Quality Gate всё равно обязан ловить случайно попавшие реальные ключи.

## Безопасность
- Source и destination должны оставаться внутри `<PROJECTS_ROOT>`.
- Backup не читает/архивирует файлы вне выбранного проекта.
- Backup не делает commit/push/deploy/publish и не меняет project files.
- Никакого Task Scheduler/Windows service: это потребовало бы изменения системной зоны.
- Автоматическое удаление старых backup запрещено политикой штаба. Retention только сообщает, что архивов стало много; prune/delete требует отдельного подтверждения пользователя.
- Restore/overwrite также требует отдельного подтверждения и не выполняется обычной командой backup.

## Автоматический checkpoint
Перед существенной широкой/рискованной правкой штаб создаёт backup, если одновременно:
1. работа идёт в зарегистрированном локальном проекте;
2. изменение затрагивает много файлов, архитектуру, миграцию, production config или dirty tree без безопасной точки возврата;
3. свежего backup с тем же content fingerprint ещё нет.

Для маленькой обратимой правки backup не обязателен.

## Дедупликация
Перед записью вычисляется fingerprint выбранного набора файлов. Если последний валидный backup проекта имеет тот же fingerprint, результат: `SKIPPED_UNCHANGED`.

## Retention
Рекомендуемая граница: 10 checkpoint-архивов на проект. Скрипт только выдаёт `retention_warning`, но сам ничего не удаляет.

## CLI
Create/dry-run:
```powershell
python scripts\backup_project.py create --project <PROJECTS_ROOT>\dev-hq --project-id dev-hq --dry-run
```

Create:
```powershell
python scripts\backup_project.py create --project <PROJECTS_ROOT>\dev-hq --project-id dev-hq
```

List:
```powershell
python scripts\backup_project.py list --project-id dev-hq
```

Verify latest:
```powershell
python scripts\backup_project.py verify --project-id dev-hq
```

## Completion rule
Backup считается `VERIFIED` только если:
- ZIP создан;
- ZIP structure test проходит;
- `manifest.json` читается;
- hashes всех файлов совпадают;
- архив находится внутри `_hq_backups`.
