# Граница сервиса очистки хранилищ

## Цель и согласованный объём

Убрать SQL, SQLite-транзакции, JSON-представление заданий, чтение окружения и
операции с файловыми хранилищами из прикладного модуля очистки. Сохранить
существующие пользовательские и эксплуатационные контракты, но заменить старый
процедурный API полноценной границей `StorageCleanupService`.

В объём входит полный переход runtime, CLI, репозиториев аккаунтов, review-запросов
и личных записей на новый сервис и SQLite-адаптер. После перехода функции
`expire_recordings`, `enqueue_cleanup_job`, `process_cleanup_jobs` и
`account_review_storage_keys` удаляются.

## Текущее поведение и проблема

`services/storage_cleanup.py` одновременно:

- выполняет SQL и управляет SQLite-транзакциями;
- сериализует ключи в JSON и знает физическую схему таблицы очереди;
- получает серверное время и реализует расписание повторов;
- создаёт local/S3/R2 storage из окружения и удаляет объекты;
- содержит прикладное итоговое представление результата.

Из-за этого infrastructure-репозитории импортируют функции из прикладного
модуля, а runtime, CLI и тесты работают напрямую с соединением SQLite. Review-
репозиторий дополнительно запускает прикладной cleanup-сценарий и хранит пути к
трём storage roots.

Существующие гарантии, которые необходимо сохранить:

- удаление метаданных и постановка cleanup-задания атомарны;
- удаление аккаунта и постановка задания для связанных файлов атомарны;
- замена или удаление review-файлов ставит старые ключи в очередь в той же
  транзакции;
- upload intent личной записи защищает файл от потери, а успешная финализация
  атомарно отменяет intent;
- отсутствие объекта при удалении считается успехом;
- startup- и opportunistic-cleanup не ломают основной пользовательский сценарий;
- CLI сообщает количества и завершается с ошибкой при failed или pending.

## Рассмотренные подходы

### Application service, port и SQLite adapter — выбран

`StorageCleanupService` владеет сценарием и политикой повторов, нейтральный port —
контрактом очереди, SQLite adapter — SQL, JSON и транзакциями. Storage adapters
передаются сервису через минимальные factory-интерфейсы. Транзакционные producer-
репозитории используют SQLite-компонент очереди на уже открытом соединении.

Этот вариант соответствует границам проекта, допускает unit-тестирование без
SQLite и сохраняет атомарность существующих операций.

### Тонкая оболочка над процедурным SQLite-модулем

Вариант требует меньше изменений, но сохраняет зависимость сценария от SQLite и
оставляет тесты привязанными к физической схеме. Архитектурная проблема меняет
форму, но не исчезает.

### Полный cleanup внутри infrastructure repository

Вызовы становятся короче, однако один infrastructure-компонент начинает владеть
БД, внешним storage, временем, повторами и итогами сценария. Это закрепляет
смешение обязанностей и поэтому отклонено.

## Архитектура и компоненты

~~~text
runtime / cleanup CLI / application services
  -> StorageCleanupService
       -> StorageCleanupRepository port
            -> SQLiteStorageCleanupRepository
       -> audio/material/review storage factories
            -> configured local/S3/R2 adapters

SQLite account/review/personal repositories
  -> SQLiteStorageCleanupQueue(existing connection)
       -> storage_cleanup_jobs
~~~

### Application service

`services/storage_cleanup.py` содержит:

- `StorageCleanupService`;
- `CleanupSummary(completed, failed, pending)`;
- минимальный `CleanupStorage` protocol с операцией `delete(key)`;
- тип factory, который создаёт `CleanupStorage` только при фактической обработке
  ключей соответствующей категории.

Сервис не импортирует API, SQLite, infrastructure, `Path`, JSON или переменные
окружения. Он получает repository, три storage factory, часы, длительность lease
и задержку повтора через конструктор.

Публичные методы сервиса:

- `expire_batch(*, limit=500, now=None) -> int`;
- `process_batch(*, limit=50, now=None) -> CleanupSummary`.

Явный `now` нужен для CLI и детерминированных тестов. При его отсутствии
используется внедрённый clock. Отрицательный limit нормализуется в ноль.

### Repository port и нейтральные модели

`services/storage_cleanup_repository.py` определяет неизменяемые структуры:

- `CleanupKeys` с кортежами audio, material и assignment ключей;
- `ClaimedCleanupJob` с ID, ключами, сроком lease и необязательной ошибкой
  декодирования;
- `CleanupOutcome` с ID задания и необязательной строкой ошибки;
- результат фиксации пакета с количествами applied completed, applied failed и
  общим pending.

`StorageCleanupRepository` предоставляет операции:

- атомарно удалить ограниченный пакет просроченных метаданных и поставить ключи
  в очередь;
- атомарно зарезервировать готовый пакет до заданного `lease_until`;
- атомарно применить результаты только к заданиям с тем же lease;
- получить общее количество ожидающих заданий.

Port не знает о SQLite, JSON, filesystem или конкретных storage backends.

### SQLite adapter и транзакционная очередь

Новый `infrastructure/database/storage_cleanup_repository.py` содержит:

- `SQLiteStorageCleanupRepository(connect_factory)`, реализующий port и
  самостоятельно открывающий соединения;
- `SQLiteStorageCleanupQueue(database)`, работающий на переданном соединении и
  предоставляющий `enqueue(keys, *, now, available_at=None)` и `cancel(job_id)`
  без commit/rollback;
- внутренние преобразования между JSON-колонками и нейтральными моделями.

`SQLiteStorageCleanupQueue` не завершает транзакцию: ею владеет вызывающий
account, review или personal repository. Ключи фильтруются до непустых строк и
дедуплицируются с сохранением порядка, как сейчас.

Имя `assignment_keys_json` сохраняется в схеме и adapter-е для совместимости с
существующими данными. Новая миграция не создаётся. На уровне прикладного
контракта это остаётся третьей категорией ключей, используемой для assignment и
review snapshot assets.

## Потоки данных и транзакции

### Producers cleanup-заданий

- `SQLiteAccountRepositorySession` собирает legacy audio, material assets,
  assignment assets, review audio, review assets и personal audio пользователя,
  после чего вызывает `SQLiteStorageCleanupQueue` до удаления пользователя. Всё
  фиксируется или откатывается одной account-транзакцией.
- Review session ставит заменённые или удаляемые audio/assets в очередь до
  завершения транзакции изменения review-запроса. `ReviewRequestService`
  передаёт во все такие вызовы значение своих внедрённых часов.
- Отдельный orphan cleanup создаёт долговечное задание собственной короткой
  транзакцией после неуспешной записи файла или snapshot-а и также получает
  явный `now` от `ReviewRequestService`.
- Personal repository создаёт upload intent отдельной транзакцией до записи
  объекта. `finalize_recording` добавляет метаданные и вызывает `cancel` для
  intent в одной `BEGIN IMMEDIATE` транзакции. Отсутствующий intent сохраняет
  прежнюю ошибку `PersonalRecordingIntentError`.

SQL для поиска всех ключей аккаунта принадлежит account SQLite repository;
отдельной прикладной функции `account_review_storage_keys` больше нет.

### Истечение записей

`expire_batch` вычисляет момент и делегирует adapter-у. Adapter под
`BEGIN IMMEDIATE`:

1. выбирает общий ограниченный пакет personal и review recordings с
   `expires_at <= now` в прежнем порядке;
2. удаляет выбранные строки метаданных;
3. создаёт одно cleanup-задание для уникальных audio keys;
4. фиксирует транзакцию.

Любая ошибка откатывает и удаление строк, и постановку задания.

### Claim, внешнее удаление и фиксация результата

`process_batch` использует короткий lease вместо удержания SQLite write-lock во
время local/S3/R2 I/O:

1. Adapter под `BEGIN IMMEDIATE` выбирает `available_at <= now`, устанавливает
   выбранным строкам `available_at = lease_until` и фиксирует claim.
2. Сервис лениво создаёт не более одного storage adapter каждой категории на
   пакет и пытается обработать все ключи каждого задания.
3. Сервис передаёт outcomes adapter-у. Adapter короткой транзакцией удаляет
   успешные задания, а ошибочным увеличивает `attempts`, записывает `last_error`
   и устанавливает `available_at = now + retry_delay`.
4. UPDATE и DELETE содержат условие на ID и исходный `lease_until`. Результат
   завершившегося поздно worker-а не может перезаписать более новый claim.
5. Adapter возвращает количества реально применённых результатов и общий
   pending; из них формируется `CleanupSummary`.

Lease и retry delay по умолчанию равны одному часу. Если worker завершается после
удаления объекта, но до фиксации результата, задание снова станет доступно после
lease. Повтор безопасен благодаря идемпотентному контракту удаления.

## Ошибки

- `FileNotFoundError` означает успешное удаление.
- После ошибки одного ключа сервис продолжает остальные ключи и категории
  задания. В outcome попадает первая ошибка в формате `TypeName: message`.
- Успешно удалённые ключи ошибочного задания могут обрабатываться повторно; это
  ожидаемая цена атомарного результата на уровне задания.
- Ошибка создания storage adapter считается ошибкой каждого задания, которому
  нужна эта категория. Другие категории и задания продолжают обрабатываться.
- Некорректный JSON или типы ключей превращаются SQLite adapter-ом в
  `ClaimedCleanupJob` с ошибкой декодирования. Одно повреждённое задание не
  прерывает пакет и откладывается на общий retry interval.
- Исключение самого repository не маскируется сервисом.
- Startup cleanup остаётся в общем `try/except` runtime и журналирует событие
  `storage_cleanup_startup_failed`.
- Review orphan/discard cleanup остаётся под `suppress(Exception)` и не меняет
  ответ основного сценария.
- Account cleanup сохраняет существующее логирование success/failure после уже
  завершённого удаления аккаунта.

## Composition и совместимость вызовов

Runtime предоставляет factory `storage_cleanup_service()`. Она собирает
`SQLiteStorageCleanupRepository(connect)` и три ленивые factory на основе
`storage_from_env` для `AUDIO_DIR`, `MATERIAL_ASSET_DIR` и `REVIEW_ASSET_DIR`.

- `init_database` вызывает один expiry batch и один processing batch с прежним
  best-effort поведением и прежними log event/fields.
- Account cleanup runner вызывает `process_batch` и преобразует результат в
  существующий `AccountCleanupSummary`.
- `ReviewRequestService` получает best-effort processing callback. Метод
  `process_cleanup` удаляется из review repository port и SQLite adapter, а его
  конструктор больше не принимает storage roots.
- CLI создаёт сервис после `init_database(cleanup=False)`, сохраняет единый
  `cleanup_cutoff`, обрабатывает expiry и cleanup пакетами по 500 и печатает
  точную строку
  `expired=X completed=Y failed=Z pending=P`. Exit code остаётся ненулевым при
  `failed > 0` или `pending > 0`.
- `UPLOAD_INTENT_GRACE_SECONDS` переносится из storage cleanup в модуль личных
  записей без изменения значения в один час.

HTTP routes, schemas, ответы, сроки хранения, storage keys и frontend не
меняются.

## Проверка

- Service unit tests: пустой пакет, успешное удаление, отсутствующий объект,
  частичный сбой с продолжением, ошибка storage factory, decode error, первая
  ошибка, фиксированные clock/now, lease и retry timestamps, applied summaries.
- SQLite adapter tests: дедупликация и JSON, enqueue/cancel без самостоятельного
  commit, rollback внешней транзакции, атомарное истечение, общий порядок и
  limit, claim lease, недоступность второго claim до окончания lease, повторный
  claim после lease, защита от stale outcome и malformed payload.
- Producer integration tests: account keys и атомарное удаление, personal upload
  intent/finalize, review replacement/discard/orphan cleanup.
- Runtime tests: правильная composition, startup best effort, account summary и
  отсутствие storage roots у review repository.
- CLI tests: пакетные циклы, фиксированный cutoff, точный stdout и exit code.
- Architecture regression: `services/storage_cleanup*.py` не импортируют API или
  infrastructure; infrastructure repositories не импортируют старый процедурный
  cleanup API; review repository не запускает application cleanup.
- Существующие API integration tests продолжают фиксировать прежнее внешнее
  поведение.
- Обязательная итоговая команда: `make check`. Frontend не меняется, поэтому
  `make test-e2e` не требуется.

## Вне объёма

Изменение таблицы `storage_cleanup_jobs`, переименование legacy JSON-колонок,
удаление старых group/assignment/submission таблиц, новый dead-letter механизм,
экспоненциальный backoff, метрики/панель очереди, новые API endpoints, изменение
retention или upload grace period, объединение всех storage wrappers и изменения
frontend.

## Статус

Дизайн согласован пользователем по частям. Реализация не начата. План:
`docs/superpowers/plans/2026-09-06-storage-cleanup-service-boundary.md`.
