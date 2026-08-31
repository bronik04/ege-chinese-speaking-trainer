# Граница AccountService для аутентификации и жизненного цикла аккаунта

## Контекст

`src/trainer/api/controllers/auth.py` обслуживает десять публичных account-сценариев, но одновременно выполняет
валидацию и прикладную оркестрацию, открывает SQLite connections, содержит SQL, управляет rate limits, сессиями и
одноразовыми токенами, отправляет письма, собирает storage keys, ставит cleanup job и запускает физическую очистку.
Дополнительно `src/trainer/services/accounts.py` сам зависит от database, mailer и storage implementations, поэтому
нынешний «service» не является границей приложения.

В результате HTTP-слой нельзя изолированно тестировать без SQLite, account-правила распределены между controller,
service и database helper, а удаление аккаунта связывает API сразу с тремя инфраструктурными подсистемами. Эта
итерация выделяет одну вертикальную границу аккаунта по уже применённому в проекте шаблону
service/port/SQLite-adapter.

Публичные routes, cookies, Pydantic schemas, JSON-ответы, таблицы и frontend остаются без изменений.

## Цели

- Удалить из auth controller прямые database/storage/mailer imports, `connect()`, `.execute()` и управление
  транзакциями.
- Оставить в controller только преобразование API-входов, semantic error mapping и формирование `ActionResult`.
- Превратить `src/trainer/services/accounts.py` в transport- и adapter-независимый `AccountService`.
- Определить один `AccountRepository` port и SQLite-реализацию, которая владеет SQL, транзакциями, rate limits,
  сессиями и account tokens.
- Инъецировать отправку account links и post-commit storage cleanup через узкие ports/callables.
- Перевести разрешение текущего пользователя в `runtime.account_service()` без database access в API dependencies.
- Сохранить существующие статусы, error codes/messages/details, cookie-поведение, audit actions, TTL, лимиты,
  email delivery и порядок критичных commit points.
- Удалить мёртвый прямой helper `delete_account_storage()`: надёжная очистка уже выполняется через durable cleanup
  jobs.
- Зафиксировать границу architecture-, unit- и integration-тестами.

## Не входит в задачу

- Изменение routes, URL, Pydantic schemas, request/response JSON или session cookie options.
- Изменение таблиц, индексов, Alembic/SQLite migrations или frozen database baseline.
- Изменение password hashing algorithm, iteration count, token entropy, TTL или rate-limit policy.
- Добавление OAuth, MFA, refresh tokens, смены email, редактирования профиля или административного управления
  пользователями.
- Изменение frontend и пользовательских account-сценариев.
- Переработка role authorization, material editor allowlist или правил единственного teacher owner.
- Общий dependency-injection framework, ORM или единый Unit of Work для всего приложения.
- Общий рефакторинг `services/storage_cleanup.py`; в этой итерации account repository использует его существующие
  durable-job primitives из infrastructure adapter.
- Переработка account audit, который создают material и review-request adapters, кроме удаления их зависимости от
  конкретного `services.accounts` helper.

## Рассмотренные варианты

### 1. Только перенести SQL из controller в существующие функции `services/accounts.py`

Controller станет короче, но service продолжит принимать raw connection/connect factory и импортировать SQLite,
mailer и storage. Тесты по-прежнему будут зависеть от инфраструктуры, а архитектурная граница останется
номинальной.

### 2. Создать отдельные `AuthenticationService` и `AccountLifecycleService`

Разделение выглядит логично по названиям, однако оба сервиса используют одни и те же user/session/token/audit
транзакции и один repository. Сейчас это добавит coordination API и дублирование dataclasses без независимых
bounded contexts.

### 3. Один `AccountService` и один `AccountRepository` — выбранный вариант

Сервис оркестрирует все account use cases и зависит от предметных функций и ports. SQLite adapter владеет SQL и
транзакциями. Отправка ссылок и post-commit cleanup остаются отдельными injected dependencies, поскольку это не
repository responsibilities. Вариант даёт полноценную границу с минимальным количеством новых абстракций.

## Архитектура

```text
accounts route / account dependencies
  → auth controller
    → AccountService
      → AccountRepository port
        → SQLiteAccountRepository
      → AccountLinkSender port
        → MailAccountLinkSender
      → account cleanup runner
        → durable storage cleanup processor
```

### API routes и controller

`src/trainer/api/routes/accounts.py` не меняет десять routes и продолжает передавать Pydantic payloads,
`RequestContext`, session token и authenticated user в те же controller functions:

- `auth_register`;
- `auth_login`;
- `auth_logout`;
- `auth_me`;
- `email_verification_request`;
- `email_verification_confirm`;
- `password_reset_request`;
- `password_reset_confirm`;
- `account_audit`;
- `account_delete`.

`src/trainer/api/controllers/auth.py` преобразует payload/user/context в простые service arguments, вызывает
`runtime.account_service()`, переводит `AccountError` в прежний `ApiError` и формирует прежний `ActionResult`.
`auth_me` остаётся тривиальной transport-проверкой уже разрешённого user payload. В controller больше нет SQL,
database helpers, mailer/storage cleanup imports, environment configuration или `time`.

### Application service

`src/trainer/services/accounts.py` содержит `AccountService`, application result dataclasses и semantic
`AccountError(reason, message=None, retry_after=None)`. Сервис зависит только от standard library,
`trainer.domain.accounts` и account ports. Он отвечает за:

- нормализацию и проверку registration/login/password reset inputs;
- выбор registration role по configured owner email;
- проверку password hash;
- порядок rate-limit, repository transaction, session, audit и delivery операций;
- возврат публичного user payload без password hash;
- одинаковый ответ password reset request для существующего и неизвестного email;
- best-effort email delivery с `email_delivery_failed` audit;
- post-commit запуск durable cleanup после удаления аккаунта.

Сервис предоставляет методы `register`, `login`, `logout`, `current_user`, `request_email_verification`,
`confirm_email_verification`, `request_password_reset`, `confirm_password_reset`, `audit_events` и
`delete_account`. Controllers не вызывают repository напрямую.

Публичный user payload сохраняет поля `id`, `email`, `displayName`, `role`, `emailVerified`. Application results
для регистрации и входа отдельно несут session token; controller по-прежнему передаёт его route-слою через
`ActionResult.session_token`.

### Account ports

`src/trainer/services/account_repository.py` определяет immutable dataclasses, exceptions и Protocols:

- `AccountProfile` — публичные поля пользователя без password hash;
- `AccountRecord` — repository record с password hash для credential checks;
- `AccountIdentity` — минимальные `id/email` для logout/audit;
- `AccountRequestMetadata(client_ip, user_agent)`;
- `AccountAuditEvent` и `AccountAuditRecord`;
- `AccountConflictError` для duplicate email без зависимости от database driver;
- `AccountRepository` с read operations и `transaction()`;
- `AccountRepositorySession` с mutation/read operations внутри явной транзакции.

Repository/session methods выражают намерения и не раскрывают connection/cursor: consume/clear auth attempt,
find/create user, create/delete/resolve session, issue/consume account token, confirm email, replace password,
delete all user sessions, write/read audit, enqueue all account cleanup keys и delete user.

Port не импортирует `sqlite3`, API или infrastructure modules. Token values и password hashes допускаются только
там, где они нужны use case; публичные результаты никогда их не содержат.

`AccountLinkSender` — узкий Protocol с `send(kind, email, token) -> str`. Cleanup dependency — callable,
возвращающий adapter-neutral summary `completed/failed/pending`. Они инъецируются в `AccountService`, а не входят
в repository.

### SQLite adapter

Новый `src/trainer/infrastructure/database/account_repository.py` реализует port поверх connection factory.
Adapter владеет:

- всем user/session/account-token/rate-limit SQL;
- генерацией opaque session/account tokens и сохранением только их digest;
- прежними `RATE_LIMITS` и `TOKEN_TTL`;
- row-to-dataclass mapping;
- преобразованием supported integrity errors в `AccountConflictError`;
- commit при успехе, rollback при исключении и закрытием connection;
- сбором legacy recording, material, assignment, review и personal-recording storage keys до cascade delete;
- постановкой единого durable cleanup job в той же транзакции, что audit и удаление user.

Низкоуровневый `src/trainer/infrastructure/database/accounts.py` сохраняет только совместно используемые SQLite
primitives, если они нужны adapter-ам. `material_repository.py` и `review_request_repository.py` записывают audit
через infrastructure-level `record_audit`, а не импортируют конкретный `trainer.services.accounts`. Raw account
helpers больше не импортируются из API или application service.

### Account-link adapter

`src/trainer/infrastructure/mailer/account_links.py` реализует `AccountLinkSender` поверх существующего
`send_email()`:

- verification URL использует query parameter `verify`, reset URL — `reset`;
- configured public URL очищается от завершающего `/`;
- subject/body и сроки «24 часа»/«1 час» сохраняются;
- delivery остаётся `smtp` или `outbox`;
- outbox permissions и SMTP behavior остаются ответственностью существующего mailer.

Если sender выбрасывает исключение, `AccountService` не срывает успешную регистрацию или password-reset request:
он записывает `email_delivery_failed` с прежним `details.kind`, безопасно логирует тип ошибки и возвращает
`"failed"`, не включая token или письмо в лог.

### Runtime composition и configuration

`src/trainer/api/runtime.py` добавляет не кэшируемую factory `account_service()`. Она собирает:

- `SQLiteAccountRepository(connect)`;
- `MailAccountLinkSender(DATA_DIR, configured_public_url)`;
- owner email и `SESSION_DAYS`;
- cleanup runner, который открывает новое соединение и вызывает существующий `process_cleanup_jobs()` с
  `AUDIO_DIR`, `MATERIAL_ASSET_DIR` и `REVIEW_ASSET_DIR`.

Factory не кэшируется: integration fixtures по-прежнему могут менять `DB_PATH`, directories и environment между
сценариями.

Чтение `TRAINER_PUBLIC_URL` и `TRAINER_OWNER_EMAIL` переносится в чистые helpers `trainer.config`, чтобы и runtime,
и API dependencies использовали один источник без циклического импорта. `validate_account_configuration()`
остаётся API startup policy. `current_user_or_none()` вызывает `runtime.account_service().current_user()`;
`dependencies.py` больше не импортирует account service functions или database connect.

## Потоки данных и транзакции

### Регистрация

1. Service нормализует email/password, затем consume-ит attempt `register`; rate-limit transaction остаётся
   отдельной и завершается до validation error, как сейчас.
2. Service проверяет credentials и display name `2..80`, вычисляет role по owner email.
3. В одной transaction adapter создаёт user, заменяет/создаёт verification token и пишет
   `account_registered` audit. Duplicate email становится `AccountConflictError`.
4. Отдельная transaction создаёт 30-дневную session и возвращает raw token только service.
5. Отдельная transaction очищает успешный registration rate limit.
6. Sender отправляет verification link; ошибка доставки даёт `verificationDelivery: "failed"` и отдельный
   `email_delivery_failed` audit.
7. Controller возвращает прежний status 201, user payload и session cookie.

### Вход и выход

1. Login consume-ит rate-limit attempt до поиска пользователя.
2. Repository читает user по нормализованному email; service выполняет constant-time-compatible
   `password_matches()` для найденного hash.
3. Неуспех пишет `login_failed` отдельной transaction и возвращает прежний 401.
4. Успех создаёт session отдельной transaction; следующая transaction очищает rate limit и пишет
   `login_succeeded`.
5. Logout при наличии token в одной transaction разрешает identity, пишет `logout` для существующей session и
   удаляет session по digest. Отсутствующий/невалидный token по-прежнему возвращает `{ "ok": true }` и очищает
   cookie.

### Подтверждение email

1. Повторный request отклоняет уже подтверждённый account, consume-ит `email_verification` rate limit, затем в
   одной transaction заменяет token и пишет `email_verification_requested`.
2. Link delivery использует тот же best-effort путь, что регистрация.
3. Confirm в одной transaction атомарно consume-ит single-use token, выставляет `email_verified_at` и пишет
   `email_verified`. Пустой, слишком длинный, использованный или истёкший token даёт прежний `token_invalid`.

### Сброс пароля

1. Request consume-ит `password_reset` rate limit и в одной transaction ищет user.
2. Для найденного user adapter заменяет token и пишет `password_reset_requested`; для неизвестного email пишет
   `password_reset_requested_unknown`. Ответ в обоих случаях одинаков, чтобы не раскрывать наличие аккаунта.
3. Письмо отправляется только для найденного user и остаётся best effort.
4. Confirm сначала проверяет длину нового пароля `8..128`, затем в одной transaction consume-ит token, меняет
   hash, удаляет все sessions, очищает login rate limit для текущего request IP/email и пишет
   `password_reset_completed`.
5. Controller возвращает `{ "ok": true }` и очищает текущую cookie.

### Audit и удаление аккаунта

1. Audit list читается repository с прежним limit 50 и сортировкой `created_at DESC, id DESC`; JSON fields и
   названия ключей не меняются.
2. Delete transaction читает password hash и service проверяет password.
3. При неверном пароле `account_deletion_failed` фиксируется отдельной завершённой transaction, затем service
   возвращает semantic `invalid_password`. Это делает задуманное событие durable: текущий controller пытается
   записать его, но случайно откатывает вместе с исключением. Это единственное намеренное observable исправление
   в рамках переноса.
4. При верном пароле одна transaction собирает все storage keys до cascade, ставит durable cleanup job, пишет
   `account_deleted` и удаляет user. Audit сохраняется благодаря текущей nullable foreign-key policy.
5. Только после commit cleanup runner делает немедленную best-effort попытку. Ошибка не меняет успешный ответ:
   job остаётся в БД для startup/CLI retry, а service пишет structured log без приватных ключей.
6. Controller возвращает `{ "ok": true }` и очищает session cookie.

## Ошибки и совместимость API

Controller сохраняет текущие ответы:

- invalid email/password/display name при регистрации → `invalid_request`, 400, прежнее русское сообщение;
- duplicate email → `email_already_registered`, 409;
- превышение лимита → `rate_limited`, 429, `Retry-After` header и numeric `retryAfter` detail;
- неверный login → `invalid_credentials`, 401;
- уже подтверждённый email → `email_already_verified`, 409;
- невалидный/истёкший/использованный token → `token_invalid`, 400;
- invalid reset password length → `invalid_request`, 400;
- неверный пароль удаления → `invalid_password`, 401;
- отсутствие user в `auth_me` → `authentication_required`, 401.

Неожиданные database, mail-adapter programming и cleanup setup ошибки не превращаются в новые публичные codes.
Письма остаются best effort только в тех сценариях, где они были best effort раньше. Payload fields,
`verificationDelivery`/`delivery`, status 201 для регистрации, cookie set/clear и audit action names/details
сохраняются.

## Удаляемый код

После переключения всех callers удаляются:

- SQL и infrastructure orchestration из `api/controllers/auth.py`;
- функции `create_session`, `current_user`, `user_for_token`, `audit` и `send_account_link` в их текущем
  infrastructure-coupled виде из `services/accounts.py`;
- `delete_account_storage()` и его unit test: runtime-кода, вызывающего helper, нет, а direct deletion без durable
  job дублирует и ослабляет текущую cleanup policy;
- imports `trainer.services.accounts` из material/review SQLite adapters;
- прямой account service/connect import из `api/dependencies.py`.

Низкоуровневые database primitives удаляются либо становятся private только после `rg`-проверки всех callers;
`record_audit` остаётся общей infrastructure-функцией для SQLite adapters.

## Тестирование

1. Новый `tests/unit/test_account_application_service.py` использует stateful fake repository, fake link sender и
   fake cleanup runner. Он фиксирует validation, role, rate limiting, success/failure login, token flows,
   anti-enumeration reset response, delivery failure audit, deletion cleanup ordering и semantic errors без
   HTTP/SQLite/filesystem.
2. Новый `tests/integration/test_account_repository.py` использует временную мигрированную SQLite DB и проверяет
   row mapping, commit/rollback, duplicate email translation, rate-limit persistence, session expiry, single-use
   token/TTL, audit ordering, account key collection и atomic cleanup-job/delete.
3. Новый/расширенный controller contract test table-driven проверяет полный `AccountError` → `ApiError`
   code/message/status/header/detail mapping и прежние `ActionResult` fields.
4. Существующие `tests/integration/test_accounts.py`, `test_api_flows.py` и `test_asgi.py` продолжают фиксировать
   HTTP contracts, outbox, auth flow и cleanup. Cleanup failure/inspection patch seam переносится с
   `auth.process_cleanup_jobs` на runtime composition.
5. `tests/unit/test_architecture_boundaries.py` запрещает auth controller database/storage/mailer/domain access,
   запрещает API/database-implementation imports в account service, infrastructure imports в port и API imports
   в SQLite/link adapters. Отдельная проверка подтверждает, что API dependencies не открывает database.
6. `docs/architecture.md` получает account vertical boundary и post-commit cleanup flow.
7. Итоговая обязательная проверка — `make check`. UI не меняется, поэтому `make test-e2e` не требуется.

## Последовательность реализации

1. Добавить ports и failing application-service/architecture tests.
2. Реализовать `AccountService` на fake repository, начиная с registration/login/current user/logout.
3. Добавить SQLite adapter и repository integration tests для users/sessions/rate limits/tokens/audit.
4. Перенести email verification, password reset и account-link adapter.
5. Перенести account deletion, durable cleanup enqueue и post-commit runner.
6. Свести controller/dependencies к transport mapping, добавить runtime composition и убрать старые helpers.
7. Обновить HTTP tests и архитектурную документацию, выполнить полную проверку и code review.

## Критерии готовности

- Auth controller не импортирует infrastructure/domain, не содержит `connect()`, `.execute()`, SQL, mail или
  storage cleanup orchestration.
- `AccountService` не импортирует `trainer.api`, `trainer.infrastructure` или `sqlite3` и не принимает raw
  connection.
- Account repository port не импортирует `sqlite3` или `trainer.infrastructure`.
- SQLite и account-link adapters не импортируют `trainer.api`.
- API dependencies разрешает session user только через `runtime.account_service()` и не открывает database.
- Все десять controller signatures, routes, payloads, statuses, cookies, public error contracts и audit action
  names сохранены.
- Rate limits, 30-day session, 24-hour verification token и 1-hour reset token сохраняют текущую политику.
- Account deletion атомарно ставит durable cleanup job до user cascade и запускает физическую очистку только
  после commit.
- Мёртвый direct-storage helper удалён; material/review adapters больше не зависят от concrete account service.
- Schema, migrations, frontend и content не изменены.
- `make check` завершён с нулевым кодом.
