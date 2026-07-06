# Техническая документация тренажёра

Этот документ предназначен для разработки, сопровождения и развёртывания проекта. Пользовательская инструкция находится в [README.md](README.md).

## Локальный запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn asgi:app --host 127.0.0.1 --port 8080
```

Откройте `http://127.0.0.1:8080`. Основной сервер — FastAPI + Uvicorn через `asgi.py`. `server.py` сохранён как совместимый переходный сервер.

По умолчанию используется SQLite в `var/trainer.sqlite3`. Каталог `var/` исключён из Git.

## Структура проекта

- `asgi.py` и `api/routes/` — маршруты FastAPI;
- `api/schemas.py` — Pydantic-контракты;
- `api/controllers/` — авторизация, аккаунты, группы, работы, записи и материалы;
- `backend/` — БД, миграции, запросы, безопасность, хранилище и оценивание;
- `app.js` — точка сборки основного интерфейса;
- `js/account-*-controller.js` — части кабинета пользователя и преподавателя;
- `js/runner-controller.js` — экзаменационный сценарий;
- `js/project-select.js` — единый интерфейс выпадающих списков;
- `variants.html` и `js/variant-catalog.js` — каталог материалов;
- `variant-editor.html` и `js/material-editor.js` — редактор вариантов и заданий;
- `reference.html`, `js/reference-page.js` и `data/reference/` — учебный справочник;
- `data/variants/` — официальные варианты;
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
- `TRAINER_EDITOR_MODE` — политика авторов материалов;
- `TRAINER_EDITOR_EMAILS` — email авторов для режима `allowlist`;
- `DATABASE_URL` — подключение PostgreSQL;
- `TRAINER_AUDIO_STORAGE` — `local` или `s3`.

## Материалы и политика авторов

Официальные варианты хранятся в `data/variants/` и доступны только через `/api/materials`. Гостю API возвращает только `open-2026`.

Авторские материалы хранятся в таблицах `materials` и `material_assets`. Полный вариант содержит задания 1–3, отдельный материал — одно выбранное задание. Тайминги и требования формируются сервером и не принимаются из редактора.

По умолчанию редактор разрешён всем вошедшим пользователям:

```bash
TRAINER_EDITOR_MODE=authenticated
```

Для ограничения владельцем проекта:

```bash
TRAINER_EDITOR_MODE=allowlist
TRAINER_EDITOR_EMAILS=owner@example.ru
```

Изображения официальных вариантов находятся в `assets/variants/<год>/`, используют WebP и имя `candidate-XX.webp`.

## Публичное развёртывание

```bash
docker compose up -d --build
```

Caddy принимает порты 80/443, получает TLS-сертификат, включает сжатие и проксирует запросы в Uvicorn. DNS домена должен указывать на сервер. Альтернативная конфигурация nginx находится в `deploy/nginx.conf`.

Приложение и прокси ограничивают размер запроса. Аудио дополнительно проверяется через `ffprobe`: максимум 30 секунд для задания 1, 150 секунд для задания 2 и 210 секунд для задания 3.

## SQLite и PostgreSQL

SQLite остаётся основным режимом и использует версионированные миграции из `backend/migrations.py`.

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
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm install
.venv/bin/pre-commit install
.venv/bin/ruff check .
npm run lint:js
npm test
npx playwright install chromium
npm run test:e2e
.venv/bin/coverage run -m unittest discover -s tests -v
.venv/bin/coverage report
```

Все проверки перед коммитом:

```bash
.venv/bin/pre-commit run --all-files
```

CI также проверяет PostgreSQL 16 с Alembic и восстановлением `pg_dump`, а S3-контракт — через MinIO. Минимальное Python-покрытие — 55%.
