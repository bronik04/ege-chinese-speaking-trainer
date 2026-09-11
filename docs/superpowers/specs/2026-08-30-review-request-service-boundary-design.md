# Граница service/repository для review requests

## Контекст

`src/trainer/api/controllers/review_requests.py` сейчас одновременно разбирает transport-значения, применяет
правила review requests, открывает SQLite-соединения, выполняет SQL, координирует storage, ставит cleanup jobs и
пишет audit. Из-за этого HTTP-слой зависит от устройства БД, а транзакционные сценарии трудно тестировать без
полного API-runtime.

Первая итерация ограничена review requests. Остальные контроллеры, публичные HTTP-контракты, frontend, схема БД,
миграции и физические пути хранения не меняются.

## Цели

- Удалить из review-request controller прямые database imports, `connect()`, `.execute()` и знание SQL.
- Сохранить все восемь действующих сценариев: создание, загрузку записи, завершение, удаление, два списка,
  детализацию и оценивание.
- Перенести прикладную оркестрацию в `ReviewRequestService`.
- Ввести один высокоуровневый `ReviewRequestRepository` port и SQLite-реализацию.
- Сохранить текущие транзакционные гарантии, audit, cleanup и защиту конкурентных переходов статуса.
- Зафиксировать границу архитектурным тестом и покрыть service/repository отдельными тестами.

## Не входит в работу

- Рефакторинг `auth`, `materials`, `recordings`, `personal_recordings` или `groups`.
- Изменение Pydantic-схем, URL, JSON, cookies, кодов ошибок или HTTP-статусов.
- Изменение таблиц, индексов, Alembic revisions или frozen SQLite baseline.
- Переименование `var/assignment-assets`, переработка storage adapters или cleanup worker.
- Добавление dependency-injection framework либо нескольких предметных repositories.

## Выбранный подход

Используется прикладной сервис с одним высокоуровневым repository port. Это сохраняет явную границу и позволяет
заменить SQLite-адаптер в тесте, не вводя полноценный Unit of Work с отдельными repositories для заявок, записей,
assets и audit.

Простой перенос SQL в service-функции отклонён: он убрал бы SQL из controller, но не создал бы стабильный port.
Полный Unit of Work отклонён как избыточный для одной вертикальной области.

## Компоненты

### API controller

`src/trainer/api/controllers/review_requests.py` сохраняет существующие публичные функции. В нём остаются:

- преобразование query/header/body и Pydantic payload в прикладные значения;
- transport-ограничения, непосредственно связанные с запросом;
- проверка скрытого owner-only detail доступа;
- преобразование `ReviewRequestError` в прежние `ApiError`;
- упаковка результата сервиса в `ActionResult`.

Controller не открывает БД, не выполняет SQL и не импортирует database packages.

### Application service

`src/trainer/services/review_requests.py` содержит `ReviewRequestService`. Сервис принимает repository port,
runtime paths и текущие media/asset helpers через конструктор либо небольшой dependency bundle. Он отвечает за:

- validation selection, run-size, recording position, MIME type и размер аудио;
- получение и обрезку material snapshot;
- проверку длительности и временный файл;
- координацию записи storage до database transaction;
- определение обязательных recording positions;
- валидацию оценок;
- best-effort cleanup нового файла или snapshot assets после неуспешной транзакции;
- возврат transport-независимых словарей результата.

Сервис не импортирует `trainer.api`, `ApiError`, `ActionResult` или HTTP-статусы.

### Repository port

`src/trainer/services/review_request_repository.py` определяет `Protocol`, transaction/session port и небольшие
структуры данных для передачи записей. Port не импортирует `sqlite3` и не раскрывает connection или cursor.

Repository предоставляет намерения предметной области, а не произвольный SQL:

- открыть обычную или immediate transaction;
- найти опубликованный custom material и source material asset;
- создать uploading request, его items и asset registrations;
- получить и повторно проверить upload target;
- заменить recording и зарегистрировать cleanup старого storage key;
- проверить полноту и атомарно перевести request в `queued`;
- удалить uploading request и зарегистрировать cleanup его файлов;
- получить student/teacher lists и teacher detail;
- сохранить scores и перевести request в `reviewed`;
- записать audit в той же transaction, что и предметное изменение.

Asset snapshot helper получает только узкий registry port: чтение source asset metadata и регистрация созданного
review asset. Он больше не принимает SQLite connection.

### SQLite adapter

`src/trainer/infrastructure/database/review_request_repository.py` реализует port поверх существующего
connection factory. Он владеет SQL, `BEGIN IMMEDIATE`, commit/rollback и вызывает существующие query formatters,
audit writer и cleanup-job persistence.

Adapter не знает HTTP, Pydantic или `ActionResult`. Существующие query functions для list/detail сохраняются и
используются внутри adapter, пока их формат ответа соответствует текущему API.

### Composition root

`src/trainer/api/runtime.py` собирает `ReviewRequestService` с SQLite adapter и действующими путями
`ROOT`, `AUDIO_DIR`, `MATERIAL_ASSET_DIR`, `REVIEW_ASSET_DIR` и `DATA_DIR / "tmp"`. Controller получает готовый
сервис через runtime factory; FastAPI routes и их сигнатуры не меняются.

## Потоки данных и транзакции

### Создание

1. Controller передаёт payload, actor и request metadata сервису.
2. Сервис валидирует selection и сериализованный run.
3. Сервис получает официальный material из content либо custom material через repository.
4. В repository transaction создаётся uploading request.
5. Snapshot helper копирует assets через storage helper и регистрирует metadata через transaction port.
6. Transaction сохраняет task snapshots и audit, затем commit.
7. При ошибке БД откатывается, а уже созданные storage keys передаются в best-effort cleanup.

### Загрузка записи

1. Сервис валидирует task/question, MIME type, размер и duration.
2. Новый storage key записывается до открытия write transaction.
3. Immediate transaction повторно проверяет ownership и статус `uploading`, заменяет запись, ставит cleanup старого
   key и пишет audit.
4. При конфликте или ошибке новый key передаётся в cleanup; временный файл удаляется всегда.

### Завершение, удаление и оценивание

- Завершение в immediate transaction читает items/recordings, проверяет обязательные позиции и делает guarded
  update `uploading → queued` вместе с audit.
- Удаление в immediate transaction повторно проверяет статус, собирает keys, удаляет request каскадно, ставит
  cleanup job и пишет audit. Фактическая обработка cleanup после commit остаётся best-effort.
- Оценивание читает допустимый request и tasks, сервис валидирует scores, adapter сохраняет task scores,
  `reviewed_at`, reviewer и audit в одной transaction.

Read-only list/detail операции проходят через repository без write transaction. Сервис по-прежнему скрывает
итоговые баллы незавершённых student requests.

## Ошибки

`ReviewRequestError` содержит семантическую причину и необязательные details, но не HTTP-статус. Минимальный набор
причин: `not_found`, `not_uploading`, `incomplete`, `invalid_material`, `invalid_recording`, `invalid_scores`.

Controller централизованно отображает их на действующие error code, русское сообщение и HTTP status. Поля
`missing` для неполной заявки сохраняются без изменений. Неожиданные исключения не маскируются и продолжают
обрабатываться общим API error middleware.

## Совместимость

- Публичные controller functions и route calls сохраняют имена и аргументы.
- Ответы, статусы и error payload сравниваются существующими integration-тестами.
- SQL schema и данные не преобразуются.
- Storage keys и физические каталоги не меняются.
- Audit action names и details сохраняются.
- Конкурентные complete/discard/upload сценарии сохраняют guarded updates и `BEGIN IMMEDIATE`.

## Тестирование

Работа выполняется по TDD, вертикальными сценариями.

1. Архитектурный тест сначала запрещает для review-request controller database imports, `connect()` и `.execute()`.
2. Unit-тесты `ReviewRequestService` используют небольшой stateful fake repository, проверяя результат и
   предметные изменения, а не количество вызовов mock-объектов.
3. Integration-тесты SQLite adapter используют временную реальную БД и проверяют commit/rollback, audit,
   cleanup jobs и guarded state transitions.
4. Существующие API integration-тесты остаются контрактной проверкой create/upload/complete/discard/list/detail/score
   и конкурентных сценариев.
5. Обязательная итоговая команда — `make check`. Frontend не меняется, поэтому `make test-e2e` не требуется.

## Порядок миграции

1. Ввести port, semantic errors и read-only repository operations.
2. Перенести list/detail controller paths на сервис.
3. Перенести create и asset registry boundary.
4. Перенести upload/complete/discard с конкурентными тестами.
5. Перенести scoring.
6. Удалить последние database dependencies из controller, включить архитектурный guard и обновить документацию.

Каждый этап сохраняет рабочий API и завершается профильными тестами и отдельным commit.

## Результат реализации

Вертикальная граница реализована в модулях:

- `src/trainer/services/review_requests.py` — прикладная оркестрация восьми сценариев;
- `src/trainer/services/review_request_repository.py` — transport- и SQLite-независимые ports/структуры;
- `src/trainer/infrastructure/database/review_request_repository.py` — SQLite SQL, audit, cleanup и transactions;
- `src/trainer/api/runtime.py` — composition factory;
- `src/trainer/api/controllers/review_requests.py` — transport adapter без database imports, `.execute()` и
  `runtime.connect()`.

Snapshot helper принимает `ReviewAssetRegistry` и больше не импортирует API runtime. Публичные routes, schemas,
error payloads, migration/schema и storage paths не изменились. Guard в `tests/unit/test_architecture_boundaries.py`
фиксирует направление зависимостей.

Свежая обязательная проверка `make check` прошла: 18 JavaScript unit-тестов, 131 Python unit-тест, 95 Python
integration-тестов (2 PostgreSQL smoke-теста пропущены без `TEST_DATABASE_URL`), итоговое покрытие — 88%.
