# Strict Review Run Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every new review request to contain a canonical completed Progress V2 run that matches its variant and selected completed tasks, while leaving legacy stored rows readable.

**Architecture:** Promote the existing single-run parser and serializer in `domain.progress` to public functions, then compose them with review-specific relationships in `domain.review_requests`. FastAPI mirrors the strict shape with the existing `CompletedRun` schema, while `ReviewRequestService` repeats domain validation and persists only canonical JSON before entering the existing material-snapshot transaction.

**Tech Stack:** Python 3, frozen dataclasses, Pydantic v2, FastAPI, SQLite, `unittest`, vanilla JavaScript fixtures and Playwright; no new dependency and no database migration.

**Spec:** docs/superpowers/specs/2026-09-07-review-run-contract-design.md

## Global Constraints

- Limit this stage to `ReviewRequestCreate.run`; do not tighten `MaterialRequest.content` or task snapshot schemas.
- Accept only a strict `CompletedProgressRun` for new review requests; require `status == "completed"`.
- Require `run.variantId == ReviewRequestCreate.variantId` and `set(tasks) <= set(run.completedTasks)`.
- For `kind="task"`, preserve exactly one selected task. For `kind="attempt"`, allow a non-empty subset of the run's completed tasks.
- Unknown run fields and type coercion remain forbidden. Invalid run structure returns HTTP 422 `request_validation_failed`; review-specific relationship failures return HTTP 400 `invalid_request`.
- Validate before material lookup, repository transaction, asset copying, persistence or audit, and never mutate the caller's input.
- Persist only the canonical dictionary returned by the Progress V2 serializer, using compact UTF-8 JSON.
- Remove `run_too_large`; do not replace it with another byte-size guard because the strict field and array bounds already cap the payload.
- Do not read, migrate or rewrite existing `review_requests.run_json`; list/detail behavior for legacy rows must stay intact.
- Preserve review-request routes, response envelopes, authorization, material snapshots, recordings, audit, cleanup and status transitions.
- Do not add or edit an Alembic revision.
- Use test-first RED/GREEN cycles and a focused commit after every task.
- Run fresh `make check` and `make test-e2e` before completion.
- Preserve the user's untracked `.superpowers/brainstorm/` and unrelated changes. Create an isolated worktree when execution starts.

---

## File Map

- Modify `src/trainer/domain/progress.py`: expose strict parsing and canonical serialization for one completed run.
- Modify `tests/unit/test_progress_domain.py`: lock the public single-run API, timestamp/list canonicalization and immutability.
- Modify `src/trainer/domain/review_requests.py`: validate a full review-request creation tuple and its cross-field relationships.
- Modify `tests/unit/test_grading.py`: cover accepted subsets and exact review-domain rejection messages.
- Modify `src/trainer/services/review_requests.py`: use full domain validation and persist canonical run JSON; remove the arbitrary size branch.
- Modify `tests/unit/test_review_request_service.py`: use complete run fixtures and prove validation happens without side effects.
- Modify `src/trainer/api/schemas.py`: type `ReviewRequestCreate.run` as `CompletedRun` and validate its internal domain contract.
- Modify `src/trainer/api/controllers/review_requests.py`: dump the Pydantic run to a plain dictionary and remove `run_too_large` mapping.
- Modify `tests/integration/test_api_flows.py`: replace permissive fixtures and verify 422/400/canonical persistence/legacy reads.
- Modify `tests-e2e/variants-catalog.spec.js`: make the one direct review-request payload canonical.
- Modify `docs/architecture.md`: document the strict review run boundary and remove the statement that it is future work.

## Task 1: Public Completed Progress Run Boundary

**Files:**
- Modify: `src/trainer/domain/progress.py:170-183,299-314`
- Modify: `tests/unit/test_progress_domain.py:1-230`

**Interfaces:**
- Produces `parse_completed_run(value: object) -> CompletedProgressRun`.
- Produces `completed_run_to_dict(run: CompletedProgressRun) -> dict[str, object]`.
- Preserves `ProgressValidationError("invalid_document")`, strict field sets, sorted task tuples and canonical UTC millisecond timestamps.
- Existing `normalize_progress()` and `progress_to_dict()` consume the same public functions; there is no second implementation.

- [ ] **Step 1: Write failing tests for the public single-run API**

Update imports in `tests/unit/test_progress_domain.py` and add these tests to `ProgressDomainTest`:

```python
from trainer.domain.progress import (
    ProgressValidationError,
    completed_run_to_dict,
    normalize_progress,
    parse_completed_run,
    progress_to_dict,
)


def test_completed_run_public_boundary_is_canonical_and_immutable(self):
    source = completed_run("public-run")
    source.update(
        mode="exam",
        tasks=[3, 1, 2],
        completedTasks=[2, 3, 1],
        currentTask=3,
        startedAt="2026-09-06T13:00:00+03:00",
        completedAt="2026-09-06T13:05:00+03:00",
    )
    original = copy.deepcopy(source)

    result = completed_run_to_dict(parse_completed_run(source))

    self.assertEqual(result["tasks"], [1, 2, 3])
    self.assertEqual(result["completedTasks"], [1, 2, 3])
    self.assertEqual(result["startedAt"], "2026-09-06T10:00:00.000Z")
    self.assertEqual(result["completedAt"], "2026-09-06T10:05:00.000Z")
    self.assertEqual(source, original)

def test_completed_run_public_boundary_rejects_invalid_structure(self):
    source = completed_run()
    source["unknown"] = True

    with self.assertRaises(ProgressValidationError) as raised:
        parse_completed_run(source)

    self.assertEqual(raised.exception.reason, "invalid_document")
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_progress_domain.ProgressDomainTest.test_completed_run_public_boundary_is_canonical_and_immutable \
  tests.unit.test_progress_domain.ProgressDomainTest.test_completed_run_public_boundary_rejects_invalid_structure -v
```

Expected: import errors because `parse_completed_run` and `completed_run_to_dict` are not public yet.

- [ ] **Step 3: Promote the existing parser and serializer**

In `src/trainer/domain/progress.py`, rename the functions and every internal call without changing their rules:

```python
def parse_completed_run(value: object) -> CompletedProgressRun:
    run, started = _parse_run_fields(value, COMPLETED_FIELDS)
    document = cast(dict[str, object], value)
    status = cast(RunStatus, _choice(document["status"], ("completed", "interrupted")))
    completed_at, completed = _timestamp(document["completedAt"])
    if completed < started or (status == "completed" and run.completed_tasks != run.tasks):
        raise _invalid()
    return CompletedProgressRun(
        **run.__dict__,
        status=status,
        completed_at=completed_at,
        recordings_count=_integer(document["recordingsCount"], minimum=0, maximum=100),
    )


def completed_run_to_dict(run: CompletedProgressRun) -> dict[str, object]:
    return {
        **_run_to_dict(run),
        "status": run.status,
        "completedAt": run.completed_at,
        "recordingsCount": run.recordings_count,
    }
```

Replace `_parse_completed_run(...)` with `parse_completed_run(...)` in `_parse_v2()` and `_migrate_v1()`. Replace `_completed_run_to_dict(...)` with `completed_run_to_dict(...)` in `_migrate_v1()` and `progress_to_dict()`.

- [ ] **Step 4: Run the full progress-domain suite to verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_progress_domain -v
```

Expected: all progress-domain tests pass, including existing strict V2 and V1 migration coverage.

- [ ] **Step 5: Commit the public domain boundary**

```bash
git add src/trainer/domain/progress.py tests/unit/test_progress_domain.py
git commit -m "refactor: expose completed progress run contract"
```

## Task 2: Review-Request Cross-Field Domain Validation

**Files:**
- Modify: `src/trainer/domain/review_requests.py:1-35`
- Modify: `tests/unit/test_grading.py:1-65`

**Interfaces:**
- Consumes `parse_completed_run(value: object) -> CompletedProgressRun` from Task 1.
- Produces frozen `ValidatedReviewRequest(selection: ReviewRequestSelection, run: CompletedProgressRun)`.
- Produces `validate_review_request(kind: object, tasks: object, variant_id: object, run: object) -> ValidatedReviewRequest`.
- Raises `ValueError` with one of four stable Russian messages: invalid run structure, incomplete status, variant mismatch or selected-task mismatch.

- [ ] **Step 1: Add a complete run fixture and failing relationship tests**

Update `tests/unit/test_grading.py` imports and add the helper/tests below:

```python
import copy

from trainer.domain.review_requests import (
    required_recording_positions,
    validate_review_request,
    validate_review_selection,
)


def completed_run():
    return {
        "id": "review-run",
        "variantId": "open-2026",
        "variantLabel": "Открытый вариант 2026",
        "mode": "exam",
        "tasks": [3, 1, 2],
        "completedTasks": [2, 3, 1],
        "currentTask": 3,
        "phase": "answer",
        "fastMode": False,
        "startedAt": "2026-09-07T10:00:00Z",
        "status": "completed",
        "completedAt": "2026-09-07T10:30:00Z",
        "recordingsCount": 7,
    }
```

Add a new `ReviewRequestValidationTest` class:

```python
class ReviewRequestValidationTest(unittest.TestCase):
    def assert_rejected(self, *, message, run=None, variant_id="open-2026", tasks=None):
        source = completed_run() if run is None else run
        original = copy.deepcopy(source)
        with self.assertRaisesRegex(ValueError, f"^{message}$"):
            validate_review_request("attempt", tasks or [1, 2], variant_id, source)
        self.assertEqual(source, original)

    def test_accepts_a_subset_of_completed_tasks_and_returns_canonical_run(self):
        source = completed_run()
        result = validate_review_request("attempt", [2, 1], "open-2026", source)
        self.assertEqual(result.selection.tasks, (1, 2))
        self.assertEqual(result.run.tasks, (1, 2, 3))
        self.assertEqual(result.run.completed_tasks, (1, 2, 3))
        self.assertEqual(source["tasks"], [3, 1, 2])

    def test_rejects_invalid_run_structure(self):
        self.assert_rejected(message="Некорректные данные попытки", run={"id": "broken"})

    def test_rejects_an_interrupted_run(self):
        run = completed_run()
        run.update(status="interrupted", completedTasks=[1, 2])
        self.assert_rejected(message="Для разбора можно отправить только завершённую попытку", run=run)

    def test_rejects_a_different_variant(self):
        self.assert_rejected(message="Вариант попытки не совпадает с выбранным вариантом", variant_id="demo-2026")

    def test_rejects_a_task_missing_from_completed_tasks(self):
        run = completed_run()
        run.update(status="interrupted", completedTasks=[1, 2])
        with self.assertRaisesRegex(ValueError, "только завершённую попытку"):
            validate_review_request("attempt", [3], "open-2026", run)
```

The last case fixes validation precedence: status is checked before the selected-task relationship. Add a separate structural `CompletedProgressRun` with `status="completed"` only through the normal parser; because Progress V2 requires all run tasks completed, a selected-task mismatch is exercised by selecting a valid task outside a practice run:

```python
def test_rejects_a_selected_task_outside_the_completed_run(self):
    run = completed_run()
    run.update(mode="practice", tasks=[2], completedTasks=[2], currentTask=2)
    self.assert_rejected(
        message="Выбранные задания отсутствуют среди завершённых",
        run=run,
        tasks=[1],
    )
```

- [ ] **Step 2: Run the review-domain tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_grading.ReviewRequestValidationTest -v
```

Expected: import error because `validate_review_request` does not exist.

- [ ] **Step 3: Implement the composed review validator**

Add these imports, result type and function to `src/trainer/domain/review_requests.py` while preserving `validate_review_selection()` and `required_recording_positions()`:

```python
from trainer.domain.progress import CompletedProgressRun, ProgressValidationError, parse_completed_run


@dataclass(frozen=True)
class ValidatedReviewRequest:
    selection: ReviewRequestSelection
    run: CompletedProgressRun


def validate_review_request(
    kind: object,
    tasks: object,
    variant_id: object,
    run: object,
) -> ValidatedReviewRequest:
    selection = validate_review_selection(kind, tasks)
    try:
        completed_run = parse_completed_run(run)
    except ProgressValidationError as error:
        raise ValueError("Некорректные данные попытки") from error
    if completed_run.status != "completed":
        raise ValueError("Для разбора можно отправить только завершённую попытку")
    if completed_run.variant_id != variant_id:
        raise ValueError("Вариант попытки не совпадает с выбранным вариантом")
    if not set(selection.tasks).issubset(completed_run.completed_tasks):
        raise ValueError("Выбранные задания отсутствуют среди завершённых")
    return ValidatedReviewRequest(selection, completed_run)
```

- [ ] **Step 4: Run all grading/review domain tests to verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_grading -v
```

Expected: all grading, selection, recording-position and full review validation tests pass.

- [ ] **Step 5: Commit the review-domain rule**

```bash
git add src/trainer/domain/review_requests.py tests/unit/test_grading.py
git commit -m "feat: validate review request run relationships"
```

## Task 3: Canonical Service Persistence Without Size Branch

**Files:**
- Modify: `src/trainer/services/review_requests.py:1-120`
- Modify: `tests/unit/test_review_request_service.py:1-340`

**Interfaces:**
- Consumes `validate_review_request(...) -> ValidatedReviewRequest` from Task 2.
- Consumes `completed_run_to_dict(run: CompletedProgressRun) -> dict[str, object]` from Task 1.
- Keeps `ReviewRequestService.create(..., run: object, ...) -> dict` callable independently of FastAPI.
- Converts every `ValueError` from the composed domain boundary into `ReviewRequestError("invalid_request", message)`.
- Removes service reason `run_too_large`.

- [ ] **Step 1: Replace permissive service fixtures and write failing canonicalization tests**

Add this helper near the imports in `tests/unit/test_review_request_service.py`:

```python
def completed_run(*, run_id="review-run", variant_id="author-material", task=2):
    return {
        "id": run_id,
        "variantId": variant_id,
        "variantLabel": "Авторский материал",
        "mode": "practice",
        "tasks": [task],
        "completedTasks": [task],
        "currentTask": task,
        "phase": "answer",
        "fastMode": False,
        "startedAt": "2026-09-07T13:00:00+03:00",
        "status": "completed",
        "completedAt": "2026-09-07T13:05:00+03:00",
        "recordingsCount": 1,
    }
```

In `test_create_persists_trimmed_snapshot_and_audit`, pass `source = completed_run()` and retain a deep copy. Replace the run assertion with:

```python
self.assertEqual(
    json.loads(repository.requests[0]["run_json"]),
    {
        **completed_run(),
        "startedAt": "2026-09-07T10:00:00.000Z",
        "completedAt": "2026-09-07T10:05:00.000Z",
    },
)
self.assertEqual(source, original)
```

Replace `test_create_rejects_oversized_run_without_persisting_state` with a side-effect-order test:

```python
def test_create_rejects_invalid_run_before_transaction_or_material_lookup(self):
    repository = FakeReviewRequestRepository()
    transaction_calls = 0

    @contextmanager
    def unexpected_transaction(*, immediate=False):
        nonlocal transaction_calls
        transaction_calls += 1
        yield repository

    repository.transaction = unexpected_transaction
    with self.assertRaises(ReviewRequestError) as caught:
        self.make_service(repository).create(
            kind="task",
            tasks=[2],
            variant_id="author-material",
            run={"id": "broken"},
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )

    self.assertEqual((caught.exception.reason, caught.exception.message), ("invalid_request", "Некорректные данные попытки"))
    self.assertEqual(transaction_calls, 0)
    self.assertEqual((repository.requests, repository.items, repository.audits), ([], [], []))
```

Update `test_create_rejects_material_without_selected_task` to pass `completed_run()` so it continues to reach the material check. Add a direct relationship case:

```python
def test_create_rejects_variant_mismatch_without_persisting_state(self):
    repository = FakeReviewRequestRepository()
    with self.assertRaises(ReviewRequestError) as caught:
        self.make_service(repository).create(
            kind="task",
            tasks=[2],
            variant_id="other-material",
            run=completed_run(),
            actor=ReviewActor(id=17, email="student@example.test"),
            metadata=RequestMetadata(client_ip="127.0.0.1", user_agent="test"),
        )
    self.assertEqual(caught.exception.reason, "invalid_request")
    self.assertEqual(caught.exception.message, "Вариант попытки не совпадает с выбранным вариантом")
    self.assertEqual(repository.requests, [])
```

- [ ] **Step 2: Run focused service tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.unit.test_review_request_service.ReviewRequestServiceTest.test_create_persists_trimmed_snapshot_and_audit \
  tests.unit.test_review_request_service.ReviewRequestServiceTest.test_create_rejects_invalid_run_before_transaction_or_material_lookup \
  tests.unit.test_review_request_service.ReviewRequestServiceTest.test_create_rejects_variant_mismatch_without_persisting_state -v
```

Expected: canonicalization assertion fails and invalid runs still reach serialization/transaction behavior.

- [ ] **Step 3: Validate and serialize the canonical run before the transaction**

Change imports and the beginning of `ReviewRequestService.create()` in `src/trainer/services/review_requests.py`:

```python
from trainer.domain.progress import completed_run_to_dict
from trainer.domain.review_requests import required_recording_positions, validate_review_request


try:
    validated = validate_review_request(kind, tasks, variant_id, run)
except ValueError as error:
    raise ReviewRequestError("invalid_request", str(error)) from error
encoded_run = json.dumps(
    completed_run_to_dict(validated.run),
    ensure_ascii=False,
    separators=(",", ":"),
)
selection = validated.selection
```

Delete the `len(encoded_run.encode("utf-8")) > 100_000` branch entirely. Keep all material, transaction, asset, item and audit code after this block unchanged.

- [ ] **Step 4: Run the complete service suite to verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_review_request_service -v
```

Expected: all review service scenarios pass with canonical fixtures; no test or code mentions `run_too_large` in the service.

- [ ] **Step 5: Commit canonical service persistence**

```bash
git add src/trainer/services/review_requests.py tests/unit/test_review_request_service.py
git commit -m "feat: persist canonical review run snapshots"
```

## Task 4: Strict HTTP Contract, Compatibility Fixtures and Documentation

**Files:**
- Modify: `src/trainer/api/schemas.py:1-130`
- Modify: `src/trainer/api/controllers/review_requests.py:14-25,86-100`
- Modify: `tests/integration/test_api_flows.py:1-1400`
- Modify: `tests-e2e/variants-catalog.spec.js:167-215`
- Modify: `docs/architecture.md:69-82,146-158`

**Interfaces:**
- `ReviewRequestCreate.run` is `CompletedRun`, with a model-level domain validation pass.
- The controller passes `payload.run.model_dump(mode="json", by_alias=True)` to the service.
- Malformed shape/internal run invariants map through FastAPI to 422 `request_validation_failed`.
- Review relationships map through `ReviewRequestError("invalid_request")` to the existing 400 response.
- Current student and teacher list/detail responses never decode `run_json`.

- [ ] **Step 1: Add canonical integration helpers and failing HTTP contract tests**

Add this module helper near `PROGRESS_MIGRATION_CASE` in `tests/integration/test_api_flows.py`:

```python
def review_run(run_id, *, variant_id="demo-2026", tasks=(2,)):
    run_tasks = list(tasks)
    return {
        "id": run_id,
        "variantId": variant_id,
        "variantLabel": "Вариант для разбора",
        "mode": "exam" if run_tasks == [1, 2, 3] else "practice",
        "tasks": run_tasks,
        "completedTasks": run_tasks,
        "currentTask": run_tasks[-1],
        "phase": "answer",
        "fastMode": False,
        "startedAt": "2026-09-07T10:00:00Z",
        "status": "completed",
        "completedAt": "2026-09-07T10:30:00Z",
        "recordingsCount": 1,
    }
```

Add these tests to `ApiFlowTest` before the first successful review flow:

```python
def test_review_request_run_contract_separates_shape_and_relationship_errors(self):
    student_cookie = self.register_student("review-run-contract")
    invalid_shape = {"id": "broken"}
    status, error, _ = self.request(
        "POST",
        "/api/review-requests",
        {"kind": "task", "variantId": "demo-2026", "tasks": [2], "run": invalid_shape},
        student_cookie,
    )
    self.assertEqual((status, error["code"]), (422, "request_validation_failed"))

    interrupted = review_run("interrupted")
    interrupted.update(status="interrupted", completedTasks=[])
    status, error, _ = self.request(
        "POST",
        "/api/review-requests",
        {"kind": "task", "variantId": "demo-2026", "tasks": [2], "run": interrupted},
        student_cookie,
    )
    self.assertEqual((status, error["code"]), (400, "invalid_request"))
    self.assertEqual(error["message"], "Для разбора можно отправить только завершённую попытку")

    mismatch = review_run("mismatch")
    status, error, _ = self.request(
        "POST",
        "/api/review-requests",
        {"kind": "task", "variantId": "other-2026", "tasks": [2], "run": mismatch},
        student_cookie,
    )
    self.assertEqual((status, error["code"]), (400, "invalid_request"))

def test_review_request_persists_canonical_run_and_legacy_rows_remain_listable(self):
    student_cookie = self.register_student("review-run-storage")
    source = review_run("canonical-storage")
    source.update(startedAt="2026-09-07T13:00:00+03:00", completedAt="2026-09-07T13:30:00+03:00")
    status, created, _ = self.request(
        "POST",
        "/api/review-requests",
        {"kind": "task", "variantId": "demo-2026", "tasks": [2], "run": source},
        student_cookie,
    )
    self.assertEqual(status, 201, created)
    request_id = created["reviewRequest"]["id"]
    with runtime.connect() as database:
        stored = json.loads(database.execute("SELECT run_json FROM review_requests WHERE id=?", (request_id,)).fetchone()[0])
        self.assertEqual(stored["startedAt"], "2026-09-07T10:00:00.000Z")
        self.assertEqual(stored["completedAt"], "2026-09-07T10:30:00.000Z")
        database.execute("UPDATE review_requests SET run_json=? WHERE id=?", ('{"legacy":true}', request_id))
    status, listed, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
    self.assertEqual(status, 200, listed)
    self.assertIn(request_id, {item["id"] for item in listed["requests"]})
    with runtime.connect() as database:
        self.assertEqual(database.execute("SELECT run_json FROM review_requests WHERE id=?", (request_id,)).fetchone()[0], '{"legacy":true}')
```

- [ ] **Step 2: Run the new integration tests to verify RED**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.integration.test_api_flows.ApiFlowTest.test_review_request_run_contract_separates_shape_and_relationship_errors \
  tests.integration.test_api_flows.ApiFlowTest.test_review_request_persists_canonical_run_and_legacy_rows_remain_listable -v
```

Expected: malformed `run` does not return the new 422 contract because the schema is still a free dictionary.

- [ ] **Step 3: Implement strict schema validation and controller serialization**

Keep the existing `Any` import for the out-of-scope `MaterialRequest.content`, import the public parser, and change `ReviewRequestCreate`:

```python
from trainer.domain.progress import ProgressValidationError, normalize_progress, parse_completed_run


class ReviewRequestCreate(ApiSchema):
    kind: Literal["task", "attempt"]
    variantId: str = Field(pattern=r"^[a-z0-9-]{3,50}$")
    tasks: list[Literal[1, 2, 3]] = Field(min_length=1, max_length=3)
    run: CompletedRun

    @model_validator(mode="after")
    def valid_run_contract(self):
        try:
            parse_completed_run(self.run.model_dump(mode="json", by_alias=True))
        except ProgressValidationError as error:
            raise ValueError(error.reason) from error
        return self
```

In `src/trainer/api/controllers/review_requests.py`, delete the `run_too_large` branch from `_service_error()` and pass a plain dictionary:

```python
run=payload.run.model_dump(mode="json", by_alias=True),
```

- [ ] **Step 4: Convert every direct Python integration fixture to a canonical run**

Replace all eight minimal `"run": {"id": ..., "status": ..., "completedTasks": ...}` values in `tests/integration/test_api_flows.py` with `review_run(...)`.

For task-only calls use:

```python
"run": review_run("review-task-2"),
```

Use the existing literal run IDs for the discard/race/asset cases. For the complete-attempt test, the selected review tasks remain `[1, 2]`, but the run must be a valid completed exam and therefore use:

```python
"run": review_run("review-attempt-1-2", tasks=(1, 2, 3)),
```

This is the explicit integration proof that an attempt review may select a completed subset.

- [ ] **Step 5: Update the direct Playwright API fixture**

In `tests-e2e/variants-catalog.spec.js`, replace the direct minimal run with a complete practice run tied to the dynamic material slug:

```javascript
const runId = `direct-review-${Date.now()}`;
const startedAt = new Date().toISOString();
const completedAt = new Date(Date.now() + 1000).toISOString();
const review = await post(student, "/api/review-requests", {
  kind: "task",
  variantId: slug,
  tasks: [2],
  run: {
    id: runId,
    variantId: slug,
    variantLabel: "Direct review snapshot",
    mode: "practice",
    tasks: [2],
    completedTasks: [2],
    currentTask: 2,
    phase: "answer",
    fastMode: false,
    startedAt,
    status: "completed",
    completedAt,
    recordingsCount: 1,
  },
});
```

Do not modify browser progress or the account review controller: their generated completed runs already satisfy this contract.

- [ ] **Step 6: Update architecture documentation**

Extend the review-request boundary in `docs/architecture.md` with:

```markdown
Новые review requests принимают только строгий `CompletedProgressRun`: transport schema проверяет форму,
review domain — статус и связи с вариантом/выбранными заданиями, а service повторяет domain-проверку и сохраняет
канонический JSON до открытия transaction. Существующие legacy `run_json` не мигрируются и не читаются list/detail
сценариями.
```

Replace the Progress V2 sentence that names `ReviewRequestCreate.run` as future work with:

```markdown
Строгий `ReviewRequestCreate.run` повторно использует эту модель; отдельным последующим этапом остаётся только
контракт `MaterialRequest.content`.
```

- [ ] **Step 7: Run the focused API and E2E scenarios to verify GREEN**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_student_queues_single_task_for_owner_review -v
npx playwright test tests-e2e/student-teacher.spec.js tests-e2e/variants-catalog.spec.js
```

Expected: the API flow passes with canonical persistence, the ordinary browser-generated run is accepted, and the direct custom-material flow remains green.

- [ ] **Step 8: Confirm the retired size reason is gone and run all required checks**

Run:

```bash
rg -n "run_too_large|Данные попытки слишком велики" src tests tests-js tests-e2e
make check
make test-e2e
```

Expected: `rg` has no matches; `make check` and all Playwright tests pass. The two PostgreSQL smoke tests may remain skipped when `TEST_DATABASE_URL` is not configured.

- [ ] **Step 9: Inspect the final diff and commit the HTTP vertical slice**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Confirm that `.superpowers/brainstorm/` remains untracked and no database/runtime artifacts are staged. Then commit only the listed files:

```bash
git add src/trainer/api/schemas.py \
  src/trainer/api/controllers/review_requests.py \
  tests/integration/test_api_flows.py \
  tests-e2e/variants-catalog.spec.js \
  docs/architecture.md
git commit -m "feat: enforce strict review run api contract"
```

## Final Completion Gate

- [ ] Review the committed diff from the implementation worktree against `docs/superpowers/specs/2026-09-07-review-run-contract-design.md`.
- [ ] Confirm new writes are strict and canonical while a manually seeded legacy `run_json` remains unchanged and listable.
- [ ] Confirm no schema migration, new dependency, frontend behavior change or unrelated cleanup entered the branch.
- [ ] Record the fresh `make check` and `make test-e2e` results before invoking branch-finishing workflow.
