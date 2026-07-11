# Техническая документация тренажёра

Этот документ предназначен для разработки, сопровождения и развёртывания проекта. Пользовательская инструкция находится в [README.md](README.md).

Архитектурные границы и направление миграции описаны в [docs/architecture.md](docs/architecture.md), порядок внесения изменений — в [CONTRIBUTING.md](CONTRIBUTING.md), правила безопасности — в [SECURITY.md](SECURITY.md). Обязательные ориентиры для разработчиков и AI-агентов находятся в [AGENTS.md](AGENTS.md).

## Локальный запуск

```bash
make install
make run
```

Откройте `http://127.0.0.1:8080`. Основной и единственный целевой production runtime — FastAPI + Uvicorn через `asgi.py`. `server.py` имеет статус legacy: он временно сохранён для совместимости, не получает новые возможности и будет удалён отдельной задачей после проверки оставшихся потребителей.

По умолчанию используется SQLite в `var/trainer.sqlite3`. Каталог `var/` исключён из Git.

## Текущая структура проекта

Целевая структура и правила размещения нового кода описаны в [архитектурном документе](docs/architecture.md). Ниже перечислено фактическое расположение файлов до поэтапной миграции.

- `src/trainer/main.py` — FastAPI-приложение, корневой `asgi.py` — совместимая точка входа;
- `src/trainer/api/routes/` — маршруты FastAPI;
- `src/trainer/api/schemas.py` — Pydantic-контракты;
- `src/trainer/api/controllers/` — авторизация, аккаунты, группы, работы, записи и материалы;
- `src/trainer/domain/` — чистые бизнес-правила;
- `src/trainer/services/` — прикладные сервисы материалов и транскрибации;
- `src/trainer/infrastructure/` — БД, storage, mailer, exports и внешние adapters;
- `src/trainer/workers/` — фоновые процессы, запускаемые через wrappers из `scripts/`;
- `app.js` — точка сборки основного интерфейса;
- `js/account-*-controller.js` — части кабинета пользователя и преподавателя;
- `js/runner-controller.js` — экзаменационный сценарий;
- `js/project-select.js` — единый интерфейс выпадающих списков;
- `frontend/pages/variants.html` и `frontend/js/catalog/variant-catalog.js` — каталог материалов;
- `variant-editor.html` и `js/material-editor.js` — редактор вариантов и заданий;
- `frontend/pages/reference.html`, `frontend/js/reference/reference-page.js` и `content/reference/` — учебный справочник;
- `content/variants/` — официальные варианты;
- `migrations/` — Alembic-миграции PostgreSQL;
- `tests/`, `tests-js/`, `tests-e2e/` — серверные, клиентские и браузерные тесты.

## Конфигурация окружения

Скопируйте пример и измените значения:

```bash
cp .env.example .env
```

Основные переменные:

- `TRAINER_DATA_DIR` — БД, локальные аудио и изображения;
- `TRAINER_PUBLIC_URL` — публичный HTTPS-адрес;
- `TRAINER_SECURE_COOKIE=1` — защищённые cookie в продакшене;
- `TRAINER_LOG_LEVEL` — уровень структурированных логов;
- `TRAINER_MAX_AUDIO_SECONDS`, `TRAINER_MAX_AUDIO_BYTES` — ограничения аудио;
- `TRAINER_TEACHER_EMAILS` — email, которым разрешена роль преподавателя;
- `TRAINER_EDITOR_MODE` — политика авторов материалов;
- `TRAINER_EDITOR_EMAILS` — email авторов для режима `allowlist`;
- `DATABASE_URL` — подключение PostgreSQL;
- `TRAINER_AUDIO_STORAGE` — `local` или `s3`.

## Материалы и политика авторов

Официальные варианты хранятся в `content/variants/` и доступны только через `/api/materials`. Гостю API возвращает только `open-2026`.

Перед добавлением или изменением варианта, справочника либо связанных изображений запустите:

```bash
python -m scripts.validate_content
```

Команда проверяет JSON по схемам из `schemas/`, согласованность `content/variants/index.json` с файлами вариантов и наличие всех изображений в `public/`. Неизвестные поля запрещены. Новый официальный вариант добавляется как JSON-файл, запись в `index.json` и набор WebP-изображений; запуск HTTP-сервера для проверки не требуется.

Авторские материалы хранятся в таблицах `materials` и `material_assets`. Полный вариант содержит задания 1–3, отдельный материал — одно выбранное задание. Тайминги и требования формируются сервером и не принимаются из редактора.

Редактор доступен только подтверждённым email из allowlist:

```bash
TRAINER_EDITOR_MODE=allowlist
TRAINER_EDITOR_EMAILS=owner@example.ru
```

Роль преподавателя также выдаётся по allowlist. До подтверждения email группы, назначения и проверка работ заблокированы:

```bash
TRAINER_TEACHER_EMAILS=teacher@example.ru
```

Назначение хранит неизменяемый снимок материала. Удаление или переиздание исходного варианта не меняет уже выданную работу. Работы после `dueAt` принимаются, но помечаются как просроченные.

Изображения официальных вариантов находятся в `public/assets/variants/<год>/`, используют WebP и имя `candidate-XX.webp`.

## Публичное развёртывание

```bash
docker compose up -d --build
```

Caddy принимает порты 80/443, получает TLS-сертификат, включает сжатие и проксирует запросы в Uvicorn. DNS домена должен указывать на сервер. Альтернативная конфигурация nginx находится в `deploy/nginx.conf`.

Приложение и прокси ограничивают размер запроса. Аудио дополнительно проверяется через `ffprobe`: максимум 30 секунд для задания 1, 150 секунд для задания 2 и 210 секунд для задания 3.

## SQLite и PostgreSQL

SQLite остаётся основным режимом и использует версионированные миграции из `src/trainer/infrastructure/database/sqlite_migrations.py`.

PostgreSQL 16 предназначен для масштабирования:

```bash
docker compose -f compose.yml -f compose.scale.yml up -d --build
```

В scale-профиле используется пул соединений, а схема обновляется Alembic. Версия PostgreSQL и `pg_dump` синхронизирована между Docker и CI.

## Аудио и S3/R2

Локальное хранилище включено по умолчанию. Для закрытого бакета Cloudflare R2 или другого S3-совместимого хранилища задайте:

```bash
TRAINER_AUDIO_STORAGE=s3
TRAINER_S3_BUCKET=chinese-ege-audio
TRAINER_S3_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=auto
```

Токен должен иметь права только на нужный бакет. Объекты не должны быть публичными.

## Автоматическая расшифровка

```bash
TRAINER_TRANSCRIPTION_ENABLED=1
OPENAI_API_KEY=...
OPENAI_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
TRAINER_TRANSCRIPTION_LANGUAGE=zh
```

Запись сначала попадает в устойчивую очередь БД. Воркер запускается отдельно:

```bash
.venv/bin/python -m scripts.transcription_worker
```

В Docker: `docker compose --profile transcription up -d --build`. Временные ошибки повторяются до трёх раз, зависшие задания возвращаются в очередь через 15 минут.

## Почта и аккаунты

Без SMTP письма записываются в закрытый файл `var/outbox.log`. Для публичной версии задайте:

```bash
TRAINER_SMTP_HOST=smtp.example.ru
TRAINER_SMTP_PORT=465
TRAINER_SMTP_SSL=1
TRAINER_SMTP_USER=...
TRAINER_SMTP_PASSWORD=...
TRAINER_SMTP_FROM=noreply@example.ru
```

Для порта 587 используйте `TRAINER_SMTP_SSL=0` и `TRAINER_SMTP_STARTTLS=1`. Секреты нельзя коммитить в репозиторий.

Пароли хранятся как PBKDF2-хеши с солью. Сессии используют `HttpOnly` cookie, подтверждение email действует 24 часа, восстановление пароля — один час. Rate limit и журнал действий хранятся в БД.

## Резервное копирование

```bash
docker compose exec app python scripts/backup.py --data-dir /app/var --output-dir /app/backups --keep 14
```

Для SQLite используется Backup API, для PostgreSQL — `pg_dump`. В локальном режиме отдельно архивируются аудио и изображения авторских материалов. Копии следует ежедневно переносить на другой сервер или в объектное хранилище и регулярно проверять восстановление. Для R2 резервирование бакета настраивается у провайдера.

## Ошибки и наблюдаемость

API возвращает единый формат:

```json
{
  "code": "invalid_credentials",
  "message": "Неверный email или пароль",
  "requestId": "c5f1d43f8cf94a488afe9ab85d891d25"
}
```

`X-Request-ID` связывает ответ со структурированным JSON-логом. `/api/health` возвращает состояние БД и агрегированные счётчики 4xx/5xx без пользовательских данных.

## Тестирование и контроль качества

```bash
make install
.venv/bin/pre-commit install
make lint
make test
npx playwright install chromium
make test-e2e
```

Все проверки перед коммитом:

```bash
make check
```

Для проверки deployment-конфигурации используйте `make docker-check`, для локальной сборки image — `make docker-build`. Низкоуровневые команды (`.venv/bin/python -m ruff`, `npm run lint:js`, `python -m coverage`) остаются доступны для диагностики отдельных ошибок.

CI также проверяет PostgreSQL 16 с Alembic и восстановлением `pg_dump`, а S3-контракт — через MinIO. Минимальное Python-покрытие — 70%.
