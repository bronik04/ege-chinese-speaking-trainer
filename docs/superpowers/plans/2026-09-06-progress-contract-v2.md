# Progress Contract V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the permissive progress V1 document with a strict canonical V2 contract while automatically preserving valid server-side and browser-local V1 progress.

**Architecture:** Pure domain dataclasses and parsers own V2 invariants and tolerant V1 migration; Pydantic mirrors the strict V2 shape at the HTTP boundary. `ProgressService` normalizes repository reads and writes, the SQLite adapter reports unreadable documents through a neutral port error, and frontend storage performs the same migration using shared cross-language fixtures.

**Tech Stack:** Python 3, dataclasses, Pydantic v2, FastAPI, SQLite, vanilla JavaScript, Node test runner and Playwright; no new dependencies and no database migration.

**Spec:** docs/superpowers/specs/2026-09-06-progress-contract-v2-design.md

## Global Constraints

- Limit this stage to the progress document. Do not tighten `ReviewRequestCreate.run` or `MaterialRequest.content`.
- Preserve `GET /api/progress`, `PUT /api/progress`, student-only authorization, response envelopes and the separate integer server `updatedAt`.
- Persist and return only canonical V2 after a successful PUT; normalize stored V1 on GET without writing it back.
- On Python/API boundaries recognize V1 only when `type(version) is int` and `version == 1`; reject `true`, `1.0`, strings and unknown versions. Browser code uses `Number.isInteger` because parsed JavaScript numbers do not preserve the lexical difference between `1` and `1.0`.
- Strict V2 forbids unknown fields and coercion at every level. New invalid V2 requests return HTTP 422 with code `request_validation_failed`.
- For a transport-recognized `version: 1`, semantic root/history errors return HTTP 400 `invalid_request`; more than 200 legacy runs remains `history_too_large`. Missing, wrongly typed or unknown version discriminators return the standard 422.
- A corrupt or unsupported stored server document returns HTTP 409 `progress_data_incompatible` and is never overwritten by GET.
- Canonical history contains at most 100 unique run IDs. Legacy migration keeps the first valid duplicate; frontend merge gives a duplicate's local copy priority and sorts newest first.
- Canonical timestamps are timezone-aware RFC 3339 values serialized in UTC with `Z` and milliseconds.
- Migrate both `egeChineseProgressV1` and `egeChineseProgressV1:user:<id>` only after successfully writing the corresponding V2 key.
- Do not add or edit an Alembic revision. Preserve the `user_progress` table.
- Use test-first RED/GREEN cycles and a focused commit after every task.
- Run fresh `make check` and `make test-e2e` before completion.
- Preserve the user's untracked `.superpowers/brainstorm/` and unrelated worktrees. Use an isolated worktree when execution starts.

---

## File Map

- Modify `src/trainer/domain/progress.py`: immutable V2 models, strict parser, canonical serializer and tolerant V1 migration.
- Create `tests/fixtures/progress_v1_migration_cases.json`: successful and failing cross-language migration examples.
- Create `tests/unit/test_progress_domain.py`: pure contract and migration tests.
- Modify `src/trainer/services/progress_repository.py`: narrow document type and neutral corrupt-data error.
- Modify `src/trainer/infrastructure/database/progress_repository.py`: translate unreadable/non-object JSON into the port error.
- Modify `src/trainer/services/progress.py`: lazy GET migration and canonical PUT persistence.
- Modify `tests/unit/test_progress_service.py` and `tests/integration/test_progress_repository.py`: service/repository behavior.
- Modify `src/trainer/api/schemas.py`: discriminated V1 compatibility input and strict nested V2 transport models.
- Modify `src/trainer/api/controllers/progress.py`: serialize input models and map stored incompatibility to 409.
- Modify `tests/unit/test_progress_controller.py` and `tests/integration/test_api_flows.py`: HTTP contracts and migration round trips.
- Rewrite `frontend/js/shared/progress.js`: V2 constants, strict parser, V1 migration, safe localStorage migration and V2 merge.
- Create `tests-js/unit/progress.test.js`: fixture parity, storage safety and merge tests.
- Modify `tests-js/unit/views.test.js`: remove old V1 merge tests now owned by the focused progress suite.
- Modify `frontend/js/runner/app.js`: use scoped V2/V1 keys and safe guest/account adoption.
- Modify `frontend/js/account/account-auth-controller.js`: report incompatible server progress without losing the local copy.
- Create `tests-e2e/progress-migration.spec.js`: real guest V1 migration and continued-use scenario.
- Modify `docs/architecture.md`: document the V2 contract and lazy migration boundary.

## Task 1: Domain Contract and Shared V1 Migration Fixtures

**Files:**
- Create: `tests/fixtures/progress_v1_migration_cases.json`
- Create: `tests/unit/test_progress_domain.py`
- Modify: `src/trainer/domain/progress.py`

**Interfaces:**
- Produces immutable `ProgressSettings`, `ProgressRun`, `CompletedProgressRun` and `ProgressDocument` dataclasses.
- Produces `normalize_progress(document: object) -> ProgressDocument` for exact V1/V2 dispatch.
- Produces `progress_to_dict(document: ProgressDocument) -> dict[str, object]` with browser field names.
- Produces `ProgressValidationError(reason)` where reasons used by this stage are `invalid_document` and `history_too_large`.
- The JSON fixture root is `{"cases": [...]}`; each case has `name`, `input`, and exactly one of `expected` or `expectedError`.

- [ ] **Step 1: Create shared migration fixtures**

Create `tests/fixtures/progress_v1_migration_cases.json` with these literal cases; keep all timestamps in the expected canonical millisecond form:

```json
{
  "cases": [
    {
      "name": "missing optional fields use defaults",
      "input": {"version": 1},
      "expected": {
        "version": 2,
        "updatedAt": "1970-01-01T00:00:00.000Z",
        "settings": {"lastVariant": null, "fastMode": false},
        "runs": [],
        "activeRun": null
      }
    },
    {
      "name": "valid completed run survives and unknown fields disappear",
      "input": {
        "version": 1,
        "updatedAt": "2026-09-06T10:15:30+00:00",
        "settings": {"lastVariant": "open-2026", "fastMode": true, "old": 1},
        "runs": [{
          "id": "run-1", "variantId": "open-2026", "variantLabel": "Открытый вариант 2026",
          "mode": "practice", "tasks": [2], "completedTasks": [2], "currentTask": 2,
          "phase": "answer", "fastMode": true, "startedAt": "2026-09-06T10:00:00Z",
          "status": "completed", "completedAt": "2026-09-06T10:05:00Z", "recordingsCount": 1,
          "legacy": "drop"
        }],
        "activeRun": null,
        "unknown": "drop"
      },
      "expected": {
        "version": 2,
        "updatedAt": "2026-09-06T10:15:30.000Z",
        "settings": {"lastVariant": "open-2026", "fastMode": true},
        "runs": [{
          "id": "run-1", "variantId": "open-2026", "variantLabel": "Открытый вариант 2026",
          "mode": "practice", "tasks": [2], "completedTasks": [2], "currentTask": 2,
          "phase": "answer", "fastMode": true, "startedAt": "2026-09-06T10:00:00.000Z",
          "status": "completed", "completedAt": "2026-09-06T10:05:00.000Z", "recordingsCount": 1
        }],
        "activeRun": null
      }
    },
    {
      "name": "bad nested entries are salvaged independently",
      "input": {
        "version": 1,
        "updatedAt": "not-a-date",
        "settings": {"lastVariant": 7, "fastMode": "yes"},
        "runs": [null, {"id": "broken"}],
        "activeRun": {"id": "broken"}
      },
      "expected": {
        "version": 2,
        "updatedAt": "1970-01-01T00:00:00.000Z",
        "settings": {"lastVariant": null, "fastMode": false},
        "runs": [],
        "activeRun": null
      }
    },
    {"name": "boolean is not version one", "input": {"version": true}, "expectedError": "invalid_document"},
    {"name": "unknown version is rejected", "input": {"version": 3}, "expectedError": "invalid_document"}
  ]
}
```

- [ ] **Step 2: Write failing domain tests**

Create `tests/unit/test_progress_domain.py`. Load the fixture relative to `Path(__file__).parents[1]`, then assert successful cases and exact error reasons:

```python
import copy
import json
import unittest
from pathlib import Path

from trainer.domain.progress import ProgressValidationError, normalize_progress, progress_to_dict


FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "progress_v1_migration_cases.json").read_text(encoding="utf-8")
)["cases"]


class ProgressDomainTest(unittest.TestCase):
    def test_shared_v1_migration_cases(self):
        for case in FIXTURES:
            with self.subTest(case=case["name"]):
                source = copy.deepcopy(case["input"])
                if reason := case.get("expectedError"):
                    with self.assertRaises(ProgressValidationError) as raised:
                        normalize_progress(source)
                    self.assertEqual(raised.exception.reason, reason)
                else:
                    self.assertEqual(progress_to_dict(normalize_progress(source)), case["expected"])
                self.assertEqual(source, case["input"])
```

Add a Python-only assertion that `{"version": 1.0}` raises `invalid_document`. Add literal V2 helpers inside the test module and tests that mutate one property at a time. The base run must contain all fields shown in the fixture. Assert rejection for an extra root/settings/run field, string/boolean task numbers, duplicate run IDs, duplicate tasks, `currentTask` outside `tasks`, `completedTasks` outside `tasks`, invalid mode/phase/status, completed-before-started timestamps, `recordingsCount` values `-1`, `101`, `true`, a completed run missing one task, and 101 V2 runs. Assert that unique unsorted task lists are accepted and serialized in ascending order. Assert valid active, completed and interrupted examples serialize exactly with canonical timestamps.

Use this mutation pattern so every rejected case asserts the machine reason and input immutability:

```python
def completed_run(run_id="run-1"):
    return {
        "id": run_id,
        "variantId": "open-2026",
        "variantLabel": "Открытый вариант 2026",
        "mode": "practice",
        "tasks": [2],
        "completedTasks": [2],
        "currentTask": 2,
        "phase": "answer",
        "fastMode": False,
        "startedAt": "2026-09-06T10:00:00Z",
        "status": "completed",
        "completedAt": "2026-09-06T10:05:00Z",
        "recordingsCount": 1,
    }


def valid_v2():
    return {
        "version": 2,
        "updatedAt": "2026-09-06T10:15:30Z",
        "settings": {"lastVariant": "open-2026", "fastMode": False},
        "runs": [completed_run()],
        "activeRun": None,
    }


def assert_invalid(self, document, reason="invalid_document"):
    original = copy.deepcopy(document)
    with self.assertRaises(ProgressValidationError) as raised:
        normalize_progress(document)
    self.assertEqual(raised.exception.reason, reason)
    self.assertEqual(document, original)

def test_v2_rejects_duplicate_run_ids(self):
    document = valid_v2()
    document["runs"] = [completed_run("same"), completed_run("same")]
    self.assert_invalid(document)

def test_v2_sorts_unique_task_numbers(self):
    document = valid_v2()
    run = completed_run("exam")
    run.update(tasks=[3, 1, 2], completedTasks=[2, 3, 1], currentTask=3, mode="exam")
    document["runs"] = [run]
    result = progress_to_dict(normalize_progress(document))["runs"][0]
    self.assertEqual(result["tasks"], [1, 2, 3])
    self.assertEqual(result["completedTasks"], [1, 2, 3])
```

- [ ] **Step 3: Run domain tests to observe RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_domain -v
```

Expected: import errors for `normalize_progress` and `progress_to_dict`.

- [ ] **Step 4: Implement immutable models and strict helpers**

Replace `src/trainer/domain/progress.py` with frozen dataclasses and explicit field sets. Use these public shapes and constants:

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

TaskNumber = Literal[1, 2, 3]
Mode = Literal["exam", "practice"]
Phase = Literal["idle", "prep", "answer"]
RunStatus = Literal["completed", "interrupted"]

ROOT_FIELDS = frozenset({"version", "updatedAt", "settings", "runs", "activeRun"})
SETTINGS_FIELDS = frozenset({"lastVariant", "fastMode"})
RUN_FIELDS = frozenset({
    "id", "variantId", "variantLabel", "mode", "tasks", "completedTasks",
    "currentTask", "phase", "fastMode", "startedAt",
})
COMPLETED_FIELDS = RUN_FIELDS | {"status", "completedAt", "recordingsCount"}
EPOCH = "1970-01-01T00:00:00.000Z"
```

Dataclass fields must follow the JSON fields in the spec, using snake_case internally. `ProgressDocument.runs` is `tuple[CompletedProgressRun, ...]`, and `active_run` is `ProgressRun | None`.

```python
@dataclass(frozen=True)
class ProgressSettings:
    last_variant: str | None
    fast_mode: bool


@dataclass(frozen=True)
class ProgressRun:
    id: str
    variant_id: str
    variant_label: str
    mode: Mode
    tasks: tuple[TaskNumber, ...]
    completed_tasks: tuple[TaskNumber, ...]
    current_task: TaskNumber
    phase: Phase
    fast_mode: bool
    started_at: str


@dataclass(frozen=True)
class CompletedProgressRun(ProgressRun):
    status: RunStatus
    completed_at: str
    recordings_count: int


@dataclass(frozen=True)
class ProgressDocument:
    updated_at: str
    settings: ProgressSettings
    runs: tuple[CompletedProgressRun, ...]
    active_run: ProgressRun | None
    version: Literal[2] = 2
```

Implement exact-type helpers (`type(value) is int`, `type(value) is bool`, `type(value) is str`), bounded strings, unique ascending task tuples, subset checks and RFC 3339 parsing. Timestamp formatting must be:

```python
def _timestamp(value: object) -> tuple[str, datetime]:
    if type(value) is not str:
        raise ProgressValidationError("invalid_document")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ProgressValidationError("invalid_document") from error
    if parsed.tzinfo is None:
        raise ProgressValidationError("invalid_document")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"), utc
```

Dispatch without equality coercion:

```python
def normalize_progress(document: object) -> ProgressDocument:
    if type(document) is not dict:
        raise ProgressValidationError("invalid_document")
    version = document.get("version")
    if type(version) is not int:
        raise ProgressValidationError("invalid_document")
    if version == 1:
        return _migrate_v1(document)
    if version == 2:
        return _parse_v2(document)
    raise ProgressValidationError("invalid_document")
```

For `_parse_v2`, require exact field sets, reject more than 100 runs and duplicate run IDs, sort unique task lists, and validate every nested object. For `_migrate_v1`, default fields as in the fixture, reject a non-list `runs`, reject 201 entries with `history_too_large`, catch `ProgressValidationError` around each run and active run independently, discard unknown fields, keep the first duplicate ID, slice at 100, and pass the generated dictionary through `_parse_v2` before returning. `progress_to_dict` must build fresh dictionaries/lists and preserve the field order from the canonical example.

- [ ] **Step 5: Run the domain tests to GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_domain -v
```

Expected: all progress domain tests pass.

- [ ] **Step 6: Commit the domain contract**

```bash
git add src/trainer/domain/progress.py tests/unit/test_progress_domain.py tests/fixtures/progress_v1_migration_cases.json
git commit -m "feat: define strict progress v2 domain contract"
```

## Task 2: Service Normalization and Repository Corruption Boundary

**Files:**
- Modify: `src/trainer/services/progress_repository.py`
- Modify: `src/trainer/infrastructure/database/progress_repository.py`
- Modify: `src/trainer/services/progress.py`
- Modify: `tests/unit/test_progress_service.py`
- Modify: `tests/integration/test_progress_repository.py`

**Interfaces:**
- Consumes `normalize_progress` and `progress_to_dict` from Task 1.
- Produces `ProgressDataError` for decoded storage that cannot represent a progress object.
- `ProgressRecord.document` becomes `dict[str, object]`.
- `ProgressService.get(user_id)` returns `None` or a new `ProgressRecord` whose document is canonical V2.
- `ProgressService.put(user_id, document)` accepts `dict[str, object]`, persists a fresh canonical V2 dict and returns integer server time.
- Produces `ProgressError("stored_document_invalid")` only for corrupt/unsupported stored data; ordinary database failures still propagate.

- [ ] **Step 1: Rewrite service tests for lazy migration and canonical persistence**

Replace the obsolete permissive-domain tests in `tests/unit/test_progress_service.py` with service-focused cases:

```python
import copy
import unittest
from unittest.mock import Mock

from trainer.services.progress import ProgressError, ProgressService
from trainer.services.progress_repository import ProgressDataError, ProgressRecord


class ProgressServiceTest(unittest.TestCase):
    def test_get_migrates_v1_without_saving(self):
        repository = Mock()
        source = {"version": 1, "extra": "drop"}
        repository.get.return_value = ProgressRecord(source, 1000)
        result = ProgressService(repository).get(7)
        self.assertEqual(result.document["version"], 2)
        self.assertNotIn("extra", result.document)
        self.assertEqual(result.updated_at, 1000)
        repository.save.assert_not_called()
        self.assertEqual(source, {"version": 1, "extra": "drop"})

    def test_put_persists_only_a_fresh_canonical_v2_document(self):
        repository = Mock()
        source = {"version": 1}
        service = ProgressService(repository, clock=lambda: 1000.9)
        self.assertEqual(service.put(7, source), 1000)
        saved = repository.save.call_args.args[1]
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["runs"], [])
        self.assertIsNot(saved, source)
        repository.save.assert_called_once_with(7, saved, 1000)

    def test_get_maps_only_stored_contract_failures(self):
        repository = Mock()
        service = ProgressService(repository)
        for failure in (ProgressDataError("bad json"), ProgressRecord({"version": 9}, 1000)):
            repository.get.side_effect = failure if isinstance(failure, Exception) else None
            repository.get.return_value = None if isinstance(failure, Exception) else failure
            with self.assertRaises(ProgressError) as raised:
                service.get(7)
            self.assertEqual(raised.exception.reason, "stored_document_invalid")

        repository.get.side_effect = OSError("storage down")
        with self.assertRaisesRegex(OSError, "storage down"):
            service.get(7)
```

Retain explicit tests that invalid PUT does not call clock/repository, `get` returns `None`, and save failures propagate.

- [ ] **Step 2: Extend repository integration tests for neutral corruption errors**

In `tests/integration/test_progress_repository.py`, replace `test_historical_json_is_not_normalized_and_bad_json_raises` with:

```python
def test_bad_json_and_non_object_roots_raise_progress_data_error(self):
    for encoded in ("not-json", "[]", "null"):
        with self.subTest(encoded=encoded), closing(self.connect()) as database, database:
            database.execute(
                "INSERT INTO user_progress(user_id,progress_json,updated_at) VALUES (1,?,1000) "
                "ON CONFLICT(user_id) DO UPDATE SET progress_json=excluded.progress_json",
                (encoded,),
            )
        with self.assertRaises(ProgressDataError):
            self.repository.get(1)
```

Update round-trip fixtures to canonical V2 dictionaries and retain commit, rollback, Unicode and user-isolation assertions.

- [ ] **Step 3: Run focused tests to observe RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_service tests.integration.test_progress_repository -v
```

Expected: missing `ProgressDataError` and old pass-through behavior failures.

- [ ] **Step 4: Add the port error and safe SQLite decoding**

In `src/trainer/services/progress_repository.py` add:

```python
class ProgressDataError(ValueError):
    pass
```

Narrow `ProgressRecord.document` and `save` to `dict[str, object]`. In the SQLite adapter, decode before constructing the record and translate only JSON/type corruption:

```python
try:
    document = json.loads(row["progress_json"])
except (json.JSONDecodeError, TypeError) as error:
    raise ProgressDataError("Stored progress JSON is unreadable") from error
if type(document) is not dict:
    raise ProgressDataError("Stored progress root is not an object")
return ProgressRecord(document, row["updated_at"])
```

Do not catch SQLite errors. Keep compact Unicode serialization and existing transaction behavior.

- [ ] **Step 5: Normalize both service directions**

In `src/trainer/services/progress.py`, remove `Any` and `validate_progress`. Add a private conversion:

```python
def _canonical(document: object) -> dict[str, object]:
    return progress_to_dict(normalize_progress(document))
```

`get` catches `ProgressDataError` around repository access, then catches `ProgressValidationError` around `_canonical(record.document)`; both become `ProgressError("stored_document_invalid")`. Return a new `ProgressRecord` with the same repository timestamp. `put` converts domain errors to their existing reasons, calls the clock only after successful normalization, and saves only the canonical dictionary.

- [ ] **Step 6: Run focused tests to GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_service tests.integration.test_progress_repository -v
```

Expected: all service and repository tests pass.

- [ ] **Step 7: Commit the application/storage boundary changes**

```bash
git add src/trainer/services/progress.py src/trainer/services/progress_repository.py \
  src/trainer/infrastructure/database/progress_repository.py \
  tests/unit/test_progress_service.py tests/integration/test_progress_repository.py
git commit -m "feat: normalize progress at service boundary"
```

## Task 3: Strict Pydantic Transport and HTTP Error Contracts

**Files:**
- Modify: `src/trainer/api/schemas.py`
- Modify: `src/trainer/api/controllers/progress.py`
- Modify: `tests/unit/test_progress_controller.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Consumes canonical domain validation from Task 1 and service errors from Task 2.
- Produces `ProgressV1`, `ProgressSettings`, `ActiveRun`, `CompletedRun`, `ProgressV2` and discriminated `ProgressPayload` transport types.
- `ProgressRequest.progress` is a `ProgressV1 | ProgressV2` model, not a free dictionary.
- Controller serializes it with `model_dump(mode="json", by_alias=True)` before calling the service.
- Produces HTTP 409 code `progress_data_incompatible` for `ProgressError("stored_document_invalid")` on GET.

- [ ] **Step 1: Update controller unit tests before production code**

In `tests/unit/test_progress_controller.py`, use `ProgressRequest(progress={"version": 1})`, but compare service input to a dictionary rather than `payload.progress`. Add a GET error case:

```python
service.get.side_effect = ProgressError("stored_document_invalid")
with self.assertRaises(ApiError) as raised:
    progress.progress_get({"id": 7})
self.assertEqual(
    (raised.exception.status, raised.exception.code, raised.exception.message),
    (409, "progress_data_incompatible", "Сохранённый прогресс имеет несовместимый формат"),
)
```

Keep PUT semantic mappings by making the service raise after receiving the valid V1 payload. Assert unknown service reasons still re-raise unchanged.

- [ ] **Step 2: Rewrite API flow expectations**

In `tests/integration/test_api_flows.py`:

- add `import copy` beside the existing `json`/`Path` imports;

- PUT the valid V1 fixture from Task 1 and assert GET returns its exact expected V2 document;
- PUT that V2 document again and assert an exact V2 round trip;
- assert missing version, `version: true`, `version: 1.0`, `version: "1"`, unknown version, extra V2 root/settings/run fields, string task numbers and invalid run relationships return 422 with `request_validation_failed`;
- assert recognized V1 with non-list runs returns 400 `Invalid progress document`, and 201 legacy runs returns 400 `Progress history is too large`, without replacing the prior saved V2;
- insert `not-json`, `[]` and `{"version":9}` directly into `user_progress` for separate students, then assert GET returns 409/code `progress_data_incompatible` and the stored bytes remain unchanged;
- retain empty GET, replacement, isolation, auth and role assertions.

Use a valid completed run dictionary copied literally from `tests/fixtures/progress_v1_migration_cases.json`; do not use `[None] * 200` as a successful document.

The central round-trip assertion should have this form:

```python
legacy = json.loads(
    (Path(__file__).parents[2] / "tests" / "fixtures" / "progress_v1_migration_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"][1]
status, saved, _ = self.request("PUT", "/api/progress", {"progress": legacy["input"]}, student)
self.assertEqual(status, 200, saved)
status, loaded, _ = self.request("GET", "/api/progress", cookie=student)
self.assertEqual(loaded["progress"], legacy["expected"])
self.assertEqual(loaded["updatedAt"], saved["updatedAt"])
```

For request validation, iterate exact status/code pairs:

```python
bad_extra = copy.deepcopy(legacy["expected"])
bad_extra["settings"]["extra"] = True
bad_task = copy.deepcopy(legacy["expected"])
bad_task["runs"][0]["tasks"] = ["2"]
bad_relationship = copy.deepcopy(legacy["expected"])
bad_relationship["runs"][0]["currentTask"] = 3
for invalid_v2 in (
    {},
    {"version": True},
    {"version": 1.0},
    {"version": "1"},
    {"version": 9},
    bad_extra,
    bad_task,
    bad_relationship,
    {**legacy["expected"], "version": 2.0},
):
    status, error, _ = self.request("PUT", "/api/progress", {"progress": invalid_v2}, student)
    self.assertEqual((status, error["code"]), (422, "request_validation_failed"))
for invalid_v1, message in (
    ({"version": 1, "runs": None}, "Invalid progress document"),
    ({"version": 1, "runs": [None] * 201}, "Progress history is too large"),
):
    status, error, _ = self.request("PUT", "/api/progress", {"progress": invalid_v1}, student)
    self.assertEqual((status, error["code"], error["message"]), (400, "invalid_request", message))
```

- [ ] **Step 3: Run controller/API tests to observe RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_controller \
  tests.integration.test_api_flows.ApiFlowTest.test_progress_round_trip_replacement_and_isolation \
  tests.integration.test_api_flows.ApiFlowTest.test_progress_invalid_input_does_not_replace_saved_history -v
```

Expected: V1 is still exposed unchanged and invalid V2 nested fields are accepted.

- [ ] **Step 4: Define discriminated schemas with strict V2 types**

In `src/trainer/api/schemas.py`, import `Annotated`, `StrictBool`, `StrictInt`, `StrictStr`, `model_validator`, and domain normalization. Add a strict base:

```python
class StrictProgressSchema(ApiSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
```

Define nested fields with the exact spec bounds. Use `list[Literal[1, 2, 3]]` with `Field(min_length=1, max_length=3)`, `Literal` for mode/phase/status, strict strings for timestamps, `StrictInt` for `recordingsCount`, and `ProgressV2.runs: list[CompletedRun] = Field(max_length=100)`. `ProgressV2` must validate the complete dumped dictionary through `normalize_progress`; convert `ProgressValidationError` to `ValueError(error.reason)` so FastAPI emits 422.

```python
class ProgressSettings(StrictProgressSchema):
    lastVariant: StrictStr | None = Field(default=None, min_length=1, max_length=80)
    fastMode: StrictBool


class ActiveRun(StrictProgressSchema):
    id: StrictStr = Field(min_length=1, max_length=120)
    variantId: StrictStr = Field(min_length=1, max_length=80)
    variantLabel: StrictStr = Field(min_length=1, max_length=160)
    mode: Literal["exam", "practice"]
    tasks: list[Literal[1, 2, 3]] = Field(min_length=1, max_length=3)
    completedTasks: list[Literal[1, 2, 3]] = Field(max_length=3)
    currentTask: Literal[1, 2, 3]
    phase: Literal["idle", "prep", "answer"]
    fastMode: StrictBool
    startedAt: StrictStr = Field(min_length=20, max_length=40)


class CompletedRun(ActiveRun):
    status: Literal["completed", "interrupted"]
    completedAt: StrictStr = Field(min_length=20, max_length=40)
    recordingsCount: StrictInt = Field(ge=0, le=100)


class ProgressV2(StrictProgressSchema):
    version: Literal[2]
    updatedAt: StrictStr = Field(min_length=20, max_length=40)
    settings: ProgressSettings
    runs: list[CompletedRun] = Field(max_length=100)
    activeRun: ActiveRun | None

    @model_validator(mode="after")
    def valid_domain_contract(self):
        try:
            normalize_progress(self.model_dump(mode="json", by_alias=True))
        except ProgressValidationError as error:
            raise ValueError(error.reason) from error
        return self
```

Define the permissive compatibility wrapper while rejecting coercion before parsing:

```python
class ProgressV1(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: Literal[1]

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not dict or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("version must be the integer 1")
        return value


ProgressPayload = Annotated[ProgressV1 | ProgressV2, Field(discriminator="version")]


class ProgressRequest(ApiSchema):
    progress: ProgressPayload
```

The V1 model declares only `version`; extra fields carry the untouched legacy payload to the service. Confirm with a direct schema test that `model_dump(mode="json", by_alias=True)` retains `runs`, settings and unknown legacy fields.

- [ ] **Step 5: Serialize payloads and map GET incompatibility**

In `src/trainer/api/controllers/progress.py`, create one mapping helper:

```python
def _raise_progress_error(error: ProgressError, *, reading: bool = False) -> None:
    if reading and error.reason == "stored_document_invalid":
        raise ApiError(
            "progress_data_incompatible",
            "Сохранённый прогресс имеет несовместимый формат",
            409,
        ) from error
    message = _MESSAGES.get(error.reason)
    if message is None:
        raise error
    raise ApiError("invalid_request", message, 400) from error
```

Wrap service GET as well as PUT. For PUT pass:

```python
document = payload.progress.model_dump(mode="json", by_alias=True)
updated_at = runtime.progress_service().put(user["id"], document)
```

- [ ] **Step 6: Run all progress Python tests to GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_progress_domain tests.unit.test_progress_service tests.unit.test_progress_controller \
  tests.integration.test_progress_repository tests.integration.test_api_flows.ApiFlowTest.test_progress_round_trip_replacement_and_isolation \
  tests.integration.test_api_flows.ApiFlowTest.test_progress_invalid_input_does_not_replace_saved_history \
  tests.integration.test_api_flows.ApiFlowTest.test_progress_auth_and_role_restrictions_remain -v
```

Expected: all selected tests pass with V2 responses and documented 400/409/422 codes.

- [ ] **Step 7: Commit the HTTP contract**

```bash
git add src/trainer/api/schemas.py src/trainer/api/controllers/progress.py \
  tests/unit/test_progress_controller.py tests/integration/test_api_flows.py
git commit -m "feat: enforce strict progress v2 api schema"
```

## Task 4: Browser Contract, Safe localStorage Migration and V2 Merge

**Files:**
- Modify: `frontend/js/shared/progress.js`
- Create: `tests-js/unit/progress.test.js`
- Modify: `tests-js/unit/views.test.js`

**Interfaces:**
- Consumes `tests/fixtures/progress_v1_migration_cases.json` in Node tests only.
- Produces constants `PROGRESS_GUEST_KEY`, `PROGRESS_ACCOUNT_PREFIX`, `LEGACY_PROGRESS_GUEST_KEY` and `LEGACY_PROGRESS_ACCOUNT_PREFIX`.
- Produces `progressStorageKeys(userId = null) -> { current, legacy }`.
- Produces `normalizeProgress(value)`, `defaultProgress()`, `loadLocalProgress(keys, options)` and V2-only `mergeProgress(local, remote)`.
- `loadLocalProgress` accepts `{ storage = localStorage, onError = () => {} }`, returns a V2 object, writes V2 before deleting V1 and never deletes a corrupt/newer V2 value.

- [ ] **Step 1: Write focused JavaScript tests**

Create `tests-js/unit/progress.test.js`. Read fixtures with `readFileSync(new URL("../../tests/fixtures/progress_v1_migration_cases.json", import.meta.url))`. For each case, deep-compare `normalizeProgress(input)` or assert `ProgressContractError.reason`.

Use this storage fake:

```javascript
function fakeStorage(entries = {}, { failSet = false } = {}) {
  const values = new Map(Object.entries(entries));
  const calls = [];
  return {
    calls,
    getItem(key) { calls.push(["get", key]); return values.has(key) ? values.get(key) : null; },
    setItem(key, value) {
      calls.push(["set", key]);
      if (failSet) throw new DOMException("quota", "QuotaExceededError");
      values.set(key, value);
    },
    removeItem(key) { calls.push(["remove", key]); values.delete(key); },
    value(key) { return values.get(key); },
  };
}
```

Add exact tests for:

- guest and user key names;
- successful V1 migration calls `set` for V2 before `remove` for V1;
- failed V2 write returns migrated in-memory data, invokes `onError`, and retains V1;
- valid existing V2 wins without reading/removing V1;
- corrupt existing V2 returns default, invokes `onError`, and leaves both stored strings untouched;
- strict V2 rejects unknown fields, coercions, duplicate IDs and invalid relationships;
- merge gives a duplicate's local value priority, chooses settings/activeRun from the newer `updatedAt`, sorts runs newest first and truncates to 100.

The migration-order and failed-write assertions must inspect calls, not only final values:

```javascript
test("local V1 is deleted only after V2 is stored", () => {
  const keys = progressStorageKeys();
  const storage = fakeStorage({ [keys.legacy]: JSON.stringify({ version: 1 }) });
  const result = loadLocalProgress(keys, { storage });
  assert.equal(result.version, 2);
  assert.deepEqual(storage.calls.slice(-2).map(call => call.slice(0, 2)), [
    ["set", keys.current],
    ["remove", keys.legacy],
  ]);
});

test("failed V2 write preserves V1 and returns the migrated in-memory copy", () => {
  const keys = progressStorageKeys(7);
  const storage = fakeStorage({ [keys.legacy]: JSON.stringify({ version: 1 }) }, { failSet: true });
  const errors = [];
  const result = loadLocalProgress(keys, { storage, onError: message => errors.push(message) });
  assert.equal(result.version, 2);
  assert.notEqual(storage.value(keys.legacy), undefined);
  assert.equal(storage.value(keys.current), undefined);
  assert.equal(errors.length, 1);
  assert.equal(storage.calls.some(call => call[0] === "remove"), false);
});
```

Move the two old V1 `mergeProgress` tests out of `tests-js/unit/views.test.js`; do not duplicate them.

- [ ] **Step 2: Run JavaScript tests to observe RED**

Run:

```bash
npm test -- --test-name-pattern="progress|migration|mergeProgress"
```

Expected: missing exports and V1 values from the old implementation.

- [ ] **Step 3: Implement the browser contract**

Rewrite `frontend/js/shared/progress.js` around these constants:

```javascript
export const PROGRESS_GUEST_KEY = "egeChineseProgressV2";
export const PROGRESS_ACCOUNT_PREFIX = `${PROGRESS_GUEST_KEY}:user:`;
export const LEGACY_PROGRESS_GUEST_KEY = "egeChineseProgressV1";
export const LEGACY_PROGRESS_ACCOUNT_PREFIX = `${LEGACY_PROGRESS_GUEST_KEY}:user:`;

export function progressStorageKeys(userId = null) {
  return userId == null
    ? { current: PROGRESS_GUEST_KEY, legacy: LEGACY_PROGRESS_GUEST_KEY }
    : { current: `${PROGRESS_ACCOUNT_PREFIX}${userId}`, legacy: `${LEGACY_PROGRESS_ACCOUNT_PREFIX}${userId}` };
}
```

Define `ProgressContractError` with a `reason` property. Mirror Task 1's exact-type, field-set, timestamp, task, run and migration rules. `new Date(value).toISOString()` provides the required UTC millisecond output, but reject non-string and invalid dates before calling it. Build new objects/arrays rather than mutating input. Strict V2 rejects duplicates; legacy migration catches individual run/active errors and keeps the first valid run ID.

Implement storage ordering explicitly:

```javascript
export function loadLocalProgress(keys, { storage = localStorage, onError = () => {} } = {}) {
  const currentRaw = storage.getItem(keys.current);
  if (currentRaw !== null) {
    try { return normalizeProgress(JSON.parse(currentRaw)); }
    catch (error) { onError("Сохранённый прогресс повреждён; исходная копия сохранена", error); return defaultProgress(); }
  }
  const legacyRaw = storage.getItem(keys.legacy);
  if (legacyRaw === null) return defaultProgress();
  let migrated;
  try { migrated = normalizeProgress(JSON.parse(legacyRaw)); }
  catch (error) { onError("Старый прогресс повреждён; исходная копия сохранена", error); return defaultProgress(); }
  try {
    storage.setItem(keys.current, JSON.stringify(migrated));
    storage.removeItem(keys.legacy);
  } catch (error) {
    onError("Не удалось перенести прогресс; старая копия сохранена", error);
  }
  return migrated;
}
```

`defaultProgress()` returns a fresh V2/epoch object. `mergeProgress` first normalizes both documents, returns local if remote is null, inserts remote then local runs into a Map so local overwrites duplicates, sorts by `completedAt || startedAt`, slices 100 and returns V2 with a current `updatedAt`.

- [ ] **Step 4: Run all JavaScript unit/lint checks to GREEN**

Run:

```bash
npm test
npm run lint:js
```

Expected: all JavaScript tests and ESLint pass.

- [ ] **Step 5: Commit the browser contract**

```bash
git add frontend/js/shared/progress.js tests-js/unit/progress.test.js tests-js/unit/views.test.js
git commit -m "feat: migrate browser progress to v2"
```

## Task 5: Runner/Account Integration and Browser Migration Scenario

**Files:**
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/js/account/account-auth-controller.js`
- Create: `tests-e2e/progress-migration.spec.js`

**Interfaces:**
- Consumes `progressStorageKeys` and the object-based `loadLocalProgress` API from Task 4.
- `runner/app.js` owns the current `{current, legacy}` scope and writes only `scope.current`.
- Guest adoption writes the account V2 key successfully before deleting guest V2/V1 keys.
- Account sync distinguishes `progress_data_incompatible` from network failure in visible status text.

- [ ] **Step 1: Add the failing Playwright migration scenario**

Create `tests-e2e/progress-migration.spec.js`:

```javascript
import { expect, test } from "@playwright/test";

test("guest V1 history migrates to V2 and a new run continues from it", async ({ page }) => {
  const legacy = {
    version: 1,
    updatedAt: "2026-09-06T10:15:30Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [{
      id: "legacy-run", variantId: "open-2026", variantLabel: "Открытый вариант 2026",
      mode: "practice", tasks: [2], completedTasks: [2], currentTask: 2,
      phase: "answer", fastMode: false, startedAt: "2026-09-06T10:00:00Z",
      status: "completed", completedAt: "2026-09-06T10:05:00Z", recordingsCount: 1,
    }],
    activeRun: null,
  };
  await page.addInitScript(value => localStorage.setItem("egeChineseProgressV1", JSON.stringify(value)), legacy);
  await page.goto("/?variant=open-2026");
  await expect(page.locator("#progressSummary")).toContainText("1 тренировка");
  await page.locator("#openProgressBtn").click();
  await expect(page.locator("#historyList")).toContainText("Открытый вариант 2026");
  await page.locator("#progressCloseBtn").click();

  const stored = await page.evaluate(() => ({
    v1: localStorage.getItem("egeChineseProgressV1"),
    v2: JSON.parse(localStorage.getItem("egeChineseProgressV2")),
  }));
  expect(stored.v1).toBeNull();
  expect(stored.v2.version).toBe(2);
  expect(stored.v2.runs[0].id).toBe("legacy-run");

  await page.locator('[data-start="2"]').click();
  const continued = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(continued.version).toBe(2);
  expect(continued.runs[0].id).toBe("legacy-run");
  expect(continued.activeRun.mode).toBe("practice");
});
```

- [ ] **Step 2: Run the new E2E test to observe RED**

Run:

```bash
npx playwright test tests-e2e/progress-migration.spec.js
```

Expected: V2 key is absent because `runner/app.js` still uses the V1 string API.

- [ ] **Step 3: Integrate scoped keys in the runner**

In `frontend/js/runner/app.js`, import `progressStorageKeys`, replace `progressStorageKey` with `progressScope`, and initialize through:

```javascript
let progressScope = progressStorageKeys();
let progress = loadLocalProgress(progressScope, { onError: message => toast(message) });
```

`saveProgressLocal` writes `progressScope.current`. `switchProgressScope` computes `nextScope = progressStorageKeys(user?.id)`, treats either next key as an existing scoped history, and calls `loadLocalProgress(nextScope, { onError: message => toast(message) })`.

For guest adoption, first run `localStorage.setItem(nextScope.current, JSON.stringify(progress))`. Only after that succeeds remove `progressScope.current` and `progressScope.legacy`; if it throws, keep guest keys, show `"Не удалось перенести прогресс в аккаунт"`, and load the account scope without deleting anything. Set `progressScope = nextScope` only after the selected branch has produced its progress value.

Keep `saveProgressLocal` slicing at 100. Runner-created active/completed run fields already match V2; do not alter review snapshot fields.

- [ ] **Step 4: Report incompatible server data distinctly**

In `frontend/js/account/account-auth-controller.js`, centralize sync failure text:

```javascript
function showProgressSyncError(error) {
  $("progressSyncStatus").textContent = error?.code === "progress_data_incompatible"
    ? "Серверный прогресс несовместим · локальная копия сохранена"
    : "Нет связи · сохранено в браузере";
}
```

Use it in `initAuth`, post-login sync and the debounced `pushProgress` catch. Do not call `ctx.setProgress` or `ctx.saveProgressLocal` when GET fails; the current local V2 stays intact.

- [ ] **Step 5: Run E2E and existing runner/account tests to GREEN**

Run:

```bash
npx playwright test tests-e2e/progress-migration.spec.js
npm test
```

Expected: migration scenario and all JavaScript unit tests pass.

- [ ] **Step 6: Commit UI integration**

```bash
git add frontend/js/runner/app.js frontend/js/account/account-auth-controller.js tests-e2e/progress-migration.spec.js
git commit -m "feat: adopt progress v2 across browser scopes"
```

## Task 6: Architecture Documentation and Full Verification

**Files:**
- Modify: `docs/architecture.md`
- Modify only if an actual boundary regression is found: `tests/unit/test_architecture_boundaries.py`

**Interfaces:**
- Consumes all prior tasks.
- Produces documented ownership of V2 validation/migration and fresh whole-project verification evidence.

- [ ] **Step 1: Update architecture documentation**

Replace the current two-line progress description in `docs/architecture.md` with a concise section that states:

```markdown
Маршруты `/api/progress` принимают legacy V1 только как вход миграции и строгий V2 как основной контракт.
`domain/progress.py` владеет нейтральными моделями, инвариантами, канонической сериализацией и V1→V2;
Pydantic повторяет строгую форму на HTTP-границе. `ProgressService` лениво нормализует V1 при GET без записи,
сохраняет только V2 при PUT и отделяет клиентский `progress.updatedAt` от серверного timestamp строки.
SQLite adapter отвечает только за JSON/транзакции и сообщает повреждённое хранилище через repository port.
Frontend синхронизирует уже нормализованный V2 и переносит guest/per-user localStorage только по правилу
write-V2-before-delete-V1.
```

Explicitly record that review `run` and material `content` remain later strict-contract stages.

- [ ] **Step 2: Run formatting and inspect the complete diff**

Run:

```bash
.venv/bin/python -m ruff format src/trainer/domain/progress.py src/trainer/services/progress.py \
  src/trainer/services/progress_repository.py src/trainer/infrastructure/database/progress_repository.py \
  src/trainer/api/schemas.py src/trainer/api/controllers/progress.py \
  tests/unit/test_progress_domain.py tests/unit/test_progress_service.py \
  tests/unit/test_progress_controller.py tests/integration/test_progress_repository.py \
  tests/integration/test_api_flows.py
git diff --check
git diff --stat HEAD~5
```

Expected: formatter completes, diff check emits no output, and the diff is limited to the files in this plan plus the spec/plan documents.

- [ ] **Step 3: Commit documentation and any formatter changes**

```bash
git add docs/architecture.md src/trainer/domain/progress.py src/trainer/services/progress.py \
  src/trainer/services/progress_repository.py src/trainer/infrastructure/database/progress_repository.py \
  src/trainer/api/schemas.py src/trainer/api/controllers/progress.py \
  tests/unit/test_progress_domain.py tests/unit/test_progress_service.py \
  tests/unit/test_progress_controller.py tests/integration/test_progress_repository.py \
  tests/integration/test_api_flows.py
git commit -m "docs: document progress v2 migration"
```

- [ ] **Step 4: Run the mandatory full checks**

Run:

```bash
make check
make test-e2e
```

Expected: lint, JSON/YAML checks, JavaScript tests, Python unit/integration tests, coverage and all Playwright tests pass.

- [ ] **Step 5: Review contract-specific evidence**

Run:

```bash
rg -n 'egeChineseProgressV1|egeChineseProgressV2|version.: 1|version.: 2' frontend tests-js tests-e2e src tests
git status --short
git log --oneline -6
```

Expected: V1 appears only in compatibility constants/fixtures/tests; production-created documents and persisted PUT data use V2; status contains no generated runtime data and still preserves `.superpowers/brainstorm/`.

- [ ] **Step 6: Request code review before integration**

Use `superpowers:requesting-code-review` on the complete branch diff. Resolve only verified issues, rerun the affected focused tests, then rerun `make check` and `make test-e2e` if production code changes after the full gate.
