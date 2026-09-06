# Recording Access Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Remove SQL, clocks, owner configuration and authorization rules from the recordings controller without changing any file-access behavior.

**Architecture:** A transport-only controller calls RecordingAccessService. The service owns access decisions using an injected clock and owner email; a RecordingAccessRepository port isolates the SQLite JOIN queries. Routes continue to own Range handling and physical file streaming.

**Tech Stack:** Existing Python, FastAPI, SQLite, unittest, dataclasses and typing Protocol; no new dependencies.

**Spec:** docs/superpowers/specs/2026-09-06-recording-access-service-boundary-design.md

## Global Constraints

- Preserve GET /api/recordings/{recording_id}, GET /api/review-recordings/{recording_id} and GET /api/review-assets/{asset_id}.
- Preserve require_authenticated, route function names, FileResult fields, Range behavior and storage roots.
- Preserve legacy access by matching actor ID to student_id or teacher_id. Do not add role or email checks to the legacy path.
- Preserve uploading legacy visibility: only the matching student_id may read it.
- Preserve review student access, owner-teacher role/email-verification/status checks, and conceal every denial as the existing resource-specific 404.
- A review recording is unavailable to everyone when expires_at <= int(clock()). Review assets have no independent expiry check.
- Preserve exact public errors: not_found / recording_not_found / asset_not_found and the current Russian messages.
- Propagate database and unexpected service errors; do not translate them into 404.
- Do not change migrations, tables, storage, upload/delete/cleanup workflows, frontend or old compatibility data.
- Use test-first RED/GREEN cycles. Run make check before each code commit and before completion. UI is unchanged, so no extra Playwright run is required.
- Preserve the user's untracked .superpowers/brainstorm/ and unrelated worktrees. Execute in an isolated worktree at implementation time.

---

## File Map

- Create src/trainer/services/recording_access_repository.py: neutral records and repository port.
- Create src/trainer/services/recording_access.py: authorization and expiry orchestration.
- Create src/trainer/infrastructure/database/recording_access_repository.py: three SQLite reads.
- Modify src/trainer/api/controllers/recordings.py: actor/result/error transport mapping only.
- Modify src/trainer/api/runtime.py: uncached service composition.
- Create tests/unit/test_recording_access_service.py: service behavior.
- Create tests/integration/test_recording_access_repository.py: real SQLite JOIN behavior.
- Create tests/unit/test_recordings_controller.py: controller contract.
- Modify tests/unit/test_application_services.py: runtime composition.
- Modify tests/unit/test_architecture_boundaries.py: dependency-direction regression.
- Modify tests/integration/test_api_flows.py: compatibility characterization and service clock patch.
- Modify docs/architecture.md: document the new vertical boundary.

## Task 1: Port and Access Service

**Files:**
- Create: src/trainer/services/recording_access_repository.py
- Create: src/trainer/services/recording_access.py
- Create: tests/unit/test_recording_access_service.py

**Interfaces:**
- Produces RecordingActor, StoredFile, LegacyRecordingRecord, ReviewRecordingRecord and ReviewAssetRecord dataclasses.
- Produces RecordingAccessRepository.legacy_recording(id), review_recording(id) and review_asset(id).
- Produces RecordingAccessService(repository, *, owner_email, clock=time.time).
- Produces service methods legacy_recording(id, actor), review_recording(id, actor), review_asset(id, actor), each returning StoredFile or raising RecordingAccessError(reason).

- [x] **Step 1: Write failing service tests**

Create tests/unit/test_recording_access_service.py with literal records and a Mock repository:

~~~python
import unittest
from unittest.mock import Mock

from trainer.services.recording_access import RecordingAccessError, RecordingAccessService
from trainer.services.recording_access_repository import (
    LegacyRecordingRecord,
    RecordingActor,
    ReviewAssetRecord,
    ReviewRecordingRecord,
    StoredFile,
)


FILE = StoredFile("private/file.webm", "audio/webm", 10)
STUDENT = RecordingActor(7, "student", "student@example.test", False)
TEACHER = RecordingActor(8, "teacher", " Owner@Example.Test ", True)
OUTSIDER = RecordingActor(9, "student", "other@example.test", False)


class RecordingAccessServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.service = RecordingAccessService(
            self.repository,
            owner_email="owner@example.test",
            clock=lambda: 100,
        )

    def assert_reason(self, reason, call):
        with self.assertRaises(RecordingAccessError) as raised:
            call()
        self.assertEqual(raised.exception.reason, reason)

    def test_legacy_participants_and_uploading_visibility(self):
        self.repository.legacy_recording.return_value = LegacyRecordingRecord(FILE, "submitted", 7, 8)
        self.assertEqual(self.service.legacy_recording(3, STUDENT), FILE)
        self.assertEqual(self.service.legacy_recording(3, TEACHER), FILE)
        self.assert_reason("legacy_recording_not_found", lambda: self.service.legacy_recording(3, OUTSIDER))

        self.repository.legacy_recording.return_value = LegacyRecordingRecord(FILE, "uploading", 7, 8)
        self.assertEqual(self.service.legacy_recording(3, STUDENT), FILE)
        self.assert_reason("legacy_recording_not_found", lambda: self.service.legacy_recording(3, TEACHER))

    def test_review_recording_expiry_applies_to_student_and_owner(self):
        for expires_at, allowed in ((101, True), (100, False), (99, False)):
            self.repository.review_recording.return_value = ReviewRecordingRecord(
                FILE, "queued", 7, expires_at
            )
            for actor in (STUDENT, TEACHER):
                with self.subTest(expires_at=expires_at, actor=actor):
                    if allowed:
                        self.assertEqual(self.service.review_recording(4, actor), FILE)
                    else:
                        self.assert_reason(
                            "review_recording_not_found",
                            lambda actor=actor: self.service.review_recording(4, actor),
                        )

    def test_review_owner_requires_every_identity_and_status_condition(self):
        allowed = ReviewRecordingRecord(FILE, "queued", 7, 101)
        self.repository.review_recording.return_value = allowed
        self.assertEqual(self.service.review_recording(4, STUDENT), FILE)
        self.assertEqual(self.service.review_recording(4, TEACHER), FILE)
        denied = (
            RecordingActor(8, "student", "owner@example.test", True),
            RecordingActor(8, "teacher", "owner@example.test", False),
            RecordingActor(8, "teacher", "other@example.test", True),
        )
        for actor in denied:
            with self.subTest(actor=actor):
                self.assert_reason(
                    "review_recording_not_found",
                    lambda actor=actor: self.service.review_recording(4, actor),
                )
        for status in ("uploading", "deleted", ""):
            self.repository.review_recording.return_value = ReviewRecordingRecord(FILE, status, 7, 101)
            self.assert_reason(
                "review_recording_not_found",
                lambda: self.service.review_recording(4, TEACHER),
            )

    def test_review_asset_has_no_expiry_but_keeps_owner_rules(self):
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "uploading", 7)
        self.assertEqual(self.service.review_asset(5, STUDENT), FILE)
        self.assert_reason("review_asset_not_found", lambda: self.service.review_asset(5, TEACHER))
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "reviewed", 7)
        self.assertEqual(self.service.review_asset(5, TEACHER), FILE)
        self.assert_reason("review_asset_not_found", lambda: self.service.review_asset(5, OUTSIDER))

    def test_missing_rows_empty_owner_and_repository_errors(self):
        for method, reason in (
            ("legacy_recording", "legacy_recording_not_found"),
            ("review_recording", "review_recording_not_found"),
            ("review_asset", "review_asset_not_found"),
        ):
            getattr(self.repository, method).return_value = None
            self.assert_reason(reason, lambda method=method: getattr(self.service, method)(1, STUDENT))
        empty_owner = RecordingAccessService(self.repository, owner_email="", clock=lambda: 100)
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "queued", 7)
        self.assert_reason("review_asset_not_found", lambda: empty_owner.review_asset(5, TEACHER))
        self.repository.legacy_recording.side_effect = OSError("database down")
        with self.assertRaisesRegex(OSError, "database down"):
            self.service.legacy_recording(3, STUDENT)
~~~

- [x] **Step 2: Observe RED**

Run:

~~~bash
PYTHONPATH=src /Users/bronik04/Documents/Projects/chinese-speaking-trainer/.venv/bin/python \
  -m unittest tests.unit.test_recording_access_service -v
~~~

Expected: import failure because the port and service modules do not exist.

- [x] **Step 3: Implement the neutral port**

Create src/trainer/services/recording_access_repository.py:

~~~python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RecordingActor:
    id: int
    role: str
    email: str
    email_verified: bool


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class LegacyRecordingRecord:
    file: StoredFile
    status: str
    student_id: int
    teacher_id: int


@dataclass(frozen=True)
class ReviewRecordingRecord:
    file: StoredFile
    status: str
    student_id: int
    expires_at: int


@dataclass(frozen=True)
class ReviewAssetRecord:
    file: StoredFile
    status: str
    student_id: int


class RecordingAccessRepository(Protocol):
    def legacy_recording(self, recording_id: int) -> LegacyRecordingRecord | None: ...
    def review_recording(self, recording_id: int) -> ReviewRecordingRecord | None: ...
    def review_asset(self, asset_id: int) -> ReviewAssetRecord | None: ...
~~~

- [x] **Step 4: Implement the service**

Create src/trainer/services/recording_access.py:

~~~python
import time
from collections.abc import Callable
from typing import Protocol

from trainer.services.recording_access_repository import (
    RecordingAccessRepository,
    RecordingActor,
    StoredFile,
)


class RecordingAccessError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _ReviewVisibilityRecord(Protocol):
    status: str
    student_id: int


class RecordingAccessService:
    def __init__(
        self,
        repository: RecordingAccessRepository,
        *,
        owner_email: str,
        clock: Callable[[], float] = time.time,
    ):
        self._repository = repository
        self._owner_email = owner_email.strip().lower()
        self._clock = clock

    def _owner_allowed(self, record: _ReviewVisibilityRecord, actor: RecordingActor) -> bool:
        return bool(
            self._owner_email
            and record.status in {"queued", "reviewed"}
            and actor.role == "teacher"
            and actor.email_verified
            and actor.email.strip().lower() == self._owner_email
        )

    def legacy_recording(self, recording_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.legacy_recording(recording_id)
        if (
            record is None
            or actor.id not in {record.student_id, record.teacher_id}
            or (record.status == "uploading" and actor.id != record.student_id)
        ):
            raise RecordingAccessError("legacy_recording_not_found")
        return record.file

    def review_recording(self, recording_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.review_recording(recording_id)
        if record is None or record.expires_at <= int(self._clock()):
            raise RecordingAccessError("review_recording_not_found")
        if actor.id != record.student_id and not self._owner_allowed(record, actor):
            raise RecordingAccessError("review_recording_not_found")
        return record.file

    def review_asset(self, asset_id: int, actor: RecordingActor) -> StoredFile:
        record = self._repository.review_asset(asset_id)
        if record is None or (actor.id != record.student_id and not self._owner_allowed(record, actor)):
            raise RecordingAccessError("review_asset_not_found")
        return record.file
~~~

The private structural Protocol deliberately lets both review record types share the identical owner policy without coupling either dataclass to a base class.

- [x] **Step 5: Run service tests and architecture suite**

Run the new service test and tests.unit.test_architecture_boundaries. Expected: PASS.

- [x] **Step 6: Run make check and commit**

Stage the task files before make check so repository hygiene sees newly tracked files. Run make check with the absolute Python override, inspect exit code zero, then:

~~~bash
git commit -m "refactor: define recording access service"
~~~

## Task 2: SQLite Recording Access Adapter

**Files:**
- Create: src/trainer/infrastructure/database/recording_access_repository.py
- Create: tests/integration/test_recording_access_repository.py

**Interfaces:**
- Consumes all records and repository signatures from Task 1.
- Produces SQLiteRecordingAccessRepository(connect).

- [x] **Step 1: Write failing real-SQLite tests**

Create a TemporaryDirectory, call upgrade_sqlite_database(path), open sqlite3 connections with row_factory sqlite3.Row and foreign_keys ON, and insert literal users plus:

~~~sql
INSERT INTO study_groups(id,teacher_id,name,join_code,created_at)
VALUES (10,2,'Archive','ABC234',1);
INSERT INTO assignments(id,group_id,teacher_id,title,variant_id,tasks_json,created_at)
VALUES (20,10,2,'Old work','demo-2026','[2]',1);
INSERT INTO submissions(id,assignment_id,student_id,attempt_number,status,run_json,submitted_at)
VALUES (30,20,1,1,'submitted','{}',1);
INSERT INTO recordings(id,submission_id,task_number,label,file_name,mime_type,size_bytes,created_at)
VALUES (40,30,2,'Legacy','30/legacy.webm','audio/webm',10,1);
INSERT INTO review_requests(id,student_id,kind,status,variant_id,run_json,submitted_at)
VALUES (50,1,'task','queued','demo-2026','{}',1);
INSERT INTO review_request_items(id,request_id,task_number,task_snapshot_json)
VALUES (60,50,2,'{}');
INSERT INTO review_request_recordings(
  id,item_id,label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at
) VALUES (70,60,'Review','review/answer.ogg','audio/ogg',11,1.0,1,500);
INSERT INTO review_request_assets(id,request_id,storage_key,mime_type,size_bytes,created_at)
VALUES (80,50,'review/image.webp','image/webp',12,1);
~~~

Tests must assert these exact records:

~~~python
self.assertEqual(
    repository.legacy_recording(40),
    LegacyRecordingRecord(StoredFile("30/legacy.webm", "audio/webm", 10), "submitted", 1, 2),
)
self.assertEqual(
    repository.review_recording(70),
    ReviewRecordingRecord(StoredFile("review/answer.ogg", "audio/ogg", 11), "queued", 1, 500),
)
self.assertEqual(
    repository.review_asset(80),
    ReviewAssetRecord(StoredFile("review/image.webp", "image/webp", 12), "queued", 1),
)
for missing in (0, 999):
    self.assertIsNone(repository.legacy_recording(missing))
    self.assertIsNone(repository.review_recording(missing))
    self.assertIsNone(repository.review_asset(missing))
~~~

Set expires_at to 1 and assert review_recording still returns ReviewRecordingRecord(..., expires_at=1), proving expiry is not filtered in SQL. Insert a second request with student_id 3, its own item and asset ID 81; assert review_asset(80).student_id == 1 and review_asset(81).student_id == 3 so JOIN results cannot mix requests.

Track connection closure with this real connection subclass:

~~~python
class TrackingConnection(sqlite3.Connection):
    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False
        self.instances.append(self)

    def close(self):
        self.closed = True
        super().close()


tracking = SQLiteRecordingAccessRepository(
    lambda: self.connect(factory=TrackingConnection)
)
tracking.legacy_recording(40)
tracking.review_recording(70)
tracking.review_asset(80)
self.assertEqual(len(TrackingConnection.instances), 3)
self.assertTrue(all(connection.closed for connection in TrackingConnection.instances))
~~~

- [x] **Step 2: Observe RED**

Run tests.integration.test_recording_access_repository. Expected: import failure for the absent adapter.

- [x] **Step 3: Implement the adapter**

Create src/trainer/infrastructure/database/recording_access_repository.py:

~~~python
import sqlite3
from collections.abc import Callable
from contextlib import closing

from trainer.services.recording_access_repository import (
    LegacyRecordingRecord,
    ReviewAssetRecord,
    ReviewRecordingRecord,
    StoredFile,
)


class SQLiteRecordingAccessRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def legacy_recording(self, recording_id: int) -> LegacyRecordingRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT recordings.file_name,recordings.mime_type,recordings.size_bytes,
                          submissions.status,submissions.student_id,assignments.teacher_id
                   FROM recordings
                   JOIN submissions ON submissions.id=recordings.submission_id
                   JOIN assignments ON assignments.id=submissions.assignment_id
                   WHERE recordings.id=?""",
                (recording_id,),
            ).fetchone()
        return (
            LegacyRecordingRecord(
                StoredFile(row["file_name"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
                row["teacher_id"],
            )
            if row
            else None
        )

    def review_recording(self, recording_id: int) -> ReviewRecordingRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT review_request_recordings.storage_key,
                          review_request_recordings.mime_type,
                          review_request_recordings.size_bytes,
                          review_request_recordings.expires_at,
                          review_requests.status,review_requests.student_id
                   FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   JOIN review_requests ON review_requests.id=review_request_items.request_id
                   WHERE review_request_recordings.id=?""",
                (recording_id,),
            ).fetchone()
        return (
            ReviewRecordingRecord(
                StoredFile(row["storage_key"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
                row["expires_at"],
            )
            if row
            else None
        )

    def review_asset(self, asset_id: int) -> ReviewAssetRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                """SELECT review_request_assets.storage_key,review_request_assets.mime_type,
                          review_request_assets.size_bytes,review_requests.status,
                          review_requests.student_id
                   FROM review_request_assets
                   JOIN review_requests ON review_requests.id=review_request_assets.request_id
                   WHERE review_request_assets.id=?""",
                (asset_id,),
            ).fetchone()
        return (
            ReviewAssetRecord(
                StoredFile(row["storage_key"], row["mime_type"], row["size_bytes"]),
                row["status"],
                row["student_id"],
            )
            if row
            else None
        )
~~~

- [x] **Step 4: Run adapter and service suites**

Run tests.integration.test_recording_access_repository and tests.unit.test_recording_access_service. Expected: PASS.

- [ ] **Step 5: Run make check and commit**

Stage both files, run make check, require exit zero, then:

~~~bash
git commit -m "refactor: add sqlite recording access repository"
~~~

## Task 3: API Cutover and Regression Gates

**Files:**
- Modify: src/trainer/api/controllers/recordings.py
- Modify: src/trainer/api/runtime.py
- Create: tests/unit/test_recordings_controller.py
- Modify: tests/unit/test_application_services.py
- Modify: tests/unit/test_architecture_boundaries.py
- Modify: tests/integration/test_api_flows.py
- Modify: docs/architecture.md

**Interfaces:**
- Consumes RecordingAccessService and SQLiteRecordingAccessRepository from Tasks 1–2.
- Produces runtime.recording_access_service() and preserves the three controller function signatures.

- [ ] **Step 1: Add controller tests before cutover**

Create tests/unit/test_recordings_controller.py. Patch runtime.recording_access_service with a Mock. For each public function assert actor conversion, exact service call and FileResult:

~~~python
user = {
    "id": 7,
    "role": "teacher",
    "email": " Owner@Example.Test ",
    "emailVerified": True,
}
actor = RecordingActor(7, "teacher", " Owner@Example.Test ", True)
stored = StoredFile("private/file.webm", "audio/webm", 10)
service.legacy_recording.return_value = stored
self.assertEqual(recordings.recording_get(3, user), FileResult("private/file.webm", "audio/webm", 10))
service.legacy_recording.assert_called_once_with(3, actor)
~~~

Repeat the literal assertion for review_recording_get and review_asset_get using IDs 4 and 5, and assert the respective Mock method receives the same literal actor. For each known reason, set the corresponding service method side_effect and assert:

~~~python
cases = (
    ("legacy_recording_not_found", "not_found", "Запись не найдена"),
    ("review_recording_not_found", "recording_not_found", "Запись не найдена"),
    ("review_asset_not_found", "asset_not_found", "Изображение не найдено"),
)
~~~

Every resulting ApiError must have status 404 and the exact code/message above. Set side_effect to RecordingAccessError("unexpected") and assert the identical exception object escapes.

- [ ] **Step 2: Add runtime composition test**

Extend tests/unit/test_application_services.py:

~~~python
class RecordingAccessRuntimeTest(unittest.TestCase):
    def test_factory_composes_uncached_repository_without_storage(self):
        repository, service = object(), object()
        with (
            patch.object(runtime, "SQLiteRecordingAccessRepository", return_value=repository) as repository_type,
            patch.object(runtime, "RecordingAccessService", return_value=service) as service_type,
            patch.object(runtime, "owner_email", return_value="owner@example.test"),
            patch.object(runtime, "storage_from_env") as storage_factory,
        ):
            self.assertIs(runtime.recording_access_service(), service)
            self.assertIs(runtime.recording_access_service(), service)
        self.assertEqual(repository_type.call_count, 2)
        self.assertEqual(service_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        service_type.assert_called_with(repository, owner_email="owner@example.test")
        storage_factory.assert_not_called()
~~~

- [ ] **Step 3: Strengthen API characterization before cutover**

Use existing ApiFlowTest helpers. Keep all current Range tests. Add this authentication characterization before changing production code:

~~~python
def test_recording_file_routes_require_authentication(self):
    for path in ("/api/recordings/999", "/api/review-recordings/999", "/api/review-assets/999"):
        with self.subTest(path=path):
            self.assertEqual(self.request("GET", path)[0], 401)

def test_legacy_recording_remains_private_to_assignment_participants(self):
    recording_id, student_cookie = self.create_recording()
    other_student_cookie = self.register_student("legacy-recording-other")
    self.assertEqual(self.request_bytes(f"/api/recordings/{recording_id}", student_cookie)[0], 200)
    self.assertEqual(self.request_bytes(f"/api/recordings/{recording_id}", other_student_cookie)[0], 404)
~~~

Run it together with test_student_queues_single_task_for_owner_review,
test_account_deletion_removes_private_review_recording_and_snapshot and the four
test_recording_* Range tests. These existing real-API tests already establish:

- another student receives 404 for review recording and review asset;
- review owner receives 404 while uploading and receives the file after queued;
- review recording returns 404 to both student and owner at expires_at == now;
- review asset remains readable to its student independent of recording expiry.

Legacy teacher/uploading permutations are covered at service level; legacy student compatibility and Range behavior remain covered through create_recording and the four existing Range tests. All listed tests must PASS against the old implementation as the compatibility baseline.

Derive every expected code, body and byte range literally. Run these cases against the current controller first and require PASS; this is the compatibility baseline.

- [ ] **Step 4: Add architecture test and observe controller RED**

Extend ArchitectureBoundaryTest:

~~~python
def test_recording_access_boundary_dependency_direction(self):
    controller = PACKAGE / "api" / "controllers" / "recordings.py"
    source = controller.read_text(encoding="utf-8")
    for token in (".execute(", "connect", "import time", "owner_email_from_env",
                  "trainer.infrastructure", "trainer.domain"):
        self.assertNotIn(token, source)
    service_imports = file_imports(PACKAGE / "services" / "recording_access.py")
    port_imports = file_imports(PACKAGE / "services" / "recording_access_repository.py")
    adapter_imports = file_imports(
        PACKAGE / "infrastructure" / "database" / "recording_access_repository.py"
    )
    for imports in (service_imports, port_imports):
        self.assertFalse(any(item.startswith(("trainer.api", "trainer.infrastructure")) for item in imports))
        self.assertNotIn("sqlite3", imports)
    self.assertFalse(any(item.startswith("trainer.api") for item in adapter_imports))
~~~

Run the controller and architecture tests. Expected RED: controller still contains SQL/time/config and does not delegate.

- [ ] **Step 5: Replace controller implementation**

Keep the three public names. Implement a private actor conversion, StoredFile conversion and known-error mapping:

~~~python
from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import FileResult
from trainer.services.recording_access import RecordingAccessError
from trainer.services.recording_access_repository import RecordingActor, StoredFile


_ERRORS = {
    "legacy_recording_not_found": ("not_found", "Запись не найдена"),
    "review_recording_not_found": ("recording_not_found", "Запись не найдена"),
    "review_asset_not_found": ("asset_not_found", "Изображение не найдено"),
}


def _actor(user: dict) -> RecordingActor:
    return RecordingActor(
        user["id"],
        str(user.get("role", "")),
        str(user.get("email", "")),
        bool(user.get("emailVerified")),
    )


def _result(stored: StoredFile) -> FileResult:
    return FileResult(stored.storage_key, stored.mime_type, stored.size_bytes)


def _access(call) -> FileResult:
    try:
        return _result(call())
    except RecordingAccessError as error:
        public = _ERRORS.get(error.reason)
        if public is None:
            raise
        raise ApiError(public[0], public[1], 404) from error


def recording_get(recording_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().legacy_recording(recording_id, _actor(user)))


def review_recording_get(recording_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().review_recording(recording_id, _actor(user)))


def review_asset_get(asset_id: int, user: dict) -> FileResult:
    return _access(lambda: runtime.recording_access_service().review_asset(asset_id, _actor(user)))
~~~

- [ ] **Step 6: Add runtime factory**

Import SQLiteRecordingAccessRepository and RecordingAccessService in runtime.py, then add:

~~~python
def recording_access_service() -> RecordingAccessService:
    return RecordingAccessService(
        SQLiteRecordingAccessRepository(connect),
        owner_email=owner_email(),
    )
~~~

Do not cache the service and do not construct storage or mail dependencies.

- [ ] **Step 7: Adapt the expiry test without patching controller time**

The existing API test patches recordings.time.time. After cutover that symbol is intentionally absent. Replace that patch with an exact real-service fixture:

~~~python
access_service = RecordingAccessService(
    SQLiteRecordingAccessRepository(runtime.connect),
    owner_email=owner_email(),
    clock=lambda: 100,
)
with (
    patch.object(runtime, "recording_access_service", return_value=access_service),
    patch.object(review_request_queries.time, "time", return_value=100),
):
    self.assertEqual(self.request_bytes(f"/api/review-recordings/{recording_id}", student_cookie)[0], 404)
    self.assertEqual(self.request_bytes(f"/api/review-recordings/{recording_id}", owner_cookie)[0], 404)
    # Keep the existing history/detail expiry assertions inside this block.
~~~

Import owner_email, SQLiteRecordingAccessRepository and RecordingAccessService at the top of the integration test. Keep the existing history/detail assertions so query-level expiry behavior remains characterized too.

- [ ] **Step 8: Document the boundary**

Add to docs/architecture.md:

~~~markdown
### Вертикальная граница доступа к записям

Маршруты legacy-записей, review-аудио и review-изображений используют
transport-only controller и RecordingAccessService. Сервис владеет правилами
видимости и сроком review-записи; RecordingAccessRepository связывает его с
SQLite adapter, которому принадлежат SELECT/JOIN.

Range-обработка и физическое чтение local/S3/R2 остаются в route/file_response.
Старые записи назначений остаются доступны по прежнему URL; таблицы и frontend
не меняются.
~~~

- [ ] **Step 9: Run focused GREEN suites**

Run:

~~~bash
PYTHONPATH=src /Users/bronik04/Documents/Projects/chinese-speaking-trainer/.venv/bin/python \
  -m unittest \
  tests.unit.test_recording_access_service \
  tests.integration.test_recording_access_repository \
  tests.unit.test_recordings_controller \
  tests.unit.test_application_services \
  tests.unit.test_architecture_boundaries \
  tests.integration.test_api_flows -v
~~~

Expected: PASS, including existing Range and review workflow tests.

- [ ] **Step 10: Static inspection**

Run:

~~~bash
git diff --check
rg -n '\.execute\(|runtime\.connect|import time|owner_email_from_env' \
  src/trainer/api/controllers/recordings.py
rg -n 'recording_access_service|SQLiteRecordingAccessRepository|RecordingAccessService' \
  src tests
~~~

Expected: first rg has no matches; second shows runtime, controller and tests.

- [ ] **Step 11: Run full verification and commit**

Stage all task files before the check. Run make check with the absolute Python override. Require exit zero, then:

~~~bash
git commit -m "refactor: isolate recording access service boundary"
~~~

- [ ] **Step 12: Independent review and handoff**

Use superpowers:requesting-code-review for the complete branch diff from its main fork point. Fix every valid Critical or Important finding through a failing regression test, rerun make check after corrections, and commit fixes. Do not merge or push without explicit user authorization. Finish with superpowers:finishing-a-development-branch.

## Plan Self-Review

- [x] Spec coverage: legacy compatibility, three URLs, exact access matrix, expiry, errors, Range ownership, SQL adapter, composition and documentation all map to tasks.
- [x] Type consistency: service, port, adapter, controller and tests use the same actor, stored-file and record fields.
- [x] Scope: no migration, storage, upload/delete/cleanup, frontend or legacy-data removal.
- [x] No implementation placeholders; each production interface and verification command is explicit.
- [ ] Execution has not started. Create an isolated worktree from main and run a clean baseline first.
