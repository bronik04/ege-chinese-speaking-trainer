# Review Request Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all review-request business orchestration and SQLite access out of the API controller while preserving every existing HTTP response, transaction guarantee, storage key, audit event, and concurrency outcome.

**Architecture:** Keep the eight public controller functions as transport adapters. Add a transport-independent `ReviewRequestService`, a single high-level repository/session port, and a SQLite adapter assembled by `trainer.api.runtime`. Refactor review-asset snapshotting to depend on a narrow registry port rather than a database connection.

**Tech Stack:** Python 3.12, FastAPI controller layer, Pydantic request schemas, SQLite, `typing.Protocol`, `unittest`, existing local/S3-compatible storage adapters.

**Spec:** `docs/superpowers/specs/2026-08-30-review-request-service-boundary-design.md`

## Global Constraints

- Preserve route signatures, Pydantic schemas, JSON fields, Russian messages, error codes, HTTP statuses, audit action names/details, storage keys, schema, and migrations.
- Do not change `legacy/`, frontend files, content, or unrelated controllers.
- `src/trainer/services/review_requests.py` must not import `trainer.api`, FastAPI, Starlette, Pydantic schemas, `sqlite3`, or database implementation modules.
- `src/trainer/services/review_request_repository.py` must not import `sqlite3` or expose a connection/cursor.
- Only `src/trainer/infrastructure/database/review_request_repository.py` owns review-request SQL and `BEGIN IMMEDIATE`.
- Add behavior through a failing test first. Read `superpowers:test-driven-development/writing-good-tests.md` before Task 1.
- Run the listed focused tests after each task and `make check` before completion. UI is unchanged, so `make test-e2e` is not required.

## Shared Types and Target Interfaces

The implementation may grow these protocols task by task, but the final public shape must be equivalent to the following. Keep structures immutable so tests compare state rather than mock call sequences.

```python
# src/trainer/services/review_request_repository.py
from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReviewActor:
    id: int
    email: str


@dataclass(frozen=True)
class RequestMetadata:
    client_ip: str
    user_agent: str


@dataclass(frozen=True)
class MaterialAsset:
    storage_key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class RequestItem:
    id: int
    task: int


@dataclass(frozen=True)
class UploadTarget:
    item_id: int
    status: str


@dataclass(frozen=True)
class RecordingRow:
    id: int
    storage_key: str


class ReviewAssetRegistry(Protocol):
    def material_asset(self, asset_id: int) -> MaterialAsset | None: ...
    def add_review_asset(
        self,
        request_id: int,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        created_at: int,
    ) -> int: ...
    def remove_review_asset(self, asset_id: int) -> None: ...


class ReviewRequestSession(ReviewAssetRegistry, Protocol):
    def published_material(self, slug: str) -> dict | None: ...
    def create_request(self, student_id: int, kind: str, variant_id: str, run_json: str) -> int: ...
    def add_item(self, request_id: int, task: int, snapshot_json: str) -> int: ...
    def upload_target(self, request_id: int, student_id: int, task: int) -> UploadTarget | None: ...
    def guard_uploading(self, request_id: int, student_id: int) -> bool: ...
    def recordings_at(self, item_id: int, question: int | None) -> list[RecordingRow]: ...
    def remove_recordings_at(self, item_id: int, question: int | None) -> None: ...
    def add_recording(self, *, item_id: int, question: int | None, label: str,
                      storage_key: str, mime_type: str, size_bytes: int,
                      duration_seconds: float, created_at: int, expires_at: int) -> int: ...
    def request_status(self, request_id: int, student_id: int) -> str | None: ...
    def request_items(self, request_id: int) -> list[RequestItem]: ...
    def uploaded_positions(self, request_id: int) -> set[tuple[int, int | None]]: ...
    def queue_request(self, request_id: int, student_id: int, submitted_at: int) -> bool: ...
    def request_storage_keys(self, request_id: int) -> tuple[list[str], list[str]]: ...
    def delete_request(self, request_id: int, student_id: int) -> bool: ...
    def scorable_items(self, request_id: int) -> list[RequestItem] | None: ...
    def save_item_scores(self, item_id: int, scores_json: str, total: int, maximum: int) -> None: ...
    def mark_reviewed(self, request_id: int, reviewer_id: int, reviewed_at: int) -> None: ...
    def enqueue_cleanup(self, *, audio_keys: Sequence[str], assignment_keys: Sequence[str]) -> None: ...
    def audit(self, action: str, *, actor: ReviewActor, metadata: RequestMetadata,
              details: Mapping[str, object]) -> None: ...


class ReviewRequestRepository(Protocol):
    def transaction(self, *, immediate: bool = False) -> AbstractContextManager[ReviewRequestSession]: ...
    def student_requests(self, student_id: int) -> list[dict]: ...
    def teacher_requests(self, *, student: str = "", task: int | None = None,
                         status: str = "", submitted_from: int | None = None,
                         submitted_before: int | None = None) -> list[dict]: ...
    def teacher_detail(self, request_id: int) -> dict | None: ...
    def enqueue_orphan_cleanup(self, *, audio_keys: Sequence[str],
                               assignment_keys: Sequence[str]) -> None: ...
    def process_cleanup(self) -> None: ...
```

The semantic service error must not carry HTTP knowledge:

```python
# src/trainer/services/review_requests.py
class ReviewRequestError(Exception):
    def __init__(self, reason: str, message: str = "", **details: object):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.details = details
```

Use these final reasons: `invalid_request`, `run_too_large`, `invalid_material`, `unsupported_media_type`, `recording_too_large`, `invalid_audio`, `not_found`, `not_uploading`, `incomplete`, and `invalid_scores`.

## Task 1: Define the Application Boundary and Semantic Errors

**Files:**

- Create: `src/trainer/services/review_request_repository.py`
- Create: `src/trainer/services/review_requests.py`
- Create: `tests/unit/test_review_request_service.py`

- [ ] **Step 1: Read the required good-test guidance**

Run:

```bash
sed -n '1,260p' /Users/bronik04/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/test-driven-development/writing-good-tests.md
```

- [ ] **Step 2: Write a failing service-boundary test**

Create `tests/unit/test_review_request_service.py` with a stateful fake repository and tests that establish two transport-independent contracts:

```python
class ReviewRequestServiceTest(unittest.TestCase):
    def test_student_list_hides_totals_until_reviewed(self):
        repository = FakeReviewRequestRepository(
            student_rows=[
                {"id": 1, "status": "uploading", "total": 4, "maximum": 7},
                {"id": 2, "status": "reviewed", "total": 6, "maximum": 7},
            ]
        )
        service = make_service(repository)

        rows = service.student_requests(17)

        self.assertNotIn("total", rows[0])
        self.assertNotIn("maximum", rows[0])
        self.assertEqual((rows[1]["total"], rows[1]["maximum"]), (6, 7))

    def test_error_is_semantic_and_keeps_details(self):
        error = ReviewRequestError("incomplete", missing=[{"task": 1, "question": 2}])
        self.assertEqual(error.reason, "incomplete")
        self.assertEqual(error.details, {"missing": [{"task": 1, "question": 2}]})
        self.assertFalse(hasattr(error, "status"))
```

The fake owns row state and returns deep copies; do not use `Mock` call assertions.

- [ ] **Step 3: Run the test to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
```

Expected: import failure because the service and repository modules do not exist.

- [ ] **Step 4: Implement the minimum port, service constructor, error, and read method**

Add the shared immutable structures and only the repository methods needed by the current tests. Implement `ReviewRequestService.student_requests()` by copying each row before removing totals; never mutate repository-owned dictionaries.

The constructor should establish all runtime dependencies now so later tasks do not introduce hidden globals:

```python
class ReviewRequestService:
    def __init__(self, repository: ReviewRequestRepository, *, project_root: Path,
                 audio_root: Path, material_asset_root: Path, review_asset_root: Path,
                 temporary_root: Path, max_audio_body: int,
                 duration_validator: Callable[[Path, int], float],
                 clock: Callable[[], float] = time.time):
        ...
```

- [ ] **Step 5: Run the focused test to verify GREEN**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
```

Expected: all new tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py tests/unit/test_review_request_service.py
git commit -m "refactor: define review request service boundary"
```

## Task 2: Move Read-Only Review Queries Behind the Repository

**Files:**

- Create: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/api/runtime.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_review_request_service.py`
- Create: `tests/integration/test_review_request_repository.py`
- Modify: `tests/integration/test_review_assets.py`

- [ ] **Step 1: Write failing service tests for teacher filters and missing detail**

Add tests asserting:

- query values already parsed by the controller reach `teacher_requests()` unchanged;
- `teacher_detail()` returns the repository dictionary;
- a missing detail raises `ReviewRequestError("not_found")`;
- repository-owned dictionaries remain unchanged.

- [ ] **Step 2: Write a failing SQLite adapter contract test**

Create a migrated temporary SQLite database, seed uploading/queued/reviewed rows, and assert that `SQLiteReviewRequestRepository` preserves the existing query contract:

```python
repository = SQLiteReviewRequestRepository(self.connect)
self.assertEqual({row["id"] for row in repository.student_requests(self.student_id)}, expected_ids)
self.assertEqual([row["id"] for row in repository.teacher_requests()], expected_teacher_order)
self.assertEqual(repository.teacher_detail(self.queued_id)["material"]["2"], expected_snapshot)
```

Move query-contract assertions from `ReviewRequestQueryTest` in `tests/integration/test_review_assets.py` into this repository-focused test. Keep asset-copy tests in `test_review_assets.py`.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
```

Expected: missing service/repository methods and adapter class.

- [ ] **Step 4: Implement the read adapter and service methods**

`SQLiteReviewRequestRepository` accepts a zero-argument connection factory. For each read, use `contextlib.closing(self._connect())`; delegate formatting to the existing functions in `trainer.infrastructure.database.queries.review_requests`.

Add service methods:

```python
def student_requests(self, student_id: int) -> list[dict]: ...
def teacher_requests(self, *, student: str = "", task: int | None = None,
                     status: str = "", submitted_from: int | None = None,
                     submitted_before: int | None = None) -> list[dict]: ...
def teacher_detail(self, request_id: int) -> dict: ...
```

- [ ] **Step 5: Add the runtime composition factory**

Add a non-cached factory so tests that patch runtime paths or `connect()` receive fresh dependencies:

```python
def review_request_service() -> ReviewRequestService:
    return ReviewRequestService(
        SQLiteReviewRequestRepository(connect, audio_root=AUDIO_DIR,
                                      material_root=MATERIAL_ASSET_DIR,
                                      review_asset_root=REVIEW_ASSET_DIR),
        project_root=ROOT,
        audio_root=AUDIO_DIR,
        material_asset_root=MATERIAL_ASSET_DIR,
        review_asset_root=REVIEW_ASSET_DIR,
        temporary_root=DATA_DIR / "tmp",
        max_audio_body=MAX_AUDIO_BODY,
        duration_validator=validate_duration,
    )
```

Import `validate_duration` in `runtime.py`; later API-flow tests will patch `runtime.validate_duration` instead of the controller module.

- [ ] **Step 6: Delegate only the three read controller functions**

Keep owner-only authorization and query parsing in the controller. Replace the database blocks with `runtime.review_request_service().student_requests(...)`, `.teacher_requests(...)`, and `.teacher_detail(...)`. Add the centralized `_service_error()` mapping needed for `not_found`; later tasks extend the mapping.

- [ ] **Step 7: Verify unit, adapter, and API contracts**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: all pass; list/detail response payloads and hidden owner behavior are unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/trainer/infrastructure/database/review_request_repository.py src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py src/trainer/api/runtime.py src/trainer/api/controllers/review_requests.py tests/unit/test_review_request_service.py tests/integration/test_review_request_repository.py tests/integration/test_review_assets.py
git commit -m "refactor: route review request reads through repository"
```

## Task 3: Move Request Creation and Asset Snapshot Registration

**Files:**

- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/services/review_assets.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_review_request_service.py`
- Modify: `tests/integration/test_review_request_repository.py`
- Modify: `tests/integration/test_review_assets.py`
- Modify: `tests/integration/test_api_flows.py`

- [ ] **Step 1: Write failing service create tests**

Extend the stateful fake session/repository and cover:

1. valid selection creates an `uploading` request, trimmed task snapshots, and `review_request_created` audit;
2. serialized `run` over 100,000 bytes raises `run_too_large` without state changes;
3. missing/published material mismatch raises `invalid_material`;
4. a snapshot storage failure rolls back fake database state and records every created assignment key for orphan cleanup.

Use an official material fixture for one test and a fake repository custom material for another. Assert resulting state, not method invocation counts.

- [ ] **Step 2: Write failing asset-registry tests**

Replace raw SQLite connections passed into `copy_review_assets()` with a small test registry implementing `ReviewAssetRegistry`. Assert:

- material assets are read through `material_asset()`;
- created snapshot URLs use ids returned by `add_review_asset()`;
- on a later copy failure, earlier registry rows and stored objects are removed;
- official public path containment and MIME rules remain unchanged.

Delete `copy_review_assets_from_env()`: service construction already provides the storage roots and public root, so a service helper must no longer import `trainer.api.runtime`.

- [ ] **Step 3: Run focused tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_assets.py' -v
```

Expected: new registry and create APIs are not implemented.

- [ ] **Step 4: Implement create orchestration in the service**

Add:

```python
def create(self, *, kind: str, tasks: Sequence[int], variant_id: str,
           run: object, actor: ReviewActor, metadata: RequestMetadata) -> dict:
    ...
```

The method must:

- call `validate_review_selection()` and convert `ValueError` to `invalid_request` with the original message;
- serialize `run` with `ensure_ascii=False, separators=(",", ":")` and enforce the existing 100,000-byte limit;
- resolve `official_detail(project_root, variant_id)` first, then `session.published_material(variant_id)`;
- verify all selected tasks, trim the material, create the request, snapshot assets, add task snapshot JSON, and audit within one ordinary transaction;
- on any exception after storage writes, call `repository.enqueue_orphan_cleanup(assignment_keys=...)`, attempt `repository.process_cleanup()` under `suppress(Exception)`, then re-raise the original semantic or unexpected exception.

- [ ] **Step 5: Implement the SQLite transaction/session adapter**

`SQLiteReviewRequestRepository.transaction(immediate=False)` must open a connection, optionally call `begin_immediate()`, yield a private `_SQLiteReviewRequestSession`, commit on success, rollback on failure, and always close.

Implement `published_material()` with the existing `material_payload(dict(row))`, request/item inserts, asset registry operations, audit delegation, and orphan cleanup persistence. SQL text and audit details must match the old controller exactly.

- [ ] **Step 6: Thin the create controller path**

Convert `user` and `RequestContext` to `ReviewActor`/`RequestMetadata`, call the service, and wrap the returned dictionary in `ActionResult(..., HTTPStatus.CREATED)`. Extend `_service_error()` mapping:

```python
"invalid_request" -> invalid_request / original message / 400
"run_too_large" -> invalid_request / "Данные попытки слишком велики" / 400
"invalid_material" -> invalid_review_material / "Материал не найден или не содержит выбранные задания" / 400
```

- [ ] **Step 7: Verify create and asset behavior**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_assets.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: create responses, snapshot bytes/URLs, audit rows, and rollback cleanup remain unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py src/trainer/services/review_assets.py src/trainer/infrastructure/database/review_request_repository.py src/trainer/api/controllers/review_requests.py tests/unit/test_review_request_service.py tests/integration/test_review_request_repository.py tests/integration/test_review_assets.py tests/integration/test_api_flows.py
git commit -m "refactor: move review request creation into service"
```

## Task 4: Move Recording Upload and Preserve Upload Races

**Files:**

- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_review_request_service.py`
- Modify: `tests/integration/test_review_request_repository.py`
- Modify: `tests/integration/test_api_flows.py`

- [ ] **Step 1: Write failing upload service tests**

Cover each semantic branch with a deterministic duration validator:

- invalid task/question produces `invalid_request` or `unsupported_media_type` matching the current distinction;
- unsupported MIME produces `unsupported_media_type`;
- empty/oversized body produces `recording_too_large`;
- validator `OSError`, `ValueError`, or `subprocess.SubprocessError` produces `invalid_audio` and removes the temp file;
- missing target produces `not_found`; non-uploading target produces `not_uploading`;
- success writes bytes, stores retention timestamps, replaces the same `(item, question)` recording, enqueues the old key, and audits;
- transaction failure after storage write enqueues the new key as an orphan and removes the temp file.

- [ ] **Step 2: Write failing real-adapter transaction tests**

Seed a request/item/recording. Assert that an immediate session:

- returns the current upload target;
- guarded status update fails after another transition;
- replaces only the same question slot;
- stores cleanup and audit in the same commit;
- rolls all database changes back when an exception escapes the context.

- [ ] **Step 3: Run focused tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
```

Expected: upload APIs are missing.

- [ ] **Step 4: Implement upload orchestration**

Add a transport-independent method receiving parsed scalar values and bytes:

```python
def upload_recording(self, *, request_id: int, task: int, question: int | None,
                     label: str, mime_type: str, body: bytes,
                     actor: ReviewActor, metadata: RequestMetadata) -> dict:
    ...
```

Generate the exact key prefix `review-requests/{request_id}/`, validate/write the temporary file, call the injected duration validator, then call `write_recording()`. Only after storage succeeds, enter `transaction(immediate=True)`, re-read target/status, call `guard_uploading()`, replace the recording, enqueue old keys, and audit. Always unlink the temporary file. On any post-write failure, persist cleanup for the new key, attempt cleanup processing under `suppress(Exception)`, and then re-raise.

- [ ] **Step 5: Delegate upload parsing from the controller**

Keep query integer parsing, label truncation, and `Content-Type` normalization in the controller. Pass parsed values to the service. Extend error mapping exactly:

```text
unsupported_media_type -> unsupported_media_type, "Неподдерживаемый формат аудио", 415
recording_too_large    -> request_too_large, "Запись превышает 15 МБ", 413
invalid_audio          -> validation_failed, "Некорректная или слишком длинная аудиозапись", 422
not_found              -> review_request_not_found, "Запрос не найден", 404
not_uploading          -> review_request_not_uploading, "Запрос уже отправлен", 409
```

Update `ApiFlowTest.setUpClass/tearDownClass` to patch `runtime.validate_duration`, because the controller no longer imports it. Replace the test-only call to `review_requests.process_cleanup_jobs(...)` with a direct import/call through `trainer.services.storage_cleanup`; the controller must not re-export cleanup infrastructure for tests.

- [ ] **Step 6: Preserve the concurrency seam without leaking SQL to the controller**

The existing upload-race tests patch `runtime.connect` and wrap the second upload connection. Keep the repository factory non-cached and make `transaction(immediate=True)` obtain its own fresh connection so these tests continue to interleave at the guarded transition. Adapt only SQL-string detection that moved from controller to adapter; do not weaken the asserted final state.

- [ ] **Step 7: Verify upload behavior and races**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: all upload, replacement, discard-vs-upload, and upload-vs-complete tests pass with the same final DB/storage state.

- [ ] **Step 8: Commit**

```bash
git add src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py src/trainer/infrastructure/database/review_request_repository.py src/trainer/api/controllers/review_requests.py tests/unit/test_review_request_service.py tests/integration/test_review_request_repository.py tests/integration/test_api_flows.py
git commit -m "refactor: move review recording uploads into service"
```

## Task 5: Move Complete and Discard State Transitions

**Files:**

- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_review_request_service.py`
- Modify: `tests/integration/test_review_request_repository.py`
- Modify: `tests/integration/test_api_flows.py`

- [ ] **Step 1: Write failing complete/discard service tests**

Cover:

- completing a missing or already-submitted request;
- exact sorted `missing` payload for task 1 questions and task 2/3 singleton positions;
- successful `uploading -> queued` transition, submitted timestamp, and audit;
- discard of missing/non-uploading request;
- successful discard collecting both audio and assignment keys, deleting state, queuing cleanup, auditing, and performing best-effort cleanup after commit;
- a cleanup processor failure does not undo a committed discard.

- [ ] **Step 2: Write failing adapter transition tests**

Use two real connections/threads or the existing interleaving wrapper to assert `BEGIN IMMEDIATE` and guarded updates serialize complete-vs-discard. The valid outcomes remain:

- exactly one transition wins;
- the loser receives `not_found` or `not_uploading` according to the committed state;
- no partially deleted request/items/recordings remain;
- cleanup job rows survive best-effort storage failure.

- [ ] **Step 3: Run focused tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
```

Expected: transition methods are missing.

- [ ] **Step 4: Implement service transitions**

Add:

```python
def complete(self, request_id: int, *, actor: ReviewActor, metadata: RequestMetadata) -> dict: ...
def discard(self, request_id: int, *, actor: ReviewActor, metadata: RequestMetadata) -> dict: ...
```

Both use `transaction(immediate=True)`. `complete()` computes `required_recording_positions(tasks)`, sorts by `(task, question or 0)`, raises `incomplete` with the existing payload, and uses a guarded queue update. `discard()` gathers keys, deletes the request, persists cleanup in the same transaction, then calls `repository.process_cleanup()` under `suppress(Exception)` after commit.

- [ ] **Step 5: Delegate controller functions and extend error mapping**

Map `incomplete` to `review_request_incomplete`, `"Загрузите все обязательные записи"`, 409, preserving the `missing` details. Existing `not_found` and `not_uploading` mappings are reused.

- [ ] **Step 6: Verify focused and API concurrency tests**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: complete/discard contracts and all existing race tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py src/trainer/infrastructure/database/review_request_repository.py src/trainer/api/controllers/review_requests.py tests/unit/test_review_request_service.py tests/integration/test_review_request_repository.py tests/integration/test_api_flows.py
git commit -m "refactor: move review request transitions into service"
```

## Task 6: Move Teacher Scoring into the Service

**Files:**

- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_review_request_service.py`
- Modify: `tests/integration/test_review_request_repository.py`
- Modify: `tests/integration/test_api_flows.py`

- [ ] **Step 1: Write failing scoring service tests**

Cover:

- missing/non-scorable request raises `not_found`;
- invalid criteria/tasks raises `invalid_scores` with the exact original `validate_scores()` message;
- success writes each task's compact `scores_json`, total/max values, marks the request reviewed with reviewer/time, and audits the existing details;
- both queued and previously reviewed requests can be scored, matching current behavior;
- a failure during one item update rolls back every score and status change.

- [ ] **Step 2: Write failing SQLite scoring transaction test**

Seed multiple items, perform scoring in an ordinary transaction, then verify the stored JSON, totals, reviewer, `reviewed_at`, and audit row. Add a rollback assertion using an exception between item updates.

- [ ] **Step 3: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
```

Expected: scoring methods are missing.

- [ ] **Step 4: Implement and delegate scoring**

Add:

```python
def score(self, request_id: int, scores_payload: Mapping[str, object], *,
          actor: ReviewActor, metadata: RequestMetadata) -> dict: ...
```

The service loads scorable items, calls `validate_scores()`, calculates per-task maxima from `CRITERIA`, persists all item scores/status/audit in one transaction, and returns the unchanged reviewed summary. The controller passes `payload.scores` and maps `invalid_scores` to `invalid_request`, the original message, 400.

- [ ] **Step 5: Verify scoring and full API flow**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: all pass and scoring response/database values are unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/trainer/services/review_request_repository.py src/trainer/services/review_requests.py src/trainer/infrastructure/database/review_request_repository.py src/trainer/api/controllers/review_requests.py tests/unit/test_review_request_service.py tests/integration/test_review_request_repository.py tests/integration/test_api_flows.py
git commit -m "refactor: move review request scoring into service"
```

## Task 7: Enforce the Boundary, Update Architecture Docs, and Verify

**Files:**

- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `docs/architecture.md`
- Modify: `docs/superpowers/specs/2026-08-30-review-request-service-boundary-design.md`
- Modify: `docs/superpowers/plans/2026-08-30-review-request-service-boundary.md`

- [ ] **Step 1: Write the architecture regression guard**

Add a controller-specific AST test:

```python
def test_review_request_controller_has_no_database_access(self):
    path = PACKAGE / "api" / "controllers" / "review_requests.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports = imported_modules(path.parent)  # use a file-local helper instead in final code
    direct_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    self.assertFalse(any(module.startswith("trainer.infrastructure.database") for module in file_imports(path)))
    self.assertNotIn("execute", direct_calls)
    self.assertNotIn("runtime.connect", source)
```

Add a `file_imports(path)` helper so the assertion inspects only this controller.

- [ ] **Step 2: Run the guard and inspect the boundary**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_architecture_boundaries.py' -v
```

Expected: GREEN if all prior vertical migrations removed their obsolete imports immediately. If it is RED, the failure must name a remaining transitional database import/call; remove that dependency in Step 3 without weakening the assertion.

- [ ] **Step 3: Remove remaining controller implementation knowledge**

The final controller may import only API/runtime/schema/result helpers, `HTTPStatus`, and the service boundary dataclasses/error. Remove obsolete JSON, secrets, subprocess, tempfile, time, path, grading, domain-rule, infrastructure, database-query, storage-cleanup, account-service, materials, recordings, and review-assets imports/helpers.

Keep all eight public function names/signatures and `_owner_allowed()`. Centralize error conversion in one helper. For unknown `ReviewRequestError.reason`, re-raise it rather than converting it into a misleading 400.

- [ ] **Step 4: Verify controller and service dependency directions**

Add assertions that:

- `services/review_requests.py` does not import `trainer.api` or `trainer.infrastructure.database`;
- `services/review_request_repository.py` does not import `sqlite3` or `trainer.infrastructure`;
- `infrastructure/database/review_request_repository.py` does not import `trainer.api`.

Run the architecture suite again and expect GREEN.

- [ ] **Step 5: Update architecture documentation**

In `docs/architecture.md`, document the completed vertical slice:

```text
review_requests controller -> ReviewRequestService -> ReviewRequestRepository port
                                               -> SQLiteReviewRequestRepository
```

State that other controllers remain transitional and that this change does not introduce a general DI framework. Mark every implementation-plan checkbox complete only after its command has passed, and append a short `## Implementation outcome` section to the design spec with final module names and verification counts.

- [ ] **Step 6: Run formatting/static checks and focused suites**

Run:

```bash
.venv/bin/ruff check src/trainer/api/controllers/review_requests.py src/trainer/api/runtime.py src/trainer/services/review_requests.py src/trainer/services/review_request_repository.py src/trainer/services/review_assets.py src/trainer/infrastructure/database/review_request_repository.py tests/unit/test_review_request_service.py tests/unit/test_architecture_boundaries.py tests/integration/test_review_request_repository.py tests/integration/test_review_assets.py tests/integration/test_api_flows.py
.venv/bin/ruff format --check src/trainer/api/controllers/review_requests.py src/trainer/api/runtime.py src/trainer/services/review_requests.py src/trainer/services/review_request_repository.py src/trainer/services/review_assets.py src/trainer/infrastructure/database/review_request_repository.py tests/unit/test_review_request_service.py tests/unit/test_architecture_boundaries.py tests/integration/test_review_request_repository.py tests/integration/test_review_assets.py tests/integration/test_api_flows.py
.venv/bin/python -m unittest discover -s tests/unit -p 'test_review_request_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_review_request_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_api_flows.py' -v
```

Expected: every command succeeds.

- [ ] **Step 7: Run mandatory full verification**

Run:

```bash
make check
```

Expected: JavaScript, Python unit/integration, lint, formatting, and coverage checks all pass with coverage at or above the repository threshold.

- [ ] **Step 8: Review the diff and commit**

Run:

```bash
git status --short
git diff --check
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Confirm there are no schema, migration, route, frontend, content, or legacy changes. Then commit:

```bash
git add src/trainer/api/controllers/review_requests.py tests/unit/test_architecture_boundaries.py docs/architecture.md docs/superpowers/specs/2026-08-30-review-request-service-boundary-design.md docs/superpowers/plans/2026-08-30-review-request-service-boundary.md
git commit -m "docs: record review request service boundary"
```

- [ ] **Step 9: Apply completion workflow**

Use `superpowers:verification-before-completion`, then `superpowers:requesting-code-review`, and finally `superpowers:finishing-a-development-branch`. Do not merge, push, or remove the worktree without the user's explicit choice in the finishing workflow.

## Implementation Outcome

All seven tasks were executed sequentially in the isolated `codex/review-request-boundary` worktree. The final
boundary matches the target interfaces, all focused service/repository/asset/API concurrency suites pass, and
`make check` passes with 18 JavaScript unit tests, 131 Python unit tests, 95 Python integration tests, and 88%
coverage. The checkboxes above remain the reusable execution recipe; this section records the completed run.
