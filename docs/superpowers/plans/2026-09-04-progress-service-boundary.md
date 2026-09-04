# Progress Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete groups API modules and move progress validation and persistence behind a tested service boundary without changing synchronization behavior.

**Architecture:** Routes call a transport-only progress controller. `ProgressService` uses pure domain validation, an injected clock, and a `ProgressRepository` port; `SQLiteProgressRepository` owns JSON persistence and transactions. Runtime composes dependencies without storage or mail.

**Tech Stack:** Existing Python, FastAPI/Pydantic, SQLite, unittest, dataclasses, typing Protocol; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-04-progress-service-boundary-design.md` (approved by the user's subsequent “дальше”).

## Global Constraints

- Preserve `GET /api/progress`, `PUT /api/progress`, `ProgressRequest`, `require_student` and route function names.
- Preserve `version == 1`, including `True` and `1.0`; missing `runs` is accepted, supplied runs must be a list of at most 200 items.
- PUT replaces the complete document; preserve Unicode, arbitrary fields, client timestamps and browser-owned merging.
- GET of a missing row returns `{"progress": null, "updatedAt": null}`. Malformed persisted JSON raises; valid historical JSON values are not normalized.
- Preserve HTTP 400 / `invalid_request` messages `Invalid progress document` and `Progress history is too large`; schema errors stay 422.
- Return success only after commit; propagate storage failures. No database migrations, frontend changes or modifications of old groups/assignments/submissions tables.
- Do not remove the working domain accounts `EMAIL_RE`; only remove its unused runtime copy and `GROUP_CODE_ALPHABET`.
- Preserve the user's untracked `.superpowers/brainstorm/` and unrelated worktrees.
- Use `apply_patch` for edits. Run fresh `make check` before completion or a code commit. Request independent review before merge.

## Execution Setup and File Map

Read `AGENTS.md` and the spec first. Use `using-git-worktrees` at execution time; obtain worktree consent if not already granted. Do not start implementation directly on main without explicit permission. Suggested branch: `codex/progress-service-boundary`.

The existing main virtualenv can be reused in a worktree without installing or changing dependencies. From the worktree, run Python tests with `PYTHONPATH=src /Users/bronik04/Documents/Projects/chinese-speaking-trainer/.venv/bin/python`; use the same `PYTHONPATH` and absolute `PYTHON` override for `make check`. Run a clean baseline before code changes.

Files and responsibilities:

- `src/trainer/domain/progress.py`: pure validation and `ProgressValidationError`.
- `src/trainer/services/progress_repository.py`: typed read record and two-method port.
- `src/trainer/services/progress.py`: get/put orchestration and `ProgressError`.
- `src/trainer/infrastructure/database/progress_repository.py`: SQLite/JSON/transaction adapter.
- Rename `src/trainer/api/controllers/groups.py` to `progress.py`: HTTP input/output/error mapping only.
- Rename `src/trainer/api/routes/groups.py` to `progress.py`: retain endpoints and dependency wiring.
- `src/trainer/api/runtime.py`, `src/trainer/main.py`: service composition, router registration, dead constants removal.
- New `tests/unit/test_progress_service.py`, `tests/unit/test_progress_controller.py`, `tests/integration/test_progress_repository.py`.
- Extend `tests/unit/test_application_services.py`, `tests/unit/test_architecture_boundaries.py`, `tests/integration/test_api_flows.py`.
- `docs/architecture.md`: progress vertical boundary and unchanged browser-owned merging.

## Task 1: Domain, Port and Application Service

**Files:** Create domain/service/port and `tests/unit/test_progress_service.py` listed above.

**Interfaces:**
- Produces `validate_progress(document: object) -> None`, raising `ProgressValidationError(reason: str)`.
- Produces `ProgressRecord(document: Any, updated_at: int)`; `Any` deliberately preserves historical decoded JSON values.
- Produces `ProgressRepository.get(user_id: int) -> ProgressRecord | None` and `save(user_id: int, document: dict[str, Any], updated_at: int) -> None`.
- Produces `ProgressService(repository, *, clock=time.time)`, `get(user_id) -> ProgressRecord | None`, `put(user_id, document) -> int`, and `ProgressError(reason: str)`.

- [x] Write the failing tests below in `tests/unit/test_progress_service.py`.

```python
import unittest
from unittest.mock import Mock

from trainer.domain.progress import ProgressValidationError, validate_progress
from trainer.services.progress import ProgressError, ProgressService
from trainer.services.progress_repository import ProgressRecord


class ProgressServiceTest(unittest.TestCase):
    def test_domain_accepts_existing_shapes_without_mutation(self):
        for version in (1, True, 1.0):
            for document in ({"version": version}, {"version": version, "runs": [None] * 200, "extra": "中文"}):
                with self.subTest(document=document):
                    original = document.copy()
                    validate_progress(document)
                    self.assertEqual(document, original)

    def test_domain_rejects_invalid_documents(self):
        cases = ((None, "invalid_document"), ([], "invalid_document"), ({}, "invalid_document"),
                 ({"version": "1"}, "invalid_document"), ({"version": 2}, "invalid_document"),
                 ({"version": 1, "runs": None}, "history_too_large"),
                 ({"version": 1, "runs": {}}, "history_too_large"),
                 ({"version": 1, "runs": [None] * 201}, "history_too_large"))
        for document, reason in cases:
            with self.subTest(document=document):
                with self.assertRaises(ProgressValidationError) as raised:
                    validate_progress(document)
                self.assertEqual(raised.exception.reason, reason)

    def test_service_validates_before_clock_or_repository(self):
        repository, clock = Mock(), Mock()
        service = ProgressService(repository, clock=clock)
        for document, reason in (({}, "invalid_document"), ({"version": 1, "runs": None}, "history_too_large")):
            with self.assertRaises(ProgressError) as raised:
                service.put(7, document)
            self.assertEqual(raised.exception.reason, reason)
        repository.save.assert_not_called()
        clock.assert_not_called()

    def test_put_preserves_document_and_returns_integer_server_time(self):
        repository = Mock()
        document = {"version": 1, "updatedAt": "client", "runs": [], "extra": "中文"}
        service = ProgressService(repository, clock=lambda: 1000.9)
        self.assertEqual(service.put(7, document), 1000)
        repository.save.assert_called_once_with(7, document, 1000)

    def test_get_returns_repository_record_or_none(self):
        repository = Mock()
        service = ProgressService(repository)
        for record in (None, ProgressRecord({"version": 1}, 1000), ProgressRecord([], 1001)):
            repository.get.return_value = record
            self.assertIs(service.get(7), record)
            repository.get.assert_called_with(7)

    def test_repository_failures_are_not_reported_as_success(self):
        repository = Mock()
        repository.save.side_effect = OSError("storage down")
        repository.get.side_effect = OSError("storage down")
        service = ProgressService(repository)
        with self.assertRaisesRegex(OSError, "storage down"):
            service.put(7, {"version": 1})
        with self.assertRaisesRegex(OSError, "storage down"):
            service.get(7)
```

- [x] Run `.venv/bin/python -m unittest tests.unit.test_progress_service -v` (use the worktree Python command above when needed). Expected RED: new modules do not exist.
- [x] Implement the pure validator in `domain/progress.py`:

```python
class ProgressValidationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_progress(document: object) -> None:
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ProgressValidationError("invalid_document")
    runs = document.get("runs", [])
    if not isinstance(runs, list) or len(runs) > 200:
        raise ProgressValidationError("history_too_large")
```

- [x] Implement the port in `services/progress_repository.py`:

```python
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProgressRecord:
    document: Any
    updated_at: int


class ProgressRepository(Protocol):
    def get(self, user_id: int) -> ProgressRecord | None: ...
    def save(self, user_id: int, document: dict[str, Any], updated_at: int) -> None: ...
```

- [x] Implement `services/progress.py`:

```python
import time
from collections.abc import Callable
from typing import Any

from trainer.domain.progress import ProgressValidationError, validate_progress
from trainer.services.progress_repository import ProgressRecord, ProgressRepository


class ProgressError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ProgressService:
    def __init__(self, repository: ProgressRepository, *, clock: Callable[[], float] = time.time):
        self._repository = repository
        self._clock = clock

    def get(self, user_id: int) -> ProgressRecord | None:
        return self._repository.get(user_id)

    def put(self, user_id: int, document: dict[str, Any]) -> int:
        try:
            validate_progress(document)
        except ProgressValidationError as error:
            raise ProgressError(error.reason) from error
        updated_at = int(self._clock())
        self._repository.save(user_id, document, updated_at)
        return updated_at
```

- [x] Rerun `tests.unit.test_progress_service` and architecture tests, observe GREEN. Run `make check` before committing the standalone modules and tests with `refactor: define progress service boundary`.

## Task 2: SQLite Progress Repository

**Files:** Create `src/trainer/infrastructure/database/progress_repository.py` and `tests/integration/test_progress_repository.py`.

**Interfaces:** Consumes `ProgressRecord` and repository signatures from Task 1. Produces `SQLiteProgressRepository(connect: Callable[[], sqlite3.Connection])` with durable `save` and user-filtered `get`.

- [x] Write these integration tests first; all use temporary SQLite and real migrations.

```python
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.progress_repository import SQLiteProgressRepository
from trainer.services.progress_repository import ProgressRecord


class SQLiteProgressRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.path)
        self.repository = SQLiteProgressRepository(self.connect)
        with closing(self.connect()) as database, database:
            for user_id in (1, 2):
                database.execute(
                    "INSERT INTO users(id,email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?,?)",
                    (user_id, f"student{user_id}@example.test", "hash", "Student", "student", 1),
                )

    def connect(self, factory=sqlite3.Connection):
        database = sqlite3.connect(self.path, factory=factory)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def test_committed_round_trip_update_and_user_isolation(self):
        self.assertIsNone(self.repository.get(1))
        first = {"version": 1, "runs": [], "extra": "中文", "updatedAt": "client"}
        self.repository.save(1, first, 1000)
        self.assertEqual(self.repository.get(1), ProgressRecord(first, 1000))
        self.assertIsNone(self.repository.get(2))
        self.repository.save(2, {"version": 1, "extra": "other"}, 1001)
        self.repository.save(1, {"version": 1}, 1002)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 1}, 1002))
        self.assertEqual(self.repository.get(2).document["extra"], "other")
        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM user_progress").fetchone()[0], 2)

    def test_json_encoding_is_compact_and_unicode_preserving(self):
        document = {"version": 1, "extra": "中文"}
        self.repository.save(1, document, 1000)
        with closing(self.connect()) as database:
            value = database.execute("SELECT progress_json FROM user_progress WHERE user_id=1").fetchone()[0]
        self.assertEqual(value, json.dumps(document, ensure_ascii=False, separators=(",", ":")))

    def test_commit_failure_rolls_back_update(self):
        class FailingCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("commit failed")
        self.repository.save(1, {"version": 1, "extra": "old"}, 1000)
        failing = SQLiteProgressRepository(lambda: self.connect(FailingCommit))
        with self.assertRaisesRegex(sqlite3.OperationalError, "commit failed"):
            failing.save(1, {"version": 1, "extra": "new"}, 1001)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 1, "extra": "old"}, 1000))

    def test_historical_json_is_not_normalized_and_bad_json_raises(self):
        with closing(self.connect()) as database, database:
            database.execute("INSERT INTO user_progress(user_id,progress_json,updated_at) VALUES (1,'[]',1000)")
        self.assertEqual(self.repository.get(1), ProgressRecord([], 1000))
        with closing(self.connect()) as database, database:
            database.execute("UPDATE user_progress SET progress_json='not-json' WHERE user_id=1")
        with self.assertRaises(json.JSONDecodeError):
            self.repository.get(1)

    def test_serialization_failure_preserves_existing_document(self):
        self.repository.save(1, {"version": 1}, 1000)
        with self.assertRaises(TypeError):
            self.repository.save(1, {"version": 1, "extra": object()}, 1001)
        self.assertEqual(self.repository.get(1), ProgressRecord({"version": 1}, 1000))
```

- [x] Run `.venv/bin/python -m unittest tests.integration.test_progress_repository -v`. Expected RED: adapter module absent.
- [x] Implement the adapter with explicit commit, rollback and closing; do not rely on `ClosingConnection.__exit__` because injected plain connections must work too:

```python
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from typing import Any

from trainer.services.progress_repository import ProgressRecord


class SQLiteProgressRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def get(self, user_id: int) -> ProgressRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT progress_json,updated_at FROM user_progress WHERE user_id=?", (user_id,)
            ).fetchone()
        return ProgressRecord(json.loads(row["progress_json"]), row["updated_at"]) if row else None

    def save(self, user_id: int, document: dict[str, Any], updated_at: int) -> None:
        encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        with closing(self._connect()) as database:
            try:
                database.execute(
                    """INSERT INTO user_progress(user_id,progress_json,updated_at) VALUES (?,?,?)
                       ON CONFLICT(user_id) DO UPDATE SET progress_json=excluded.progress_json,
                       updated_at=excluded.updated_at""",
                    (user_id, encoded, updated_at),
                )
                database.commit()
            except BaseException:
                database.rollback()
                raise
```

- [x] Run repository and service suites, observe GREEN. Run `make check` before committing with `refactor: add sqlite progress repository`.

## Task 3: API Cutover, Dead-Code Removal and Regression Gates

**Files:** Rename route/controller groups modules; modify runtime, main, architecture docs and tests listed in the file map.

**Interfaces:** Consumes Tasks 1–2. Produces `runtime.progress_service() -> ProgressService`, transport functions `progress_get(user)` / `progress_put(payload, user)`, unchanged GET/PUT endpoints.

- [x] Add `tests/unit/test_progress_controller.py` before the renamed module exists. Use these transport assertions:

```python
import unittest
from unittest.mock import Mock, patch

from trainer.api import runtime
from trainer.api.controllers import progress
from trainer.api.errors import ApiError
from trainer.api.schemas import ProgressRequest
from trainer.services.progress import ProgressError
from trainer.services.progress_repository import ProgressRecord


class ProgressControllerTest(unittest.TestCase):
    def test_transport_results_and_delegation(self):
        service = Mock()
        payload = ProgressRequest(progress={"version": 1})
        with patch.object(runtime, "progress_service", return_value=service):
            service.get.return_value = None
            self.assertEqual(progress.progress_get({"id": 7}).payload, {"progress": None, "updatedAt": None})
            service.get.return_value = ProgressRecord(payload.progress, 1000)
            self.assertEqual(progress.progress_get({"id": 7}).payload, {"progress": payload.progress, "updatedAt": 1000})
            service.get.assert_called_with(7)
            service.put.return_value = 1001
            result = progress.progress_put(payload, {"id": 7})
            self.assertEqual((result.status, result.payload), (200, {"ok": True, "updatedAt": 1001}))
            service.put.assert_called_once_with(7, payload.progress)

    def test_semantic_errors_keep_http_contract(self):
        service = Mock()
        with patch.object(runtime, "progress_service", return_value=service):
            for reason, message in (("invalid_document", "Invalid progress document"),
                                    ("history_too_large", "Progress history is too large")):
                service.put.side_effect = ProgressError(reason)
                with self.assertRaises(ApiError) as raised:
                    progress.progress_put(ProgressRequest(progress={}), {"id": 7})
                self.assertEqual((raised.exception.status, raised.exception.code, raised.exception.message),
                                 (400, "invalid_request", message))
            unexpected = ProgressError("unexpected")
            service.put.side_effect = unexpected
            with self.assertRaises(ProgressError) as raised:
                progress.progress_put(ProgressRequest(progress={}), {"id": 7})
            self.assertIs(raised.exception, unexpected)
```

- [x] Add the following methods to existing `ApiFlowTest` in `tests/integration/test_api_flows.py`; existing helpers supply sessions, origin headers and temporary SQLite. Keep `test_legacy_assignment_routes_are_not_active` unchanged.

```python
def test_progress_round_trip_replacement_and_isolation(self):
    student = self.register_student("progress-one")
    other = self.register_student("progress-two")
    status, empty, _ = self.request("GET", "/api/progress", cookie=student)
    self.assertEqual((status, empty), (200, {"progress": None, "updatedAt": None}))
    document = {"version": 1, "runs": [None] * 200, "extra": "中文", "updatedAt": "client"}
    status, saved, _ = self.request("PUT", "/api/progress", {"progress": document}, student)
    self.assertEqual(status, 200, saved)
    self.assertEqual(set(saved), {"ok", "updatedAt"})
    self.assertIs(saved["ok"], True)
    self.assertIsInstance(saved["updatedAt"], int)
    status, loaded, _ = self.request("GET", "/api/progress", cookie=student)
    self.assertEqual((status, loaded), (200, {"progress": document, "updatedAt": saved["updatedAt"]}))
    self.assertEqual(self.request("GET", "/api/progress", cookie=other)[1], {"progress": None, "updatedAt": None})
    for version in (1, True, 1.0):
        replacement = {"version": version}
        self.assertEqual(self.request("PUT", "/api/progress", {"progress": replacement}, student)[0], 200)
        self.assertEqual(self.request("GET", "/api/progress", cookie=student)[1]["progress"], replacement)

def test_progress_invalid_input_does_not_replace_saved_history(self):
    student = self.register_student("progress-validation")
    original = {"version": 1, "runs": []}
    self.assertEqual(self.request("PUT", "/api/progress", {"progress": original}, student)[0], 200)
    cases = (({}, "Invalid progress document"), ({"version": "1"}, "Invalid progress document"),
             ({"version": 1, "runs": None}, "Progress history is too large"),
             ({"version": 1, "runs": [None] * 201}, "Progress history is too large"))
    for document, message in cases:
        status, error, _ = self.request("PUT", "/api/progress", {"progress": document}, student)
        self.assertEqual((status, error["code"], error["message"]), (400, "invalid_request", message))
    for payload in ({}, {"progress": []}, {"progress": original, "extra": 1}):
        self.assertEqual(self.request("PUT", "/api/progress", payload, student)[0], 422)
    self.assertEqual(self.request("GET", "/api/progress", cookie=student)[1]["progress"], original)

def test_progress_auth_and_role_restrictions_remain(self):
    owner = self.verified_owner_cookie()
    for method in ("GET", "PUT"):
        payload = {"progress": {"version": 1}} if method == "PUT" else None
        self.assertEqual(self.request(method, "/api/progress", payload)[0], 401)
        self.assertEqual(self.request(method, "/api/progress", payload, owner)[0], 403)
```

- [x] Add this test to `ArchitectureBoundaryTest`, using its existing `PACKAGE` and `file_imports` helpers:

```python
def test_progress_boundary_and_retired_names(self):
    for area in ("controllers", "routes"):
        self.assertFalse((PACKAGE / "api" / area / "groups.py").exists())
    controller = PACKAGE / "api" / "controllers" / "progress.py"
    source = controller.read_text(encoding="utf-8")
    for token in (".execute(", "connect", "import json", "import time", "trainer.infrastructure", "trainer.domain"):
        self.assertNotIn(token, source)
    for relative in ("domain/progress.py", "services/progress.py", "services/progress_repository.py"):
        imports = file_imports(PACKAGE / relative)
        self.assertFalse(any(item.startswith(("trainer.api", "trainer.infrastructure", "sqlite3")) for item in imports))
    runtime_source = (PACKAGE / "api" / "runtime.py").read_text(encoding="utf-8")
    self.assertNotIn("GROUP_CODE_ALPHABET", runtime_source)
    self.assertNotIn("EMAIL_RE", runtime_source)
```

- [x] Run controller and architecture tests, observe RED for absent modules/runtime factory and retained groups names. Run the new API tests against the old implementation to establish compatible baseline behavior before cutover.
- [x] Replace the old controller with `api/controllers/progress.py` using this complete transport implementation:

```python
from trainer.api import runtime
from trainer.api.errors import ApiError
from trainer.api.results import ActionResult
from trainer.api.schemas import ProgressRequest
from trainer.services.progress import ProgressError

_MESSAGES = {"invalid_document": "Invalid progress document", "history_too_large": "Progress history is too large"}


def progress_get(user: dict) -> ActionResult:
    record = runtime.progress_service().get(user["id"])
    return ActionResult({"progress": record.document if record is not None else None,
                         "updatedAt": record.updated_at if record is not None else None})


def progress_put(payload: ProgressRequest, user: dict) -> ActionResult:
    try:
        updated_at = runtime.progress_service().put(user["id"], payload.progress)
    except ProgressError as error:
        message = _MESSAGES.get(error.reason)
        if message is None:
            raise
        raise ApiError("invalid_request", message, 400) from error
    return ActionResult({"ok": True, "updatedAt": updated_at})
```

- [x] Move the route module with `apply_patch` Move-to support, changing its controller import to `from trainer.api.controllers import progress as actions`. Preserve its remaining contents. In main replace the router import name `groups` with `progress` and registration with `app.include_router(progress.router)`.
- [x] In runtime import `SQLiteProgressRepository` and `ProgressService` from their defined modules; add the factory below. Delete only `EMAIL_RE`, `GROUP_CODE_ALPHABET`, and the now-unused `import re`.

```python
def progress_service() -> ProgressService:
    return ProgressService(SQLiteProgressRepository(connect))
```

- [x] Add `ProgressServiceRuntimeTest` to `tests/unit/test_application_services.py` using existing Mock/patch/runtime/unittest imports:

```python
class ProgressServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_uncached_repository_without_external_services(self):
        repository, service = object(), object()
        with (patch.object(runtime, "SQLiteProgressRepository", return_value=repository) as repository_type,
              patch.object(runtime, "ProgressService", return_value=service) as service_type,
              patch.object(runtime, "storage_from_env") as storage_factory,
              patch.object(runtime, "MailAccountLinkSender") as mail_sender):
            self.assertIs(runtime.progress_service(), service)
            self.assertIs(runtime.progress_service(), service)
        self.assertEqual(repository_type.call_count, 2)
        self.assertEqual(service_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        service_type.assert_called_with(repository)
        storage_factory.assert_not_called()
        mail_sender.assert_not_called()
```

- [x] Add this section to `docs/architecture.md` alongside other vertical boundaries:

```markdown
### Вертикальная граница прогресса

Маршруты `/api/progress` вызывают transport-only controller и `ProgressService`.
Правила версии документа и лимита истории находятся в `domain/progress.py`;
`ProgressRepository` связывает сервис с `SQLiteProgressRepository`, который владеет
JSON persistence и транзакциями. Успешный PUT возвращается только после commit.

Сервер хранит документ целиком без merge и сравнения клиентского времени. Объединение
локальной и серверной истории остаётся в браузере. Старые API-модули `groups` удалены;
исторические таблицы групп, назначений и submissions сохранены без изменений.
```

- [x] Run `.venv/bin/python -m unittest tests.unit.test_progress_service tests.unit.test_progress_controller tests.unit.test_application_services tests.unit.test_architecture_boundaries tests.integration.test_progress_repository tests.integration.test_api_flows -v` and observe GREEN. Run Ruff formatting only on changed Python files when needed.
- [x] Inspect `git diff --check` and active imports with `rg -n 'GROUP_CODE_ALPHABET|EMAIL_RE|groups\.router|controllers import groups' src tests`. The remaining domain accounts `EMAIL_RE` is expected; no active groups route/controller reference is allowed. Historical docs remain unchanged.
- [x] Run fresh `make check`. UI is unchanged, so no additional Playwright run is required by AGENTS. Commit the coherent cutover with `refactor: route progress through service boundary`.
- [ ] Use `requesting-code-review` for the complete branch diff against its main fork point. Fix any real important findings through regression tests; rerun `make check` after code corrections. Do not merge or push without user authorization. Use `finishing-a-development-branch` for integration handoff.

## Plan Self-Review and Handoff

- [x] Spec coverage: Task 1 covers validation and service semantics; Task 2 covers durable storage and historical JSON; Task 3 covers API, composition, removed names, authorization and documentation.
- [x] Interfaces agree across tasks: `ProgressRecord.document/updated_at`, repository `get/save`, service `get/put`, service factory `progress_service`.
- [x] No dependency additions, migrations, frontend edits, server merge, broader cleanup or deletion of compatibility data.
- [x] Concrete RED/GREEN commands and fixtures provided; existing application remains usable until atomic route/controller cutover.
- [x] User selected sequential inline execution without implementation subagents and approved isolation. Worktree: `.worktrees/progress-service-boundary`, branch: `codex/progress-service-boundary`.
