# Граница PersonalRecordingService

## Проблема

`src/trainer/api/controllers/personal_recordings.py` одновременно выполняет transport-адаптацию, проверяет
аудио, создаёт временный файл, открывает SQLite, ставит durable cleanup intent, выбирает storage и завершает
запись метаданных. `src/trainer/services/personal_recordings.py` при этом является набором SQL-функций и зависит
от конкретной SQLite-транзакции. Из-за этого controller нельзя изолированно тестировать, а критичный порядок
`cleanup intent → storage put → metadata commit` распределён между API и псевдосервисом.

## Цель

Выделить transport- и adapter-независимый `PersonalRecordingService`, сохранив без изменений:

- три публичных маршрута, payloads, статусы и коды ошибок;
- приватность записей и проверку владельца;
- ограничение одной позиции для заданий 2 и 3;
- MIME- и size-проверки, длительность и retention;
- durable cleanup intent до первой записи в storage;
- grace period, не позволяющий cleanup удалить объект до metadata commit;
- атомарность создания metadata и удаления cleanup intent;
- удаление временного файла при любом исходе.

Схема БД, миграции, frontend и storage cleanup processor не меняются.

## Граница

```text
personal-recordings route
  → transport-only controller
    → PersonalRecordingService
      → PersonalRecordingRepository port
      → PersonalRecordingStorage port
      → duration validator callable

runtime
  → SQLitePersonalRecordingRepository
  → configured local/S3 storage
  → ffprobe duration adapter
```

### Service

`src/trainer/services/personal_recordings.py` содержит:

- `PersonalRecordingService`;
- semantic `PersonalRecordingError`;
- проверки позиции, MIME и размера;
- создание и гарантированное удаление временного файла;
- генерацию private storage key;
- оркестрацию upload intent, storage put и metadata finalize;
- преобразование repository records в публичные dictionaries.

Service не импортирует `trainer.api`, `trainer.infrastructure`, `sqlite3` или HTTP-типы.

### Ports

`src/trainer/services/personal_recording_repository.py` определяет immutable records и узкие интерфейсы:

- `create_upload_intent(storage_key, now, available_at) -> int`;
- `finalize_recording(data, cleanup_job_id, now) -> record`;
- `recordings(student_id, now) -> list[record]`;
- `recording_file(recording_id, student_id, now) -> access | None`;
- storage `put(key, source, content_type)`;
- adapter-neutral `PersonalRecordingConflictError` и `PersonalRecordingAudioError`.

Ни connection, ни cursor через port не передаются.

### SQLite adapter

`src/trainer/infrastructure/database/personal_recording_repository.py` владеет всем SQL:

- upload intent создаётся и commit-ится отдельной транзакцией до storage put;
- finalize начинает immediate transaction, вставляет metadata и удаляет cleanup job в одной транзакции;
- любой сбой finalize откатывает и metadata, и удаление intent;
- uniqueness violation переводится в `PersonalRecordingConflictError`;
- reads закрывают connection и фильтруют owner/expiry в SQL.

### Audio и storage

Runtime передаёт storage object из существующего `storage_from_env(AUDIO_DIR)`. FFprobe adapter переводит
ожидаемые ошибки чтения/формата/процесса в `PersonalRecordingAudioError`; неожиданные ошибки не маскируются.

## Порядок создания

1. Service проверяет position, MIME и размер до файловых или database side effects.
2. Body записывается во временный файл под `var/tmp`.
3. Duration adapter проверяет запись.
4. Service генерирует private key и просит repository commit-нуть cleanup intent с grace period.
5. Storage сохраняет объект.
6. Repository в immediate transaction создаёт metadata и удаляет intent.
7. Service удаляет temporary file в `finally`.

Если шаг 5 или 6 падает, intent остаётся и storage cleanup повторно удалит объект после grace period. Если шаг
4 падает, storage ещё не вызывался. При conflict публичный ответ остаётся `409 personal_recording_exists`.

## HTTP mapping

Controller переводит только `PersonalRecordingError`:

| reason | status | API code |
|---|---:|---|
| `invalid_position` | 400 | `invalid_request` |
| `unsupported_audio` | 415 | `unsupported_media_type` |
| `audio_too_large` | 413 | `request_too_large` |
| `invalid_audio` | 422 | `validation_failed` |
| `recording_exists` | 409 | `personal_recording_exists` |
| `recording_not_found` | 404 | `recording_not_found` |

## Проверки

- Stateful fake unit-тестирует порядок side effects, validation и public records.
- SQLite integration-тесты фиксируют commit/rollback upload intent и finalize, uniqueness, owner/expiry reads.
- Controller unit-тесты фиксируют delegation и error mapping.
- Архитектурные тесты запрещают API/infrastructure imports в service/port и SQL/filesystem orchestration в
  controller.
- Существующие HTTP-flow тесты подтверждают полную обратную совместимость.

