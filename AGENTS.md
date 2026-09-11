# Правила работы с проектом

Обязательные ориентиры для разработчиков и AI-агентов. Пользовательская инструкция находится в
[README.md](README.md), запуск и эксплуатация — в [DEVELOPMENT.md](DEVELOPMENT.md), устройство системы — в
[docs/architecture.md](docs/architecture.md).

## Текущая архитектура

- `src/trainer/main.py` содержит FastAPI-приложение; `asgi.py` — совместимая ASGI-точка входа.
- `src/trainer/api/routes/` принимает HTTP-запросы, `api/controllers/` выполняет сценарии, `api/schemas.py` и
  `api/errors.py` определяют контракты.
- `src/trainer/domain/` содержит чистые правила, `src/trainer/services/` — прикладные операции,
  `src/trainer/infrastructure/` — SQLite и внешние adapters.
- `frontend/` содержит страницы, стили и vanilla JavaScript; `content/` — JSON-материалы, `public/` — файлы,
  напрямую доступные браузеру.
- `scripts/` содержит backup, restore smoke, storage cleanup, import и проверки.
- `tests/`, `tests-js/`, `tests-e2e/` содержат Python-, JavaScript- и браузерные тесты.
- `migrations/` содержит Alembic-ревизии SQLite после замороженного baseline 1–7 в
  `src/trainer/infrastructure/database/sqlite_migrations.py`.

Целевая структура совпадает с текущими верхнеуровневыми границами:

```text
src/trainer/       API, domain, services, infrastructure
frontend/          HTML, CSS и браузерные JavaScript-модули
content/           версионируемые варианты и справочник
public/            публичные браузерные файлы
docs/              архитектура, ADR и runbooks
var/               локальная БД и пользовательские runtime-данные
backups/           локальные резервные копии
tmp/               воспроизводимые временные артефакты
```

Направление зависимостей: API оркестрирует domain/services; domain не зависит от HTTP и внешних adapters;
infrastructure не зависит от API. HTTP-статусы, cookies и сериализация принадлежат API; правила аккаунтов,
материалов, review requests и оценивания — domain; SQLite, S3/R2, SMTP и filesystem — infrastructure.

## Как вносить изменения

1. Найдите существующий маршрут, контроллер, сервис, adapter и тесты через `rg`.
2. Расширьте существующую ответственность; не создавайте параллельный сервис ради новой структуры.
3. Не меняйте публичное поведение без теста, который фиксирует требование или регрессию.
4. Для API обновляйте schema, route/controller и Python integration test.
5. Для бизнес-правила добавляйте unit test без зависимости от HTTP.
6. Для UI обновляйте JavaScript-тест; при изменении сценария — Playwright-тест.
7. Для схемы БД добавляйте новую Alembic-ревизию и проверяйте чистую, обновляемую и повторно обновляемую
   SQLite-базу. Не редактируйте baseline 1–7 и опубликованные revisions.
8. Для `content/**/*.json` запускайте `.venv/bin/python -m scripts.validate_content` и профильные тесты.
9. Обновляйте документацию и runbooks при изменении архитектуры, конфигурации или эксплуатации.

Старые таблицы групп, назначений и submissions сохраняются для совместимости данных. Новые возможности на них
не строятся; их удаление требует отдельного ADR и плана миграции данных.

## Данные и секреты

Коммитить разрешено исходный код, документацию, миграции, синтетические fixtures, `content/` и публичные
`public/assets/`.

Не коммитьте `.env`, ключи API, SMTP/S3 credentials, `var/`, `backups/`, пользовательские аудиозаписи, outbox,
`.coverage`, `.ruff_cache/`, `test-results/`, `playwright-report/`, `.venv/`, `node_modules/`, `__pycache__/` и
содержимое `tmp/`.

## Обязательная проверка

```bash
make check
```

При изменении UI дополнительно:

```bash
make test-e2e
```

При изменении Docker запускайте `make docker-check`, `make docker-build` и Compose health smoke. При изменении
S3/R2 или backup запускайте соответствующий smoke из [DEVELOPMENT.md](DEVELOPMENT.md). Не объявляйте задачу
завершённой без свежего успешного вывода обязательных проверок.
