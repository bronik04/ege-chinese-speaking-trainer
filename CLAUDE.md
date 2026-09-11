# CLAUDE.md

Руководство для Claude Code в этом репозитории. Обязательные правила находятся в [AGENTS.md](AGENTS.md),
эксплуатация — в [DEVELOPMENT.md](DEVELOPMENT.md), архитектура — в
[docs/architecture.md](docs/architecture.md), безопасность — в [SECURITY.md](SECURITY.md).

## Команды

```bash
make install
make run
make lint
make test-unit
make test-integration
make test
make test-e2e
make check
make docker-check
make docker-build
```

Playwright сам поднимает Uvicorn на порту 8091 с временным `TRAINER_DATA_DIR`; отдельный сервер не нужен.

Для контента и схемы БД:

```bash
.venv/bin/python -m scripts.validate_content
.venv/bin/alembic revision -m "describe schema change"
.venv/bin/alembic upgrade head
.venv/bin/python -m unittest tests.integration.test_migrations.SqliteMigrationTest -v
```

## Путь запроса

Единственная точка входа — `asgi.py` → `trainer.main:app`.

1. `main.py` применяет body limits, same-origin checks, request ID, logging и единый error contract.
2. `api/routes/*.py` валидирует Pydantic-payload и зависимости ролей.
3. Синхронная функция из `api/controllers/*.py` выполняется через `run_in_threadpool` и возвращает
   `ActionResult` или `FileResult`.
4. `api/routes.respond()` преобразует результат в FastAPI response, добавляя cookie и защитные заголовки.

Контроллеры не зависят от FastAPI/Starlette. Файлы и byte ranges формируются на уровне route, а storage-чтение
делегируется сервису.

## Слои и границы

Границы проверяет `tests/unit/test_architecture_boundaries.py`:

- `domain/` не импортирует API, web framework, environment или внешние adapters;
- `infrastructure/` не импортирует `trainer.api`;
- `api/dependencies.py` не выполняет SQL и не выбирает mailer/storage напрямую;
- контроллеры не выбирают storage backend;
- контроллеры не импортируют FastAPI или Starlette.

Для новой возможности сначала найдите существующие route, controller, domain/service, adapter и тест. Не
создавайте shim или пустой compatibility-модуль.

## База и приватные файлы

SQLite в WAL-режиме — единственный движок. Baseline 1–7 в
`src/trainer/infrastructure/database/sqlite_migrations.py` заморожен; дальнейшие изменения добавляются новыми
Alembic-ревизиями в `migrations/versions/`.

`runtime.REVIEW_ASSET_DIR` логически принадлежит review requests, но физически указывает на
`var/assignment-assets` для чтения существующих snapshot-файлов. Не переименовывайте каталог или поля
`assignment_keys_json` без отдельной миграции данных.

## Материалы и review requests

`services/materials.py` объединяет официальные варианты из `content/variants/` и авторские материалы из
SQLite. Гостю доступен только `open-2026`. `domain/materials.py:EXAM_SPEC` задаёт неизменяемые тайминги и
структуру заданий.

`services/review_assets.py` копирует изображения в приватный неизменяемый snapshot. Review request может
содержать одно задание или полную попытку; selection и scoring проверяются domain-функциями. Старые таблицы
назначений читаются только для совместимости данных и удаления аккаунта.

## Frontend и контент

Frontend не имеет сборки: ES-модули, страницы и стили раздаются напрямую. Точки входа —
`runner/app.js`, `catalog/variants-page.js`, `materials/material-editor.js` и
`reference/reference-page.js`. Любой пользовательский текст, вставляемый в HTML-строку, проходит через
`escapeHtml`.

`content/**/*.json` валидируется схемами из `schemas/`; изображения официальных вариантов находятся в
`public/assets/variants/<год>/candidate-XX.webp`.

## Конвенции

- Python 3.12+, Ruff line length 120, двойные кавычки; ESLint покрывает frontend и JS-тесты.
- Пользовательский интерфейс и активная документация — на русском языке.
- Ветки: `feature/`, `fix/`, `docs/`, `codex/`.
- Не коммитьте секреты, runtime-данные и generated reports.
- Не объявляйте задачу завершённой без свежего `make check`; после UI-изменений нужен `make test-e2e`.
