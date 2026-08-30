# Техническая документация тренажёра

Этот документ описывает установку, разработку и эксплуатацию проекта. Пользовательская инструкция находится
в [README.md](README.md), архитектурные границы — в [docs/architecture.md](docs/architecture.md), правила
изменений — в [CONTRIBUTING.md](CONTRIBUTING.md), требования безопасности — в [SECURITY.md](SECURITY.md).

Эксплуатационные процедуры: [backup/restore](docs/runbooks/backup-restore.md),
[хранение записей](docs/runbooks/recording-retention.md) и
[реакция на инциденты](docs/runbooks/incident-response.md).

## Локальный запуск

```bash
make install
make run
```

Приложение откроется на `http://127.0.0.1:8080`. FastAPI через `asgi.py` — единственный HTTP runtime.
По умолчанию SQLite и приватные файлы находятся в `var/`; этот каталог не отслеживается Git.

## Структура проекта

- `src/trainer/main.py` — FastAPI-приложение, middleware и выдача публичных файлов;
- `src/trainer/api/routes/` — HTTP-маршруты, `api/controllers/` — синхронные прикладные сценарии;
- `src/trainer/api/schemas.py` и `api/errors.py` — Pydantic-контракты и единый формат ошибок;
- `src/trainer/domain/` — чистые правила аккаунтов, материалов, оценивания и срока хранения;
- `src/trainer/services/` — операции с материалами, записями, review snapshots и cleanup;
- `src/trainer/infrastructure/` — SQLite, S3/R2, локальное хранилище, SMTP/outbox и observability;
- `frontend/` — HTML, CSS и браузерные ES-модули без этапа сборки;
- `content/` — версионируемые JSON-материалы, `public/` — публичные изображения;
- `migrations/` — Alembic-ревизии после замороженного SQLite baseline 1–7;
- `scripts/` — backup, restore smoke, storage cleanup, content import и проверки;
- `tests/`, `tests-js/`, `tests-e2e/` — Python-, JavaScript- и Playwright-тесты.

## Конфигурация

```bash
cp .env.example .env
```

Основные переменные:

- `TRAINER_DATA_DIR` — SQLite, локальные аудио, закрытые изображения и outbox;
- `TRAINER_PUBLIC_URL` и `TRAINER_SECURE_COOKIE` — публичный HTTPS-адрес и защищённые cookie;
- `TRAINER_BIND_ADDRESS`, `TRAINER_PORT`, `TRAINER_LOG_LEVEL` — публикация и логи;
- `TRAINER_MAX_AUDIO_SECONDS`, `TRAINER_MAX_AUDIO_BYTES` — ограничения загрузок;
- `TRAINER_OWNER_EMAIL` — единственный подтверждённый владелец кабинета преподавателя;
- `TRAINER_EDITOR_MODE`, `TRAINER_EDITOR_EMAILS` — политика авторов материалов;
- `TRAINER_AUDIO_STORAGE` — `local` или `s3`;
- `TRAINER_S3_*`, `AWS_*` — закрытое S3/R2-хранилище;
- `TRAINER_SMTP_*` — SMTP; без SMTP локальная доставка использует приватный outbox.

При заданном `TRAINER_PUBLIC_URL` обязательно задайте `TRAINER_OWNER_EMAIL`. Ссылки подтверждения email и
сброса пароля строятся только из `TRAINER_PUBLIC_URL`; входящие `Host` и forwarded-заголовки для этого не
используются.

## Материалы и review requests

Официальные варианты лежат в `content/variants/` и выдаются через `/api/materials`. Гостю доступен только
`open-2026`. Авторские материалы хранятся в `materials` и `material_assets`; тайминги и инструкции задаются
серверным `EXAM_SPEC` и не принимаются из редактора.

```bash
.venv/bin/python -m scripts.validate_content
```

Заявка на разбор сохраняет неизменяемый снимок материала и приватные копии его изображений. Физический каталог
`var/assignment-assets` сохраняет историческое имя, но используется активным review-request workflow. Старые
таблицы групп, назначений и submissions остаются только для совместимости данных и удаления аккаунта; не
удаляйте их вручную.

Перед rollout очереди заявок:

1. Создайте backup базы и закрытого storage.
2. Задайте `TRAINER_OWNER_EMAIL` до регистрации владельца.
3. Обновите базу командой `.venv/bin/alembic upgrade head`.
4. Зарегистрируйте и подтвердите точный email владельца.
5. Проверьте health, вход ученика, очередь преподавателя и один review request.

## SQLite и Alembic

SQLite в WAL-режиме — единственный поддерживаемый движок. Миграции 1–7 в
`src/trainer/infrastructure/database/sqlite_migrations.py` заморожены: новая схема добавляется только новой
Alembic-ревизией.

```bash
.venv/bin/alembic revision -m "describe schema change"
.venv/bin/alembic upgrade head
.venv/bin/python -m unittest tests.integration.test_migrations.SqliteMigrationTest -v
```

Проверяйте чистую базу, обновление с предыдущей ревизии и повторный `upgrade head`. Опубликованные ревизии и
baseline не редактируйте.

## Закрытое хранилище и почта

Локальный storage включён по умолчанию. Для закрытого S3/R2 bucket:

```bash
TRAINER_AUDIO_STORAGE=s3
TRAINER_S3_BUCKET=chinese-ege-audio
TRAINER_S3_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=auto
```

Объекты не должны быть публичными; credential ограничивается нужным bucket/prefix. Smoke:

```bash
.venv/bin/python -m scripts.s3_smoke
```

В production настройте `TRAINER_SMTP_*`. В development без SMTP письма записываются в приватный каталог внутри
`TRAINER_DATA_DIR`; содержимое outbox нельзя публиковать или коммитить.

## Обслуживание и backup

```bash
.venv/bin/python -m scripts.backup --data-dir var --output-dir backups --keep 14
.venv/bin/python -m scripts.sqlite_restore_smoke
.venv/bin/python -m scripts.cleanup_storage
```

Backup переносится с хоста приложения и регулярно проверяется восстановлением. Для S3/R2 включите versioning
или provider backup: локальный скрипт bucket не копирует. `cleanup_storage` удаляет истёкшие записи и повторяет
устойчивые cleanup jobs; ненулевой код означает оставшиеся `failed` или `pending` задачи.

## Публичное развёртывание

```bash
docker compose up -d --build
```

Caddy принимает 80/443 и проксирует Uvicorn. DNS домена должен указывать на сервер. Альтернативная конфигурация
nginx находится в `deploy/nginx.conf`.

После изменения Docker:

```bash
make docker-check
make docker-build
docker compose up -d --build app
curl -fsS http://127.0.0.1:8080/api/health
```

## Проверки и CI

```bash
make lint
make test
make check
make test-e2e  # обязательно после изменения UI
```

`make check` запускает pre-commit, JavaScript-тесты, Python unit/integration и coverage. CI дополнительно
проверяет FastAPI health smoke, SQLite restore, Playwright, S3 adapter с MinIO, non-root Docker image и Compose
health. Минимальное Python-покрытие — 70%.
