# Архитектура тренажёра

## Обзор

Браузерный frontend на vanilla JavaScript обращается к FastAPI через JSON API. FastAPI через `asgi.py` —
единственный HTTP runtime. SQLite в WAL-режиме — единственный поддерживаемый движок БД. Закрытые файлы
хранятся локально или в S3/R2; почта отправляется через SMTP либо приватный development outbox.

Решения зафиксированы в [ADR 0001](decisions/0001-fastapi-runtime.md),
[ADR 0002](decisions/0002-content-and-runtime-data.md),
[ADR 0003](decisions/0003-database-migration-strategy.md) и отменяющем dual-database требования
[ADR 0004](decisions/0004-sqlite-only-storage.md).

## Текущая структура

```text
asgi.py                         ASGI wrapper
src/trainer/main.py             FastAPI application и middleware
src/trainer/api/                routes, controllers, schemas, dependencies, errors
src/trainer/domain/             чистые бизнес-правила
src/trainer/services/           прикладные операции
src/trainer/infrastructure/     SQLite, storage, mailer, observability
frontend/                       HTML, CSS и браузерные ES-модули
content/                        версионируемые JSON-материалы
public/                         публичные браузерные assets
migrations/                     Alembic-ревизии SQLite
scripts/                        backup, restore, cleanup, import и проверки
tests*/, tests-e2e/             Python, JavaScript и Playwright
deploy/                         Caddy и nginx
```

Плоский модуль превращается в пакет только при появлении нескольких реальных ответственностей. Пустые
compatibility-слои и параллельные реализации не создаются.

## Границы и зависимости

- API знает HTTP, Pydantic, cookies, статусы и JSON-контракт.
- Domain описывает аккаунты, материалы, review selection, оценивание и retention без зависимости от HTTP,
  environment или внешних adapters.
- Services оркестрирует прикладные сценарии и зависит от infrastructure через явные ports там, где граница уже
  выделена.
- Infrastructure реализует SQLite, filesystem, S3/R2, SMTP/outbox и observability и не импортирует API.
- Frontend зависит только от публичного HTTP-контракта и публичных assets.

Контроллеры — синхронные функции, возвращающие `ActionResult`/`FileResult`. FastAPI routes выполняют их через
thread pool и преобразуют результат в response. Это сохраняет transport на границе API и позволяет тестировать
сценарии без web framework.

### Вертикальная граница аккаунтов

Все десять сценариев аутентификации и жизненного цикла аккаунта проходят через прикладной сервис:

```text
accounts routes/dependencies → auth controller → AccountService
AccountService → AccountRepository / AccountLinkSender / cleanup runner ports
runtime → SQLiteAccountRepository / MailAccountLinkSender / durable cleanup processor
```

Routes и dependencies отвечают за cookies и получение текущего пользователя, controller преобразует схемы и
`AccountError` в прежний HTTP-контракт. `AccountService` владеет регистрацией, входом, сессиями, подтверждением
email, восстановлением пароля, аудитом и удалением аккаунта, не импортируя API или infrastructure. SQLite adapter
владеет SQL, rate limits, account tokens и границами транзакций; mail adapter формирует и отправляет ссылки.

При удалении аккаунта SQLite adapter собирает ключи всех приватных файлов и ставит durable cleanup job в той же
транзакции, где записываются `account_deleted` и удаляется пользователь. Физическое удаление из storage начинается
только после commit. Если storage недоступен, аккаунт остаётся удалённым, а задача сохраняется для повторной
обработки.

### Вертикальная граница review requests

Все восемь review-request сценариев проходят через одну прикладную границу:

```text
review_requests controller
  → ReviewRequestService
    → ReviewRequestRepository port
      → SQLiteReviewRequestRepository
```

Controller разбирает HTTP-значения, проверяет owner-only detail и преобразует `ReviewRequestError` в прежний
`ApiError`. Service содержит правила selection, snapshots, аудиозаписей, переходов статуса и оценивания.
SQLite adapter владеет SQL, audit, cleanup jobs и обычными/immediate transactions. Snapshot helper получает
только `ReviewAssetRegistry`, а не database connection.

Каждая вертикальная миграция ограничена своим bounded context и не вводит общий DI framework. Остальные
контроллеры могут сохранять переходную структуру и переносятся только отдельными проверяемыми изменениями.

### Вертикальная граница материалов

Все девять material-сценариев проходят через одну прикладную границу:

```text
materials controller
  → MaterialService
    → MaterialRepository port
      → SQLiteMaterialRepository
    → image encoder и storage port
```

Controller преобразует API-входы и semantic errors в прежние HTTP-ответы. Service владеет видимостью каталога,
черновиками, публикацией, сохранением изображений из assignment snapshots и компенсационным удалением при сбое
загрузки. SQLite adapter владеет SQL, транзакциями и audit persistence, а Pillow adapter — декодированием,
проверкой и WebP-кодированием изображений. Публичные маршруты, payloads и правила storage при этом не меняются.

### Вертикальная граница личных записей

Создание, список и выдача личных тренировочных записей проходят через отдельный прикладной сервис:

```text
personal_recordings controller
  → PersonalRecordingService
    → PersonalRecordingRepository / storage ports
      → SQLitePersonalRecordingRepository / configured storage
```

Controller только преобразует Pydantic schema, `PersonalRecordingError` и `FileResult`. Service проверяет позицию
ответа, MIME, размер и длительность, управляет временным файлом и порядком записи в хранилище. Перед загрузкой
SQLite adapter отдельной транзакцией фиксирует cleanup intent с защитным интервалом. После успешной загрузки он
атомарно создаёт метаданные и удаляет intent; при сбое хранилища или финализации intent остаётся для повторной
очистки. SQL, SQLite-транзакции, ffprobe и выбор local/S3 storage не попадают в controller или service.

## Потоки данных

```text
Browser
  → FastAPI middleware и Pydantic validation
  → role dependency
  → controller
  → domain/service
  → SQLite и/или storage adapter
  → ActionResult/FileResult
  → единый API response с requestId
```

Review request сначала фиксирует selection и материал, затем сохраняет приватные аудио и snapshot-изображения.
После завершения uploading-заявка становится видна преподавателю. Удаление или переиздание исходного материала
не меняет snapshot.

SMTP использует adapter: при настроенном SMTP письмо отправляется провайдеру, иначе development-режим пишет
JSON в приватный outbox. Фоновые операции хранения выполняются командой
`.venv/bin/python -m scripts.cleanup_storage`.

## База и совместимость данных

Baseline SQLite 1–7 заморожен. При создании существующей базы он применяется и штампуется исходной
Alembic-ревизией; затем Alembic выполняет все последующие revisions. Новые изменения схемы добавляются только
новой ревизией.

Старые таблицы групп, назначений, submissions и reviews сохраняются, чтобы не терять существующие данные и
корректно удалять аккаунты. Активный UI и API их не развивают. Физический каталог `var/assignment-assets`
сохраняет историческое имя и содержит приватные изображения review snapshots.

## Категории файлов

| Категория | Назначение | Git | Публичный доступ |
|---|---|---:|---:|
| `content/` | проверяемые учебные материалы | да | только через разрешённый API |
| `public/` | браузерные изображения | да | да |
| `var/` | SQLite, аудио, assets, outbox | нет | нет |
| `backups/` | резервные копии | нет | нет |
| `tmp/` | воспроизводимые временные результаты | нет | нет |

Секреты находятся только в environment/secret manager. `.env.example` содержит имена и демонстрационные
значения, но не реальные credentials.

## Где размещать изменения

| Изменение | Каталог | Обязательная проверка |
|---|---|---|
| HTTP endpoint или schema | `src/trainer/api` | Python integration и OpenAPI contract |
| Бизнес-правило | `src/trainer/domain` | независимый unit test |
| Прикладная операция | `src/trainer/services` | unit/integration test |
| SQL или migration | `src/trainer/infrastructure/database`, `migrations/` | чистая, обновляемая и повторно обновляемая SQLite |
| Storage/SMTP | `src/trainer/infrastructure` | adapter test и профильный smoke |
| UI | `frontend/` | JS test и Playwright для сценария |
| Вариант или справочник | `content/`, `public/assets/variants` | JSON check и content test |
| Backup или cleanup | `scripts/` | unit/integration и smoke |

Правила безопасной работы с данными находятся в [SECURITY.md](../SECURITY.md), workflow — в
[CONTRIBUTING.md](../CONTRIBUTING.md).
