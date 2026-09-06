# Storage Cleanup Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the procedural SQLite-coupled cleanup module with a `StorageCleanupService`, a neutral repository port and a transaction-safe SQLite adapter without changing public behavior.

**Architecture:** `StorageCleanupService` owns time, leases, retry policy and storage deletion through injected factories. `SQLiteStorageCleanupRepository` owns SQL, JSON and short transactions; `SQLiteStorageCleanupQueue` lets account, review and personal repositories enqueue or cancel work on their existing transaction. Runtime composes the boundary for startup, account, review and CLI entry points.

**Tech Stack:** Existing Python, FastAPI runtime composition, SQLite, unittest, dataclasses and typing Protocol; no new dependencies and no database migration.

**Spec:** docs/superpowers/specs/2026-09-06-storage-cleanup-service-boundary-design.md

## Global Constraints

- Remove the public functions `expire_recordings`, `enqueue_cleanup_job`, `process_cleanup_jobs` and `account_review_storage_keys` after every caller has migrated.
- Preserve atomic cleanup intent creation for account deletion, review replacement/discard, personal upload intent and recording expiry.
- Preserve the `storage_cleanup_jobs` schema and the physical column name `assignment_keys_json`; do not add or edit a migration.
- Preserve key filtering, stable deduplication, expiry ordering across personal/review tables and existing batch limits.
- Use a one-hour lease and a one-hour retry delay. A stale worker may not finish a job claimed by a newer worker.
- Treat `FileNotFoundError` as success; attempt every key; retain the first other error as `TypeName: message`.
- Preserve startup, review and account best-effort behavior and current log event names.
- Preserve CLI stdout exactly as `expired=X completed=Y failed=Z pending=P` and return nonzero when failed or pending is nonzero.
- Move `UPLOAD_INTENT_GRACE_SECONDS` to the personal-recording service without changing its one-hour value.
- Preserve HTTP routes, schemas, responses, retention, storage keys, local/S3/R2 behavior and frontend.
- Use test-first RED/GREEN cycles. Run fresh `make check` before completion. UI is unchanged, so `make test-e2e` is not required.
- Preserve the user's untracked `.superpowers/brainstorm/` and unrelated worktrees. Execute in an isolated worktree at implementation time.

---

## File Map

- Create `src/trainer/services/storage_cleanup_repository.py`: neutral queue records and repository port.
- Rewrite `src/trainer/services/storage_cleanup.py`: application orchestration only.
- Create `src/trainer/infrastructure/database/storage_cleanup_repository.py`: SQLite queue, expiry, claim and outcome persistence.
- Modify `src/trainer/infrastructure/database/account_repository.py`: collect all account keys locally and enqueue transactionally.
- Modify `src/trainer/infrastructure/database/personal_recording_repository.py`: create and cancel intents through the SQLite queue.
- Modify `src/trainer/infrastructure/database/review_request_repository.py`: enqueue through the SQLite queue and stop processing cleanup.
- Modify `src/trainer/services/review_request_repository.py`: add explicit cleanup timestamps and remove `process_cleanup`.
- Modify `src/trainer/services/review_requests.py`: inject the best-effort cleanup callback and pass its clock to producers.
- Modify `src/trainer/services/personal_recordings.py`: own the upload-intent grace constant.
- Modify `src/trainer/api/runtime.py`: compose the cleanup service and migrate all runtime callers.
- Modify `scripts/cleanup_storage.py`: batch through the service rather than a raw database connection.
- Create `tests/unit/test_storage_cleanup_service.py`: pure service behavior.
- Create `tests/integration/test_storage_cleanup_repository.py`: real SQLite queue, expiry and lease behavior.
- Modify producer, runtime, CLI, API-flow and architecture tests listed in the tasks below.
- Modify `docs/architecture.md`: document the cleanup boundary and update review/account descriptions.

## Task 1: Neutral Port and Application Service

**Files:**
- Create: `src/trainer/services/storage_cleanup_repository.py`
- Modify: `src/trainer/services/storage_cleanup.py`
- Create: `tests/unit/test_storage_cleanup_service.py`

**Interfaces:**
- Produces `CleanupKeys(audio=(), material=(), assignment=())`.
- Produces `ClaimedCleanupJob(id, keys, lease_until, error=None)` and `CleanupOutcome(job_id, error=None)`.
- Produces `CleanupBatchResult(completed=0, failed=0, pending=0)`.
- Produces `StorageCleanupRepository.expire_recordings`, `claim_jobs`, `finish_jobs` and `pending_jobs`.
- Produces `StorageCleanupService.expire_batch(*, limit=500, now=None)` and `process_batch(*, limit=50, now=None)`.
- Temporarily retains the old free functions at the bottom of `storage_cleanup.py` so the repository stays green until Task 6 removes them.

- [x] **Step 1: Write failing service tests**

Create `tests/unit/test_storage_cleanup_service.py` with a fake repository and literal storage adapters. Cover expiry delegation, lazy factories, all three categories, missing files, first failure, decode errors, retry/lease timestamps and empty ready batches:

~~~python
import unittest
from unittest.mock import Mock

from trainer.services.storage_cleanup import CleanupSummary, StorageCleanupService
from trainer.services.storage_cleanup_repository import (
    ClaimedCleanupJob,
    CleanupBatchResult,
    CleanupKeys,
)


class RecordingStorage:
    def __init__(self, failures=()):
        self.deleted = []
        self.failures = set(failures)

    def delete(self, key):
        self.deleted.append(key)
        if key == "missing":
            raise FileNotFoundError(key)
        if key in self.failures:
            raise OSError(f"cannot delete {key}")


class StorageCleanupServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.repository.claim_jobs.return_value = []
        self.repository.pending_jobs.return_value = 0
        self.audio = RecordingStorage()
        self.material = RecordingStorage()
        self.assignment = RecordingStorage()
        self.service = StorageCleanupService(
            self.repository,
            audio_storage=lambda: self.audio,
            material_storage=lambda: self.material,
            assignment_storage=lambda: self.assignment,
            clock=lambda: 100,
        )

    def test_expire_batch_delegates_normalized_limit_and_time(self):
        self.repository.expire_recordings.return_value = 2
        self.assertEqual(self.service.expire_batch(limit=-1, now=90), 2)
        self.repository.expire_recordings.assert_called_once_with(now=90, limit=0)

    def test_processes_all_categories_and_treats_missing_as_success(self):
        self.repository.claim_jobs.return_value = [
            ClaimedCleanupJob(
                7,
                CleanupKeys(("audio", "missing"), ("material",), ("assignment",)),
                3700,
            )
        ]
        self.repository.finish_jobs.return_value = CleanupBatchResult(completed=1)

        self.assertEqual(self.service.process_batch(), CleanupSummary(completed=1))
        self.assertEqual(self.audio.deleted, ["audio", "missing"])
        self.assertEqual(self.material.deleted, ["material"])
        self.assertEqual(self.assignment.deleted, ["assignment"])
        outcome = self.repository.finish_jobs.call_args.args[0][0]
        self.assertIsNone(outcome.error)

    def test_attempts_every_key_and_records_only_first_failure(self):
        self.audio.failures = {"first", "second"}
        self.repository.claim_jobs.return_value = [
            ClaimedCleanupJob(8, CleanupKeys(audio=("first", "second", "last")), 3700)
        ]
        self.repository.finish_jobs.return_value = CleanupBatchResult(failed=1, pending=1)

        summary = self.service.process_batch()

        self.assertEqual(summary, CleanupSummary(failed=1, pending=1))
        self.assertEqual(self.audio.deleted, ["first", "second", "last"])
        outcome = self.repository.finish_jobs.call_args.args[0][0]
        self.assertEqual(outcome.error, "OSError: cannot delete first")

    def test_decode_error_skips_storage_and_empty_batch_reports_pending(self):
        self.repository.claim_jobs.return_value = [
            ClaimedCleanupJob(9, CleanupKeys(), 3700, "ValueError: invalid cleanup payload")
        ]
        self.repository.finish_jobs.return_value = CleanupBatchResult(failed=1, pending=2)
        self.assertEqual(self.service.process_batch(), CleanupSummary(failed=1, pending=2))
        self.assertEqual(self.repository.finish_jobs.call_args.args[0][0].error, "ValueError: invalid cleanup payload")

        self.repository.reset_mock()
        self.repository.claim_jobs.return_value = []
        self.repository.pending_jobs.return_value = 3
        self.assertEqual(self.service.process_batch(now=200), CleanupSummary(pending=3))
~~

- [x] **Step 2: Run the new tests to observe RED**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_storage_cleanup_service -v
~~~

Expected: import failures for `StorageCleanupService` and the repository models.

- [x] **Step 3: Define the port and value objects**

Create `src/trainer/services/storage_cleanup_repository.py`:

~~~python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CleanupKeys:
    audio: tuple[str, ...] = ()
    material: tuple[str, ...] = ()
    assignment: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimedCleanupJob:
    id: int
    keys: CleanupKeys
    lease_until: int
    error: str | None = None


@dataclass(frozen=True)
class CleanupOutcome:
    job_id: int
    error: str | None = None


@dataclass(frozen=True)
class CleanupBatchResult:
    completed: int = 0
    failed: int = 0
    pending: int = 0


class StorageCleanupRepository(Protocol):
    def expire_recordings(self, *, now: int, limit: int) -> int: ...
    def claim_jobs(self, *, now: int, lease_until: int, limit: int) -> list[ClaimedCleanupJob]: ...
    def finish_jobs(
        self,
        outcomes: Sequence[CleanupOutcome],
        *,
        lease_until: int,
        now: int,
        retry_at: int,
    ) -> CleanupBatchResult: ...
    def pending_jobs(self) -> int: ...
~~~

- [x] **Step 4: Add the service without removing the legacy functions yet**

At the top of `src/trainer/services/storage_cleanup.py`, define `CleanupStorage`, `StorageFactory`, `CleanupSummary` and `StorageCleanupService`. Use `moment = int(self._clock()) if now is None else int(now)`, `maximum = max(0, int(limit))`, `lease_until = moment + self._lease_seconds` and `retry_at = moment + self._retry_delay_seconds`. Cache one factory result or factory exception per category for the whole batch. Convert `CleanupBatchResult` to the public `CleanupSummary`.

Use one resolver cache for the batch:

~~~python
resolved: dict[StorageFactory, CleanupStorage | Exception] = {}

def resolved_storage(factory: StorageFactory) -> CleanupStorage:
    if factory not in resolved:
        try:
            resolved[factory] = factory()
        except Exception as error:
            resolved[factory] = error
    value = resolved[factory]
    if isinstance(value, Exception):
        raise value
    return value
~~~

The deletion loop must have this shape so it continues after failures:

~~~python
failures: list[Exception] = []
for factory, keys in categories:
    if not keys:
        continue
    try:
        storage = resolved_storage(factory)
    except Exception as error:
        failures.append(error)
        continue
    for key in keys:
        try:
            storage.delete(key)
        except FileNotFoundError:
            continue
        except Exception as error:
            failures.append(error)
error_text = f"{type(failures[0]).__name__}: {failures[0]}" if failures else None
~~~

When `ClaimedCleanupJob.error` is present, do not resolve any storage; emit that error directly. Call:

~~~python
result = self._repository.finish_jobs(
    outcomes,
    lease_until=lease_until,
    now=moment,
    retry_at=moment + self._retry_delay_seconds,
)
~~~

- [x] **Step 5: Run service tests and the existing cleanup tests**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_storage_cleanup_service \
  tests.unit.test_application_services -v
~~~

Expected: PASS; existing callers still use the temporarily retained functions.

- [x] **Step 6: Commit the service contract**

~~~bash
git add src/trainer/services/storage_cleanup.py \
  src/trainer/services/storage_cleanup_repository.py \
  tests/unit/test_storage_cleanup_service.py
git commit -m "refactor: define storage cleanup service"
~~~

## Task 2: SQLite Cleanup Adapter and Lease Semantics

**Files:**
- Create: `src/trainer/infrastructure/database/storage_cleanup_repository.py`
- Create: `tests/integration/test_storage_cleanup_repository.py`

**Interfaces:**
- Consumes the Task 1 models and `StorageCleanupRepository` signatures.
- Produces `SQLiteStorageCleanupQueue(database).enqueue(keys, *, now, available_at=None) -> int`.
- Produces `SQLiteStorageCleanupQueue(database).cancel(job_id) -> bool`.
- Produces `SQLiteStorageCleanupRepository(connect_factory)` implementing expiry, claim, finish and pending operations.

- [x] **Step 1: Write queue and expiry integration tests**

Create a temporary migrated SQLite database in `tests/integration/test_storage_cleanup_repository.py`. Add tests that:

~~~python
queue = SQLiteStorageCleanupQueue(database)
job_id = queue.enqueue(
    CleanupKeys(("audio", "audio", ""), ("material",), ("assignment",)),
    now=100,
    available_at=200,
)
row = database.execute(
    "SELECT audio_keys_json,material_keys_json,assignment_keys_json,created_at,available_at "
    "FROM storage_cleanup_jobs WHERE id=?",
    (job_id,),
).fetchone()
self.assertEqual(json.loads(row["audio_keys_json"]), ["audio"])
self.assertEqual((row["created_at"], row["available_at"]), (100, 200))
self.assertTrue(queue.cancel(job_id))
self.assertFalse(queue.cancel(job_id))
~~~

Also seed one personal and one review recording with the same key. Assert `expire_recordings(now=10, limit=2)` removes both rows and enqueues one deduplicated audio key. Patch `SQLiteStorageCleanupQueue.enqueue` to raise and assert both metadata deletes roll back.

- [x] **Step 2: Write lease, malformed payload and stale outcome tests**

Enqueue two ready jobs and assert:

~~~python
first = repository.claim_jobs(now=100, lease_until=3700, limit=1)
self.assertEqual([job.id for job in first], [first_job_id])
self.assertEqual(repository.claim_jobs(now=100, lease_until=3700, limit=10)[0].id, second_job_id)
self.assertEqual(repository.claim_jobs(now=101, lease_until=3701, limit=10), [])
reclaimed = repository.claim_jobs(now=3700, lease_until=7300, limit=10)
self.assertEqual({job.id for job in reclaimed}, {first_job_id, second_job_id})
~~~

Finish the stale first claim with `lease_until=3700` after reclaim and assert it applies zero completed/failed and leaves the row. Finish the newer claim with `lease_until=7300` and assert it removes the row. Insert invalid JSON manually, claim it, and assert the returned job contains a `ValueError:` error instead of raising.

- [x] **Step 3: Run adapter tests to observe RED**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_storage_cleanup_repository -v
~~~

Expected: import failure because the SQLite adapter does not exist.

- [x] **Step 4: Implement the transaction-local queue**

In `src/trainer/infrastructure/database/storage_cleanup_repository.py`, add stable filtering and strict decoding:

~~~python
def _keys(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def _decode(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
        raise ValueError("invalid cleanup payload")
    return _keys(decoded)
~~~

`enqueue` inserts the three JSON arrays, `attempts=0`, `created_at=updated_at=now`, and `available_at=now` unless explicitly supplied. `cancel` deletes by ID and returns `rowcount == 1`. Neither method commits or rolls back.

- [x] **Step 5: Implement repository expiry and claim**

Use `closing(self._connect())`, `begin_immediate(database)`, explicit commit/rollback and the existing union query/order from the legacy function. `expire_recordings` uses `SQLiteStorageCleanupQueue(database).enqueue(...)` before commit.

For `claim_jobs`, select ready rows ordered by `available_at,id`, update every selected row with:

~~~sql
UPDATE storage_cleanup_jobs
SET available_at=?, updated_at=?
WHERE id=? AND available_at<=?
~~~

Commit before decoding. Decode every selected row independently; convert decode exceptions to `ClaimedCleanupJob(..., error="TypeName: message")`.

- [x] **Step 6: Implement outcome persistence and pending count**

Under `BEGIN IMMEDIATE`, process each outcome with lease ownership:

~~~sql
DELETE FROM storage_cleanup_jobs WHERE id=? AND available_at=?
~~~

or:

~~~sql
UPDATE storage_cleanup_jobs
SET attempts=attempts+1,last_error=?,updated_at=?,available_at=?
WHERE id=? AND available_at=?
~~~

Count completed/failed only when `rowcount == 1`, then read total pending and commit. `pending_jobs` performs a read-only count on its own connection.

- [x] **Step 7: Run adapter, service and migration tests**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.integration.test_storage_cleanup_repository \
  tests.unit.test_storage_cleanup_service \
  tests.integration.test_migrations -v
~~~

Expected: PASS, including the two-worker lease regression and clean/update migration coverage.

- [x] **Step 8: Commit the SQLite adapter**

~~~bash
git add src/trainer/infrastructure/database/storage_cleanup_repository.py \
  tests/integration/test_storage_cleanup_repository.py
git commit -m "refactor: add sqlite storage cleanup repository"
~~~

## Task 3: Account and Personal Cleanup Producers

**Files:**
- Modify: `src/trainer/infrastructure/database/account_repository.py`
- Modify: `src/trainer/infrastructure/database/personal_recording_repository.py`
- Modify: `src/trainer/services/personal_recordings.py`
- Modify: `tests/integration/test_account_repository.py`
- Modify: `tests/integration/test_personal_recording_repository.py`
- Modify: `tests/unit/test_personal_recording_service.py`

**Interfaces:**
- Consumes `CleanupKeys` and `SQLiteStorageCleanupQueue` from Tasks 1–2.
- Preserves `AccountRepositorySession.enqueue_account_cleanup(user_id, now)`.
- Preserves `PersonalRecordingRepository.create_upload_intent` and `finalize_recording`.
- Produces `trainer.services.personal_recordings.UPLOAD_INTENT_GRACE_SECONDS = 60 * 60`.

- [x] **Step 1: Strengthen producer transaction tests**

In `tests/integration/test_account_repository.py`, retain the existing all-key assertion and add a failure after `enqueue_account_cleanup` followed by rollback; verify both the user and pre-existing file metadata remain and `storage_cleanup_jobs` stays empty.

In `tests/integration/test_personal_recording_repository.py`, keep the existing committed intent, atomic finalize, missing-intent rollback and conflict-retains-intent cases. Patch `SQLiteStorageCleanupQueue.enqueue` to raise and assert `create_upload_intent` leaves no job. Patch `cancel` to return false and assert metadata insertion rolls back with `PersonalRecordingIntentError`.

- [x] **Step 2: Run producer tests as characterization**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.integration.test_account_repository \
  tests.integration.test_personal_recording_repository -v
~~~

Expected: the new patched-class assertions fail because both repositories still call the legacy function or direct SQL.

- [x] **Step 3: Migrate account cleanup key collection**

Replace the import from `trainer.services.storage_cleanup` with:

~~~python
from trainer.infrastructure.database.storage_cleanup_repository import SQLiteStorageCleanupQueue
from trainer.services.storage_cleanup_repository import CleanupKeys
~~~

Move the review recording, review asset and personal recording SELECTs into `enqueue_account_cleanup` next to the existing legacy/material/assignment queries. Build stable ordered tuples and call:

~~~python
SQLiteStorageCleanupQueue(self.database).enqueue(
    CleanupKeys(
        audio=_keys([*legacy_audio, *review_audio, *personal_audio]),
        material=_keys(material_assets),
        assignment=_keys([*assignment_assets, *review_assets]),
    ),
    now=now,
)
~~~

Define the small `_keys` helper locally in the adapter. Do not commit inside the session.

- [x] **Step 4: Migrate personal upload intents**

Use `SQLiteStorageCleanupQueue(database).enqueue(CleanupKeys(audio=(storage_key,)), now=now, available_at=available_at)` in `create_upload_intent`. In `finalize_recording`, replace the direct DELETE with `queue.cancel(cleanup_job_id)` and raise the existing `PersonalRecordingIntentError` when it returns false.

Define:

~~~python
UPLOAD_INTENT_GRACE_SECONDS = 60 * 60
~~~

in `src/trainer/services/personal_recordings.py`. Update personal service tests to import the constant from its new owner. Retain the old constant in `storage_cleanup.py` only as a temporary compatibility export until runtime migrates in Task 5 and Task 6 deletes the procedural block.

- [x] **Step 5: Run producer tests**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.integration.test_account_repository \
  tests.integration.test_personal_recording_repository \
  tests.unit.test_personal_recording_service -v
~~~

Expected: PASS with unchanged rows, errors and intent timing.

- [x] **Step 6: Commit producer migration**

~~~bash
git add src/trainer/infrastructure/database/account_repository.py \
  src/trainer/infrastructure/database/personal_recording_repository.py \
  src/trainer/services/personal_recordings.py \
  tests/integration/test_account_repository.py \
  tests/integration/test_personal_recording_repository.py \
  tests/unit/test_personal_recording_service.py
git commit -m "refactor: migrate account and personal cleanup intents"
~~~

## Task 4: Review Cleanup Producer and Best-Effort Callback

**Files:**
- Modify: `src/trainer/services/review_request_repository.py`
- Modify: `src/trainer/services/review_requests.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `tests/unit/test_review_request_service.py`
- Modify: `tests/integration/test_review_request_repository.py`

**Interfaces:**
- Changes session `enqueue_cleanup(..., now: int) -> None`.
- Changes repository `enqueue_orphan_cleanup(..., now: int) -> None`.
- Adds `cleanup_runner: Callable[[], object]` to `ReviewRequestService`, with a no-op default until runtime supplies it in Task 5.
- Stops `ReviewRequestService` from calling `repository.process_cleanup()`.

- [ ] **Step 1: Update fake-repository tests first**

Change `FakeReviewRequestRepository` so cleanup calls record `(keys, now)` and remove its `process_cleanup`. Add a `cleanup_calls` list supplied by `make_service` through `cleanup_runner=lambda: cleanup_calls.append("processed")`.

Assert replacement uses the service clock:

~~~python
self.assertEqual(repository.cleanup_audio_keys, ["review-requests/9/old.webm"])
self.assertEqual(repository.cleanup_times, [1000])
~~~

Assert orphan and discard flows enqueue before invoking the callback. Make the callback raise `OSError("storage down")` and verify create/upload compensation and discard retain their existing result because cleanup remains best-effort.

- [ ] **Step 2: Run review service tests to observe RED**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_review_request_service -v
~~~

Expected: failures because timestamps and `cleanup_runner` are not yet part of the interfaces.

- [ ] **Step 3: Change the review port and service**

In `ReviewRequestSession.enqueue_cleanup` and `ReviewRequestRepository.enqueue_orphan_cleanup`, add the required keyword `now: int`. Remove `ReviewRequestRepository.process_cleanup`.

Add `cleanup_runner` to the service constructor and store it. Update the three producer paths:

~~~python
now = int(self.clock())
session.enqueue_cleanup(audio_keys=keys, assignment_keys=asset_keys, now=now)
~~~

and:

~~~python
with suppress(Exception):
    self.repository.enqueue_orphan_cleanup(
        audio_keys=audio_keys,
        assignment_keys=assignment_keys,
        now=int(self.clock()),
    )
    self.cleanup_runner()
~~~

After discard commit, call only `self.cleanup_runner()` inside the existing `suppress(Exception)`.

- [ ] **Step 4: Migrate SQLite review enqueue operations**

Replace the legacy `enqueue_cleanup_job` import with `CleanupKeys` and `SQLiteStorageCleanupQueue`. Both session and orphan methods call `enqueue(..., now=now)`. Keep the existing review repository constructor, its `process_cleanup_jobs` import and the now-unused `process_cleanup` method temporarily so runtime remains compatible until Task 5; Task 6 removes all three.

- [ ] **Step 5: Run review unit and integration tests**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_review_request_service \
  tests.integration.test_review_request_repository -v
~~~

Expected: PASS; compensation and transaction behavior remain unchanged.

- [ ] **Step 6: Commit review producer migration**

~~~bash
git add src/trainer/services/review_request_repository.py \
  src/trainer/services/review_requests.py \
  src/trainer/infrastructure/database/review_request_repository.py \
  tests/unit/test_review_request_service.py \
  tests/integration/test_review_request_repository.py
git commit -m "refactor: delegate review cleanup processing"
~~~

## Task 5: Runtime Composition and CLI Cutover

**Files:**
- Modify: `src/trainer/api/runtime.py`
- Modify: `scripts/cleanup_storage.py`
- Modify: `tests/unit/test_application_services.py`
- Modify: `tests/unit/test_storage_cleanup_command.py`
- Modify: `tests/integration/test_accounts.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Produces `runtime.storage_cleanup_service() -> StorageCleanupService`.
- Produces `runtime._process_storage_cleanup() -> CleanupSummary` as the common opportunistic callback.
- Preserves `runtime._process_account_cleanup() -> AccountCleanupSummary`.
- Makes the CLI use one service and one fixed cutoff.

- [ ] **Step 1: Write runtime composition tests**

Replace patches of `runtime.expire_recordings`/`runtime.process_cleanup_jobs` with a fake service. Assert the factory is uncached and receives:

~~~python
SQLiteStorageCleanupRepository(runtime.connect)
StorageCleanupService(
    repository,
    audio_storage=audio_factory,
    material_storage=material_factory,
    assignment_storage=assignment_factory,
)
~~~

Each category factory must remain uncalled during composition and invoke `storage_from_env` only when called. Assert `init_database()` calls `expire_batch()` before `process_batch()` and keeps `storage_cleanup_startup_failed` on either exception. Assert `review_request_service()` passes `runtime._process_storage_cleanup` and constructs `SQLiteReviewRequestRepository(runtime.connect)` without roots.

- [ ] **Step 2: Rewrite CLI tests against the service**

In `tests/unit/test_storage_cleanup_command.py`, make `runtime.storage_cleanup_service.return_value` the fake service. Preserve the existing side effects and assert:

~~~python
service.expire_batch.call_args_list == [
    call(limit=500, now=100),
    call(limit=500, now=100),
]
service.process_batch.call_args_list == [
    call(limit=500, now=100),
    call(limit=500, now=100),
]
~~~

Also assert the exact accumulated stdout and nonzero result for failed/pending work.

- [ ] **Step 3: Run runtime and CLI tests to observe RED**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_application_services \
  tests.unit.test_storage_cleanup_command -v
~~~

Expected: failures because runtime and CLI do not expose or consume the service factory.

- [ ] **Step 4: Implement runtime composition**

Import `UPLOAD_INTENT_GRACE_SECONDS` from `personal_recordings`, and import `StorageCleanupService` plus `SQLiteStorageCleanupRepository`. Add:

~~~python
def storage_cleanup_service() -> StorageCleanupService:
    return StorageCleanupService(
        SQLiteStorageCleanupRepository(connect),
        audio_storage=lambda: storage_from_env(AUDIO_DIR),
        material_storage=lambda: storage_from_env(MATERIAL_ASSET_DIR),
        assignment_storage=lambda: storage_from_env(REVIEW_ASSET_DIR),
    )


def _process_storage_cleanup() -> CleanupSummary:
    return storage_cleanup_service().process_batch()
~~~

Make `_process_account_cleanup` map `_process_storage_cleanup()`. Make `init_database` create one cleanup service inside its existing `try`, call `expire_batch()` then `process_batch()`, and keep exact log messages/events/fields.

Construct `SQLiteReviewRequestRepository(connect)` without roots and pass `cleanup_runner=_process_storage_cleanup` to `ReviewRequestService`.

- [ ] **Step 5: Cut the CLI over to the service**

Remove the database context and old function imports. After `runtime.init_database(cleanup=False)` and `cleanup_cutoff = int(time())`, create one service and keep the two batch loops:

~~~python
service = runtime.storage_cleanup_service()
batch = service.expire_batch(limit=500, now=cleanup_cutoff)
batch = service.process_batch(limit=500, now=cleanup_cutoff)
~~~

Accumulate and print the same summary and preserve the current loop termination conditions.

- [ ] **Step 6: Update API/integration patch points**

In `tests/integration/test_accounts.py` and `tests/integration/test_api_flows.py`:

- replace direct `process_cleanup_jobs(...)` calls with `runtime.storage_cleanup_service().process_batch(now=...)`;
- replace monkey-patches of `runtime.process_cleanup_jobs` with patches of `runtime._process_storage_cleanup`;
- when a test inspects the durable job before immediate processing, inspect through a wrapper around `_process_storage_cleanup` and then call the saved original callback;
- import `UPLOAD_INTENT_GRACE_SECONDS` from `trainer.services.personal_recordings`;
- preserve assertions for durable jobs, concurrent upload protection and physical deletion.

- [ ] **Step 7: Run runtime, CLI, account and API-flow tests**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_application_services \
  tests.unit.test_storage_cleanup_command \
  tests.integration.test_accounts \
  tests.integration.test_api_flows -v
~~~

Expected: PASS with exact CLI output and unchanged HTTP behavior.

- [ ] **Step 8: Commit runtime cutover**

~~~bash
git add src/trainer/api/runtime.py scripts/cleanup_storage.py \
  tests/unit/test_application_services.py \
  tests/unit/test_storage_cleanup_command.py \
  tests/integration/test_accounts.py \
  tests/integration/test_api_flows.py
git commit -m "refactor: compose storage cleanup service"
~~~

## Task 6: Remove the Procedural API and Lock the Boundary

**Files:**
- Modify: `src/trainer/services/storage_cleanup.py`
- Modify: `src/trainer/infrastructure/database/review_request_repository.py`
- Modify: `tests/unit/test_application_services.py`
- Modify: `tests/integration/test_storage.py`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `docs/architecture.md`

**Interfaces:**
- Removes all four legacy free functions and both infrastructure imports from `services/storage_cleanup.py`.
- Removes review repository storage-root constructor parameters and `process_cleanup`.
- Leaves only the service API, neutral port and SQLite adapter described in the spec.

- [ ] **Step 1: Add the architecture regression before deletion**

Extend `tests/unit/test_architecture_boundaries.py`:

~~~python
def test_storage_cleanup_boundary_dependency_direction(self):
    service = PACKAGE / "services" / "storage_cleanup.py"
    port = PACKAGE / "services" / "storage_cleanup_repository.py"
    service_imports = file_imports(service)
    port_imports = file_imports(port)
    self.assertFalse(any(name.startswith(("trainer.api", "trainer.infrastructure")) for name in service_imports))
    self.assertFalse(any(name.startswith(("trainer.api", "trainer.infrastructure")) for name in port_imports))
    self.assertNotIn("sqlite3", service_imports | port_imports)
    source = service.read_text(encoding="utf-8")
    for retired in (
        "def expire_recordings(",
        "def enqueue_cleanup_job(",
        "def process_cleanup_jobs(",
        "def account_review_storage_keys(",
    ):
        self.assertNotIn(retired, source)

    review_adapter = (PACKAGE / "infrastructure/database/review_request_repository.py").read_text(encoding="utf-8")
    self.assertNotIn("def process_cleanup(", review_adapter)
~~~

- [ ] **Step 2: Run the architecture test to observe RED**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_architecture_boundaries.ArchitectureBoundaryTest.test_storage_cleanup_boundary_dependency_direction -v
~~~

Expected: FAIL because the procedural functions and infrastructure imports still exist.

- [ ] **Step 3: Delete migrated compatibility code**

Remove the legacy imports, constants and four free functions from `services/storage_cleanup.py`; keep only `CleanupSummary`, protocols and `StorageCleanupService`. Remove the now-unused path fields, root constructor arguments and `process_cleanup` method from `SQLiteReviewRequestRepository`.

Delete `StorageCleanupJobServiceTest` from `tests/unit/test_application_services.py` because its cases now live in the dedicated service and adapter suites. Delete `LocalStorageTest.test_selects_private_review_keys_before_account_cascade` from `tests/integration/test_storage.py` because the stronger account repository test owns that behavior.

- [ ] **Step 4: Update architecture documentation**

Add a `Вертикальная граница очистки хранилищ` section to `docs/architecture.md` with:

~~~text
runtime / cleanup CLI / application callbacks
  → StorageCleanupService
    → StorageCleanupRepository / storage ports
      → SQLiteStorageCleanupRepository / configured storage
~~~

State that producer repositories use `SQLiteStorageCleanupQueue` on their current transactions, workers claim jobs with a one-hour lease, storage I/O happens outside SQLite write transactions, and stale outcomes are ignored. Update the review section so SQLite owns cleanup intents but `ReviewRequestService` invokes the cleanup callback. Do not change `DEVELOPMENT.md`; its command and exit-code description remain correct.

- [ ] **Step 5: Verify no old call sites remain**

Run:

~~~bash
rg -n "account_review_storage_keys|enqueue_cleanup_job|expire_recordings|process_cleanup_jobs|def process_cleanup" \
  src scripts tests
~~~

Expected: no matches for the four retired names; `expire_recordings` may remain only as the repository protocol/adapter method, never as a free function or caller import. If using the broad search, confirm those remaining method declarations/calls are `repository.expire_recordings` only.

- [ ] **Step 6: Run focused boundary and cleanup suites**

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_storage_cleanup_service \
  tests.integration.test_storage_cleanup_repository \
  tests.integration.test_account_repository \
  tests.integration.test_personal_recording_repository \
  tests.unit.test_review_request_service \
  tests.integration.test_review_request_repository \
  tests.unit.test_storage_cleanup_command \
  tests.unit.test_architecture_boundaries -v
~~~

Expected: PASS.

- [ ] **Step 7: Run the mandatory complete verification**

Run:

~~~bash
make check
~~~

Expected: formatting/static checks and all JavaScript, Python unit and integration tests pass at the repository's required coverage threshold.

- [ ] **Step 8: Commit the completed boundary**

~~~bash
git add src/trainer/services/storage_cleanup.py \
  src/trainer/infrastructure/database/review_request_repository.py \
  tests/unit/test_application_services.py \
  tests/integration/test_storage.py \
  tests/unit/test_architecture_boundaries.py \
  docs/architecture.md
git commit -m "refactor: isolate storage cleanup service boundary"
~~~

- [ ] **Step 9: Confirm the final tree and commit range**

Run:

~~~bash
git status --short --branch
git log --oneline --decorate -7
~~~

Expected: only the pre-existing untracked `.superpowers/brainstorm/` remains; implementation commits are visible after the plan/spec commits.

## Completion Criteria

- `StorageCleanupService` and its port have no API, infrastructure, SQLite, JSON, environment or filesystem dependency.
- Every producer creates or cancels cleanup work atomically on its existing SQLite transaction.
- Cleanup processing uses short lease/result transactions and external storage I/O outside database locks.
- Two workers cannot process one job concurrently before lease expiry, and a stale outcome cannot overwrite a newer claim.
- Runtime, review/account callbacks and CLI use the new service; review repository does not process cleanup.
- The four legacy free functions and all imports/call sites are gone.
- Public HTTP behavior, CLI output, logs, retention and storage configuration remain unchanged.
- `make check` has fresh successful output; no frontend files changed, so Playwright is not required.
