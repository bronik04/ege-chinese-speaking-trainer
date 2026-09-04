# Граница сервиса прогресса

## Цель и согласованный объём

Убрать SQL и прикладные проверки из активного API-модуля с устаревшим названием `groups`.
Сохранить существующее поведение `GET /api/progress` и `PUT /api/progress`, историю тренировок,
права доступа и совместимость данных. Это архитектурный рефакторинг, а не новая синхронизация.

Исходная точка: `main`, коммит `f2b0c5b`. Пользователь согласовал переименование `groups` в
`progress`, выделение `ProgressService` и SQLite-адаптера, удаление неиспользуемых констант runtime.

## Текущее поведение

- `api/routes/groups.py` содержит только GET и PUT прогресса; оба используют `require_student`.
- `api/controllers/groups.py` открывает соединения, читает JSON, проверяет вход и выполняет UPSERT.
- Таблица `user_progress` хранит один документ и серверный `updated_at` на пользователя.
- GET без сохранённого документа возвращает `{"progress": null, "updatedAt": null}`.
- PUT заменяет документ целиком. Сервер не объединяет попытки и не сравнивает клиентские timestamps.
- Браузер объединяет локальную историю с результатом GET через `mergeProgress`, затем выполняет PUT.
- Внешний `updatedAt` ответа — целые Unix-секунды сервера; `updatedAt` внутри документа принадлежит клиенту.
- `runtime.EMAIL_RE` и `GROUP_CODE_ALPHABET` не используются. Рабочая проверка email находится в domain accounts.

## Подходы

Рекомендуется узкая вертикальная граница по уже принятому в проекте образцу: controller, service,
repository port и SQLite adapter. Она устраняет смешение HTTP и хранения и позволяет независимо
проверять правила прогресса и транзакции.

Только переименование файлов проще, но оставляет SQL и правила в controller. Общая переработка
синхронизации с серверным merge или optimistic locking меняет пользовательское поведение и выходит
за согласованный объём. Эти два подхода не выбираются.

## Ответственности

### API

- Переименовать `api/routes/groups.py` и `api/controllers/groups.py` в `progress.py`, обновить
  регистрацию router в `main.py`. Старые forwarding-модули не оставлять.
- Сохранить пути, методы, имена route-функций, `ProgressRequest` и `require_student`.
- Controller передаёт только ID текущего пользователя и документ сервису; преобразует результат
  в прежние `ActionResult`, а semantic errors — в прежние `ApiError`.
- В controller не остаётся SQL, соединений, JSON-кодирования, часов и правил проверки документа.

### Domain и service

- `domain/progress.py` содержит чистую проверку документа и ошибку с машинно-читаемой причиной.
- Сохранить текущие проверки: документ является dict, `version == 1`; отсутствующий `runs`
  трактуется для проверки как пустой список; переданный `runs` является списком не длиннее 200.
- Не вводить строгий тип версии, обязательность `runs`, проверку структуры каждой попытки или
  фильтрацию неизвестных полей. Текущее Python-сравнение версии, включая равенство `True` и `1.0`
  единице, не ужесточается в рефакторинге.
- `services/progress.py` предоставляет `ProgressService.get(user_id)` и `put(user_id, document)`.
  PUT валидирует вход до обращения к repository, получает время через injected clock и сохраняет
  весь документ. Сервис преобразует domain validation error в semantic service error.
- Service не импортирует API, SQLite, environment или infrastructure; не занимается merge.
- `services/progress_repository.py` описывает узкий `ProgressRepository` с методами чтения и
  сохранения и `ProgressRecord` с документом и серверным timestamp. HTTP-ключи остаются в API.

### Infrastructure и composition

- `infrastructure/database/progress_repository.py` реализует `SQLiteProgressRepository(connect)`.
- Adapter владеет SELECT, UPSERT, JSON-кодированием и декодированием, commit, rollback и закрытием
  соединения. Сохраняется `ensure_ascii=False`, компактные JSON-разделители и все поля документа.
- Успешное сохранение фиксируется до возврата; любая ошибка до commit не оставляет частичной записи.
- Чтение фильтруется по user_id; повторный PUT обновляет только строку этого пользователя.
- JSON при GET декодируется без дополнительной нормализации. Невалидный сохранённый JSON по-прежнему
  вызывает ошибку, а не незаметно заменяется пустой историей. Валидные исторические JSON-значения
  возвращаются как раньше, даже если они не соответствуют текущим правилам PUT.
- `runtime.progress_service()` собирает сервис и SQLite repository без кеширования и без storage
  или mail dependencies. Удаляются только неиспользуемые `EMAIL_RE`, `GROUP_CODE_ALPHABET` и import `re`.

## Контракты ошибок и транзакций

- Неверная версия: HTTP 400, code `invalid_request`, message `Invalid progress document`.
- Неверный тип `runs` или более 200 элементов: HTTP 400, code `invalid_request`,
  message `Progress history is too large`.
- Ошибки внешней Pydantic schema остаются HTTP 422; auth, origin guard и body limit не меняются.
- PUT возвращает `{"ok": true, "updatedAt": <server timestamp>}` только после commit.
- GET возвращает документ без изменений и timestamp его сохранения.
- Ошибки БД и сериализации не маскируются как успешное сохранение или validation error.
- Порядок двух конкурентных PUT определяется записью в SQLite, как раньше; разрешение конфликтов
  на основании времени клиента не добавляется.

## Что не меняется

Frontend, localStorage, debounce синхронизации, браузерный merge, лимит клиентской истории в 100
попыток, лимит сервера в 200, схема БД, миграции, старые таблицы групп/назначений/submissions,
архивные документы и правила очистки данных. Рефакторинг `safe_progress` и выдачи аудиофайлов не входит
в эту задачу. Новые функции, общий DI framework и compatibility wrappers не создаются.

## Проверка

- Domain unit: допустимый документ, отсутствие runs, границы 200/201, неверные version/runs,
  сохранение текущей неточной типизации version; без HTTP и БД.
- Service unit с fake repository и clock: validation до записи, полный документ, timestamp,
  отсутствие строки, передача ошибок хранилища без ложного успеха.
- SQLite integration: вставка, обновление, видимость commit через новое соединение, rollback,
  изоляция пользователей, Unicode/неизвестные поля, существующие и некорректные JSON-данные.
- Controller/runtime unit: mapping payload/error/result, composition без storage/mail и кеша.
- API integration: GET до PUT, round trip, повторная запись, изоляция двух пользователей,
  auth/role restrictions, ошибки 400/422 и отсутствие восстановленных legacy group routes.
- Архитектурные тесты: нет SQL и infrastructure в progress controller; нет API/infrastructure
  в domain/service/port; отсутствуют старые API-модули groups и удалённые runtime-константы.
- Обновить `docs/architecture.md`. Запустить `make check` и независимое ревью перед слиянием.
  Frontend не меняется, поэтому обязательного изменения JS/Playwright-тестов нет.

## Статус

Спецификация согласована пользователем сообщением «дальше». Реализация ещё не начата.
План реализации: `docs/superpowers/plans/2026-09-04-progress-service-boundary.md`.
