# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Документация проекта и интерфейс — на русском языке. Обязательные правила для агентов находятся в
[AGENTS.md](AGENTS.md), эксплуатация — в [DEVELOPMENT.md](DEVELOPMENT.md), архитектура —
в [docs/architecture.md](docs/architecture.md), security-чувствительные области — в [SECURITY.md](SECURITY.md).

## Команды

```bash
make install            # .venv, pip install -e ., npm ci
make run                # uvicorn asgi:app на http://127.0.0.1:8080
make lint               # ruff check + ruff format --check + eslint + check_json + check-yaml
make test-unit          # node --test tests-js/unit + unittest discover tests/unit
make test-integration   # unittest discover tests/integration
make test               # оба слоя под coverage (fail_under = 70)
make test-e2e           # playwright (нужен npx playwright install chromium)
make check              # pre-commit --all-files + make test — обязательный gate перед коммитом
make docker-check       # docker compose config для compose.yml и compose.scale.yml
make docker-build
```

Отдельные тесты:

```bash
.venv/bin/python -m unittest tests.unit.test_grading -v
.venv/bin/python -m unittest tests.integration.test_migrations.SqliteMigrationTest -v
node --test tests-js/unit/views.test.js
npx playwright test tests-e2e/reference.spec.js
```

Playwright сам поднимает uvicorn на порту 8091 с временным `TRAINER_DATA_DIR` и allowlist-переменными из
`playwright.config.js` — отдельный сервер запускать не нужно.

При изменении `content/**/*.json` или `public/assets/variants/`:

```bash
.venv/bin/python -m scripts.validate_content
```

При изменении схемы БД:

```bash
.venv/bin/alembic revision -m "describe schema change"
.venv/bin/alembic upgrade head
```

## Путь запроса

Единственная точка входа — `asgi.py` → `trainer.main:app`. Между FastAPI и бизнес-логикой стоит адаптер,
сохранивший форму `BaseHTTPRequestHandler`; это главная особенность кодовой базы:

1. `main.py` — middleware: лимит JSON-тела, `X-Request-ID`, структурированный лог, единый JSON-формат ошибок,
   catch-all выдача статики.
2. `api/routes/*.py` — тонкие обёртки: `return await invoke(request, "action_name", *args, payload=Schema)`.
3. [`api/http.py:invoke`](src/trainer/api/http.py) — читает тело с лимитом (`MAX_AUDIO_BODY` для
   `recording_create` и `material_asset_create`, иначе `MAX_BODY`), создаёт `ApiController` через
   `object.__new__`, подставляет `headers`/`rfile`/`wfile`/`send_response`/`send_header`, проверяет
   same-origin для POST/PUT/DELETE и выполняет действие в `run_in_threadpool`.
4. `api/controllers/*.py` — **синхронные** методы-действия, которые ничего не возвращают, а пишут ответ через
   `self.send_json(...)` / `self.send_error_json(...)` / `self.wfile.write(...)`.

`ApiController` ([api/controller.py](src/trainer/api/controller.py)) собирается из mixin-ов контроллеров плюс
`ApiDependenciesMixin` (сессии, `require_role`, audit) и `ApiTransportMixin` (чтение тела, cookie, заголовки).

Добавление эндпоинта:

1. Схема в `api/schemas.py` (базовый `ApiSchema` — `extra="forbid"`, `populate_by_name=True`).
2. Маршрут в `api/routes/<область>.py`, вызывающий `invoke` с именем действия.
3. Метод-действие в соответствующем mixin из `api/controllers/`.
4. Integration-тест в `tests/integration/`.

Внутри действия: `self.read_json()` возвращает уже провалидированный Pydantic-payload, если схема передана в
`invoke`, иначе разбирает `rfile`. `self.require_role("student"|"teacher")` при отказе сам отправляет ошибку и
возвращает `None` — вызывающий код должен немедленно сделать `return`. Блокирующий IO пишется обычным
синхронным кодом, `await` внутри контроллеров не используется.

## Слои и границы

`API → domain → infrastructure interfaces`. Границы не декоративные — их проверяет
[tests/unit/test_architecture_boundaries.py](tests/unit/test_architecture_boundaries.py):

- `domain/` не импортирует `trainer.api`, `fastapi`, `boto3`, `openai`, `smtplib` и **`os`** — значения
  окружения передаются аргументами (например `authorize_role(..., teacher_emails=...)`);
- `infrastructure/` не импортирует `trainer.api`;
- `api/dependencies.py` не выполняет SQL напрямую и не импортирует mailer/storage — только `services/`;
- `api/controllers/{auth,recordings,work}.py` не вызывают `storage_from_env`.

Дополнительно [test_package_layout.py](tests/unit/test_package_layout.py) фиксирует, что `asgi.app is
trainer.main.app`, что в корне нет `server.py` и что legacy-пути (`index.html`, `js/`, `data/`, `assets/`,
`styles.css` в корне) не отслеживаются Git. [scripts/check_repository_hygiene.py](scripts/check_repository_hygiene.py)
запрещает трекать `.env`, `var/`, `backups/`, `tmp/`, `test-results/`, `playwright-report/`, `*.key` и файлы
с приватными ключами.

## База данных

Один SQL-диалект на два движка. Весь код пишет **SQLite-диалект** (`?`-плейсхолдеры, `INSERT OR IGNORE`),
а [postgres.py](src/trainer/infrastructure/database/postgres.py) транслирует его на лету: `?` → `%s`,
`INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`, и дописывает `RETURNING id` для таблиц из `IDENTITY_TABLES`,
чтобы работал `cursor.lastrowid`. **Новая таблица, для которой нужен `lastrowid`, должна быть добавлена
в `IDENTITY_TABLES`.**

`connect()` из `api/runtime.py` — контекстный менеджер, выбирающий движок по `DATABASE_URL`; на выходе он
коммитит (или откатывает) и закрывает соединение.

Заморожены как baseline и не редактируются: миграции 1–7 в
[sqlite_migrations.py](src/trainer/infrastructure/database/sqlite_migrations.py) и `POSTGRES_SCHEMA` в
`postgres.py` (используется только ревизией `20260705_01`). Все новые изменения схемы — отдельной Alembic-ревизией
в `migrations/versions/`, работающей и на SQLite, и на PostgreSQL.

## Материалы и назначения

Каталог собирается из двух источников, объединяемых в [services/materials.py](src/trainer/services/materials.py):
официальные варианты из `content/variants/` (`index.json` + файлы) и авторские материалы из таблицы `materials`.
Гостю без сессии доступен только `open-2026` — и в списке, и в детальном запросе.

`EXAM_SPEC` в [domain/materials.py](src/trainer/domain/materials.py) задаёт тайминги, инструкции и количество
пунктов на сервере; редактор их не передаёт и не может переопределить. Роли преподавателя и автора выдаются
по allowlist (`TRAINER_TEACHER_EMAILS`, `TRAINER_EDITOR_MODE`/`TRAINER_EDITOR_EMAILS`) и требуют подтверждённого email.

Назначение хранит **неизменяемый снимок**: `assignments.material_snapshot_json` плюс копии изображений в
`assignment_material_assets`. [services/assignment_assets.py](src/trainer/services/assignment_assets.py)
переписывает ссылки `/api/material-assets/N` → `/api/assignment-assets/M` и при ошибке откатывает созданные
строки и объекты хранилища. Удаление или переиздание исходного материала не должно менять уже выданную работу.

## Frontend

Сборки нет: нативные ES-модули отдаются как есть catch-all маршрутом в `main.py`. Соответствие URL и каталогов:
страницы из белого списка → `frontend/pages/`, `js/` и `styles/` → `frontend/`, `assets/` → `public/`,
`content/reference/` → `content/reference/`. Всё остальное — 404.

Точки входа: `frontend/js/runner/app.js` (тренажёр + кабинет), `catalog/variants-page.js`,
`materials/material-editor.js`, `reference/reference-page.js`.

JS-тесты (`node --test`, без DOM) покрывают чистые функции, возвращающие разметку — `account-view.js`,
`task-view.js`, `variant-catalog.js`, `account-security.js`. Любой текст из БД или от преподавателя
пропускается через `escapeHtml` из `shared/progress.js`; на это есть отдельные тесты.

## Контент

`content/**/*.json` валидируется по схемам из `schemas/` (`validate_content` — ещё и pre-commit хук); неизвестные
поля запрещены, все ссылки на изображения должны существовать в `public/`. Изображения официальных вариантов —
`public/assets/variants/<год>/candidate-XX.webp`.

## legacy/

`legacy/` — временно сохранённый compatibility HTTP runtime. Он не входит в `make test`, `make check` и CI;
новые возможности туда не добавляются, основной код его не импортирует (это проверяется тестом).

## Конвенции

- Python 3.12+, ruff `line-length = 120`, двойные кавычки; ESLint покрывает `frontend/js`, `tests-js`, `tests-e2e`.
- Сообщения коммитов и пользовательские строки — на русском; коммит — короткий глагол в повелительной форме
  («Добавить проверку структуры материала»). Ветки: `feature/`, `fix/`, `docs/`, `codex/`.
- Не создавать коммит и не отправлять изменения во внешний репозиторий без явного решения владельца проекта
  ([CONTRIBUTING.md](CONTRIBUTING.md)).
- Не объявлять задачу завершённой без свежего успешного вывода `make check`.
