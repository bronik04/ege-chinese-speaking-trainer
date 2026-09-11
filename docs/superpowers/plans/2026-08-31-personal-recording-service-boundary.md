# План внедрения PersonalRecordingService

**Цель:** убрать SQLite, storage, ffprobe и temporary-file orchestration из personal-recordings controller,
сохранив публичное поведение и durable cleanup protocol.

**Спецификация:**
`docs/superpowers/specs/2026-08-31-personal-recording-service-boundary-design.md`.

## Инварианты

- Не менять routes, schemas, DB schema и retention policy.
- Cleanup intent commit-ится до storage put.
- Metadata insert и intent delete атомарны.
- Service/port не импортируют API, infrastructure или sqlite3.
- Controller не открывает БД, не создаёт файлы и не выбирает storage.
- Новое публичное поведение добавляется только вместе с тестом.

## Task 1. Ports и service core

**Файлы:**

- создать `src/trainer/services/personal_recording_repository.py`;
- переписать `src/trainer/services/personal_recordings.py`;
- создать `tests/unit/test_personal_recording_service.py`;
- расширить `tests/unit/test_architecture_boundaries.py`.

Сначала добавить failing tests для validation, успешного порядка
`intent → put → finalize`, сохранения intent при storage/finalize failure, удаления temporary file, list/file
ownership contracts. Затем реализовать минимальный service и ports.

Проверка:

```bash
PYTHONPATH=src ../../.venv/bin/python -m unittest \
  tests.unit.test_personal_recording_service \
  tests.unit.test_architecture_boundaries -v
```

Коммит: `refactor: define personal recording service boundary`.

## Task 2. SQLite repository

**Файлы:**

- создать `src/trainer/infrastructure/database/personal_recording_repository.py`;
- создать `tests/integration/test_personal_recording_repository.py`.

Через real SQLite проверить:

- отдельный commit upload intent;
- finalize insert + intent delete;
- rollback обоих действий при сбое;
- adapter-neutral conflict;
- owner/expiry filtering и public field mapping.

Проверка:

```bash
PYTHONPATH=src ../../.venv/bin/python -m unittest \
  tests.integration.test_personal_recording_repository -v
```

Коммит: `feat: add sqlite personal recording repository`.

## Task 3. Duration adapter и runtime composition

**Файлы:**

- изменить `src/trainer/infrastructure/audio.py`;
- изменить `src/trainer/api/runtime.py`;
- добавить/изменить `tests/unit/test_application_services.py`;
- добавить adapter test при необходимости.

Добавить runtime factory без cache, передающий repository, configured audio storage, temp root, body limit,
grace period и duration adapter. Expected media errors переводить в port exception.

Коммит: `feat: compose personal recording service runtime`.

## Task 4. Controller cutover

**Файлы:**

- переписать `src/trainer/api/controllers/personal_recordings.py`;
- создать `tests/unit/test_personal_recording_controller.py`;
- обновить `tests/integration/test_api_flows.py` patch seams;
- удалить legacy SQL helpers из `src/trainer/services/personal_recordings.py`.

Controller сохраняет три сигнатуры, формирует service data и переводит semantic errors в прежние `ApiError`.
Добавить table-driven error mapping и delegation tests. Перенести integration patches на runtime composition или
adapter seams.

Проверка:

```bash
PYTHONPATH=src ../../.venv/bin/python -m unittest \
  tests.unit.test_personal_recording_controller \
  tests.unit.test_personal_recording_service \
  tests.unit.test_architecture_boundaries \
  tests.integration.test_personal_recording_repository \
  tests.integration.test_api_flows.ApiFlowTest.test_personal_recordings_are_private_owner_bound_and_expire \
  tests.integration.test_api_flows.ApiFlowTest.test_personal_recording_has_durable_cleanup_intent_before_storage_write \
  tests.integration.test_api_flows.ApiFlowTest.test_personal_recording_upload_intent_is_not_processed_while_metadata_is_committing \
  tests.integration.test_api_flows.ApiFlowTest.test_personal_recording_removes_temporary_file_when_cleanup_intent_fails -v
```

Коммит: `refactor: delegate personal recording api to service`.

## Task 5. Документация, ревью и verification

- добавить personal-recording boundary в `docs/architecture.md`;
- выполнить structural searches для запрещённых imports/calls;
- запустить профильный набор повторно;
- запустить `make check` через основной venv и `PYTHONPATH=src`;
- провести независимое read-only code review транзакций, cleanup race, privacy, HTTP mapping и token/key secrecy;
- исправлять actionable findings только через regression test;
- повторить `make check` после последнего коммита.

Финальная проверка:

```bash
PYTHONPATH=src make check PYTHON=../../.venv/bin/python
git status --short --branch
```

Коммит документации: `docs: document personal recording boundary`.

