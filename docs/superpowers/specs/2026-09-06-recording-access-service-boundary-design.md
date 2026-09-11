# Граница сервиса доступа к записям

## Цель и согласованный объём

Убрать SQL, часы, чтение конфигурации владельца и правила авторизации из
api/controllers/recordings.py. Сохранить выдачу legacy-записей старых назначений,
review-записей и review-изображений без изменения URL, Range-ответов, хранилищ,
таблиц или пользовательского поведения.

Пользователь подтвердил, что старые записи должны оставаться доступными, и выбрал
отдельную read-only границу RecordingAccessService.

## Текущее поведение

- GET /api/recordings/{recording_id} выдаёт запись старого назначения ученику
  или связанному преподавателю. Запись submission в статусе uploading видит
  только ученик.
- GET /api/review-recordings/{recording_id} выдаёт непросроченную запись своему
  ученику. Подтверждённый преподаватель-владелец видит её только у заявок
  queued и reviewed.
- GET /api/review-assets/{asset_id} использует те же правила владельца и статуса,
  но у snapshot-изображений нет собственного срока хранения.
- Отсутствие строки, запрет доступа и истечение срока намеренно не различаются для
  клиента и возвращают 404.
- Controller сейчас выполняет три SQL-запроса, читает серверное время и получает
  owner email через API dependency.
- Route владеет Range-разбором и вызывает file_response; фактическое чтение local
  или S3/R2 storage не выполняется controller-ом.

## Рассмотренные подходы

### Отдельный read-only сервис доступа — выбран

Один RecordingAccessService и один RecordingAccessRepository обслуживают все
три GET-сценария. SQLite adapter владеет запросами, service — решениями о доступе,
controller — HTTP mapping. Решение не раздувает уже крупный изменяющий
ReviewRequestService и даёт одной небольшой границе единый смысл: безопасно
разрешить чтение сохранённого файла.

### Расширить ReviewRequestService и отделить legacy-сервис

Современные файлы можно добавить в ReviewRequestService, а старые записи вынести
в отдельный сервис. Предметные области формально разделены чище, но ради трёх
простых чтений появляются две composition factory, а существующий review service
получает ещё одну ответственность.

### Вынести только SQL

Repository helper сделал бы controller короче, но оставил бы там часы, owner
configuration и бизнес-правила доступа. Основная архитектурная проблема сохранилась
бы, поэтому этот вариант отклонён.

## Архитектура и контракты

~~~text
recordings route
  → transport-only recordings controller
    → RecordingAccessService
      → RecordingAccessRepository
        → SQLiteRecordingAccessRepository
~~~

### Port и модели

services/recording_access_repository.py определяет неизменяемые нейтральные
структуры:

- StoredFile(storage_key, mime_type, size_bytes);
- legacy record с файлом, status, student_id и teacher_id;
- review recording с файлом, status, student_id и expires_at;
- review asset с файлом, status и student_id.

RecordingAccessRepository предоставляет три точечных метода чтения по ID:
legacy_recording, review_recording и review_asset. Возвращается запись или None.
Port не импортирует API, SQLite, filesystem или storage.

### SQLite adapter

SQLiteRecordingAccessRepository(connect) содержит существующие SELECT/JOIN без
изменения схемы. Adapter фильтрует только по ID и возвращает все данные, необходимые
сервису. В частности, срок review-записи не скрывается SQL-условием: сравнение с
серверным временем является правилом сервиса и проверяется отдельно.

Каждый вызов открывает и закрывает соединение. Это read-only adapter: транзакций
записи, storage access и нормализации строк он не выполняет.

### Application service

RecordingAccessService(repository, *, owner_email, clock=time.time) предоставляет
три метода с ID файла и текущим actor. Actor содержит id, role, email и
email_verified; service не принимает API-dict.

Правила:

- legacy: actor.id должен совпадать с student_id или teacher_id старого назначения;
  при status == "uploading" доступ имеет только student_id; role и email для этого
  исторического правила не добавляются;
- review recording недоступна любому actor при expires_at <= int(clock()); до
  истечения срока собственный student имеет доступ;
- review asset: собственный student имеет доступ без отдельной проверки expiry;
- чужой review-файл доступен только actor с role teacher, подтверждённым email,
  нормализованным email владельца и status в queued или reviewed; для recording
  это правило применяется только после общей проверки срока;
- пустой owner email никому не даёт teacher-доступ;
- любое отсутствие или нарушение правила вызывает RecordingAccessError с
  причиной, соответствующей виду ресурса.

Сервис возвращает StoredFile. Он не читает файл, не знает о Range, FastAPI,
SQLite или storage backend.

### API и composition

Имена функций recording_get, review_recording_get и review_asset_get сохраняются.
Controller преобразует user dict в actor, вызывает
runtime.recording_access_service(), преобразует StoredFile в FileResult и
semantic errors в прежние ответы:

- legacy recording: 404, code not_found, message «Запись не найдена»;
- review recording: 404, code recording_not_found, та же message;
- review asset: 404, code asset_not_found, message «Изображение не найдено».

Неизвестные service errors не маскируются. Runtime собирает uncached service из
SQLiteRecordingAccessRepository(connect), config.owner_email() и часов сервиса,
без создания storage adapters.

Маршруты, require_authenticated, file_response, Range-заголовки,
runtime.AUDIO_DIR и runtime.REVIEW_ASSET_DIR не меняются.

## Ошибки и граничные случаи

- Ровно в момент expires_at == int(clock()) review-запись считается недоступной,
  как при прежнем SQL expires_at > now.
- Email сравнивается после trim/lower; существующий config.owner_email() уже
  возвращает нормализованное значение.
- Все запреты остаются 404, чтобы не раскрывать существование приватного файла.
- Ошибки базы, неверные сохранённые значения и storage failures не преобразуются
  в «не найдено» и продолжают подниматься как внутренние ошибки.
- Размер, MIME и storage key передаются без изменения.

## Проверка

- Service unit tests: legacy student/teacher/чужой actor, uploading; review student,
  подтверждённый owner teacher, неверная роль/email/verification/status; expiry до,
  после и ровно на границе; отсутствие строк и причины ошибок.
- SQLite integration: каждый JOIN возвращает точные метаданные и authorization
  fields; отсутствующие ID; review expiry читается без фильтрации; соединения
  закрываются; данные разных заявок не смешиваются.
- Controller unit: actor mapping, делегирование, FileResult, точные 404
  code/message и проброс неизвестных ошибок.
- Runtime unit: uncached composition без storage или mail dependencies.
- API characterization/regression: прежние URL, ученик и owner, запрет постороннему,
  статусы, expiry, legacy compatibility и существующие Range-сценарии.
- Architecture test: в recordings controller отсутствуют SQL, connect, часы,
  owner configuration, infrastructure и domain imports; service и port не зависят
  от API/infrastructure/SQLite.
- Обязательная итоговая проверка: make check. Frontend не меняется, поэтому
  дополнительный Playwright-прогон не требуется.

## Вне объёма

Удаление legacy endpoint или старых таблиц, миграция старых записей, изменение
retention, новый storage API, серверный proxy файлов, изменение Range-реализации,
объединение с личными записями, переработка upload/delete/cleanup workflows и
изменения frontend.

## Статус

Дизайн согласован пользователем по частям. Реализация не начата.
План реализации: docs/superpowers/plans/2026-09-06-recording-access-service-boundary.md.
