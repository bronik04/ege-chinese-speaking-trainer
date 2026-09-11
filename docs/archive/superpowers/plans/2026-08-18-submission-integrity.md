# Submission Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an assigned submission visible and gradable only after its complete required audio set is stored.

**Architecture:** The database gives submissions an explicit `uploading` state; controller actions own valid transitions and recording positions. The runner creates, uploads and completes a submission in sequence, retaining local recordings on any error.

**Tech Stack:** SQLite/Alembic, FastAPI/Pydantic, vanilla JavaScript, Python integration tests, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-core-reliability-design.md`

## Global Constraints

- Existing `submitted` and `graded` rows retain their current meaning.
- Required positions are task 1 questions 1–5, task 2, and task 3, limited to tasks selected for the assignment.
- A teacher query, export, history and review never expose or mutate `uploading` rows.
- Use `409 submission_incomplete` with missing positions and `409 submission_not_uploading` for prohibited uploads/transitions.
- Do not mark a browser run as successfully sent until `/complete` succeeds.

---

### Task 1: Migration and submission-state foundation

**Files:**
- Create: `migrations/versions/20260818_06_submission_states.py`
- Modify: `tests/integration/test_migrations.py:16-120`
- Modify: `src/trainer/infrastructure/database/submissions.py:9-42`
- Test: `tests/integration/test_migrations.py`
- Test: `tests/integration/test_queries.py`

**Interfaces:**
- Produces: schema where `submissions.status` permits `uploading`, `submitted`, `graded` and `submitted_at` is nullable; `create_submission_with_retry(..., status="uploading") -> tuple[int, int]`.
- Consumes: Alembic revision `20260730_05` and current submissions table definition.

- [ ] **Step 1: Add a failing migration assertion**

  Extend `EXPECTED_TABLES` tests to create a clean database, insert an `uploading` row, and assert `PRAGMA table_info(submissions)` retains the current columns. Add an upgrade test that starts at `20260730_05`, runs head, and accepts the new status.

  ```python
  database.execute(
      "INSERT INTO submissions(assignment_id, student_id, attempt_number, status, run_json, submitted_at) "
      "VALUES (1, 1, 1, 'uploading', '{}', NULL)"
  )
  ```

- [ ] **Step 2: Run the migration test to verify failure**

  Run: `python -m pytest tests/integration/test_migrations.py -v`

  Expected: SQLite CHECK constraint rejects `uploading`.

- [ ] **Step 3: Implement an Alembic copy-and-swap migration**

  Define the current `submissions` table explicitly, use `op.batch_alter_table(..., copy_from=...)` to replace its status CHECK constraint with `('uploading', 'submitted', 'graded')` and make `submitted_at` nullable, preserving both foreign keys and `UNIQUE(assignment_id, student_id, attempt_number)`. Update `create_submission_with_retry` to insert explicit `status` with `submitted_at=NULL` for uploading rows.

  ```python
  cursor = database.execute(
      "INSERT INTO submissions(assignment_id, student_id, attempt_number, status, run_json, submitted_at) "
      "VALUES (?, ?, ?, ?, ?, ?)",
      (assignment_id, student_id, attempt, status, encoded_run, None),
  )
  ```

- [ ] **Step 4: Run clean and upgrade migration checks**

  Run: `python -m pytest tests/integration/test_migrations.py tests/integration/test_queries.py -v`.

  Expected: PASS and `head_revision()` equals `20260818_06`.

- [ ] **Step 5: Commit the schema foundation**

  ```bash
  git add migrations/versions/20260818_06_submission_states.py src/trainer/infrastructure/database/submissions.py tests/integration/test_migrations.py tests/integration/test_queries.py
  git commit -m "feat: add uploading submission state"
  ```

### Task 2: Complete only valid recording manifests

**Files:**
- Modify: `src/trainer/api/controllers/work.py:229-358`
- Modify: `src/trainer/api/controllers/recordings.py:19-109`
- Modify: `src/trainer/api/routes/work.py:65-70`
- Modify: `src/trainer/api/schemas.py:48-55`
- Test: `tests/integration/test_api_flows.py:400-460`

**Interfaces:**
- Produces: `submission_complete(submission_id: int, user: dict, context: RequestContext) -> ActionResult` and `POST /api/submissions/{submission_id}/complete`.
- Consumes: uploading schema and recording metadata.

- [ ] **Step 1: Write failing lifecycle tests**

  Create an assignment with tasks `[1, 2]`, POST a submission, assert `status == "uploading"`, assert `GET /api/teacher/submissions` omits it, upload only task 2, then assert complete returns `409` with missing `[{"task": 1, "question": 1}, ...]`. Upload all five task-1 answers, complete, and assert the teacher sees exactly six recordings.

  ```python
  status, incomplete, _ = self.request("POST", f"/api/submissions/{submission_id}/complete", {}, student_cookie)
  self.assertEqual((status, incomplete["code"]), (409, "submission_incomplete"))
  ```

- [ ] **Step 2: Run lifecycle tests to verify failure**

  Run: `python -m pytest tests/integration/test_api_flows.py -k submission -v`.

  Expected: complete route is 404 and teacher query includes the just-created row.

- [ ] **Step 3: Add the state machine and manifest validator**

  In `work.py`, add `_required_recording_positions(tasks: list[int]) -> set[tuple[int, int | None]]`; check assignment membership, load recordings, return `submission_incomplete` with sorted `missing` data, update `status='submitted'` and `submitted_at=now` only where status is `uploading`, and write a `submission_completed` audit event. Add an empty `SubmissionCompleteRequest` schema and route using `require_student`.

  ```python
  required = {(1, number) for number in range(1, 6)} if 1 in tasks else set()
  required |= {(task, None) for task in (2, 3) if task in tasks}
  ```

- [ ] **Step 4: Restrict uploads, reads and reviews to the correct state**

  `recording_create` selects `submissions.status`, rejects any non-uploading row with `submission_not_uploading`, and checks `question=1..5` only for task 1. `review_submission`, export and submission history select only `submitted`/`graded`. The query layer starts filters with `submissions.status IN ('submitted', 'graded')`.

- [ ] **Step 5: Verify controller/API outcomes**

  Run: `python -m pytest tests/integration/test_api_flows.py tests/integration/test_queries.py -v`.

  Expected: full recording sets complete successfully; incomplete, duplicate-state and review-before-complete paths return expected 409/404 results.

- [ ] **Step 6: Commit the server state machine**

  ```bash
  git add src/trainer/api/controllers/work.py src/trainer/api/controllers/recordings.py src/trainer/api/routes/work.py src/trainer/api/schemas.py src/trainer/infrastructure/database/queries/combined.py tests/integration/test_api_flows.py tests/integration/test_queries.py
  git commit -m "feat: complete submissions after required recordings"
  ```

### Task 3: Make browser completion explicit and retryable

**Files:**
- Modify: `frontend/js/shared/api.js:18-29`
- Modify: `frontend/js/runner/runner-controller.js:275-299`
- Test: `tests-js/unit/runner-controller.test.js`
- Test: `tests-e2e/student-teacher.spec.js:25-91`

**Interfaces:**
- Produces: `completeSubmission(submissionId)` and an assigned-run UI that calls it after every `uploadAudio` request.
- Consumes: `POST /api/submissions/{id}/complete`.

- [ ] **Step 1: Add failing client tests**

  Mock `api`/`uploadAudio` and assert the runner sends recordings in order, calls `/complete` last, and changes status text to success only after that request resolves. In the rejected-complete test, assert the status keeps a retry action and does not say «Работа отправлена».

  ```javascript
  assert.deepEqual(calls.at(-1), ["/api/submissions/41/complete", { method: "POST", body: "{}" }]);
  ```

- [ ] **Step 2: Run the new JS tests to verify failure**

  Run: `npm test -- --test-name-pattern="complete submission"`.

  Expected: FAIL because the current runner finishes after upload calls.

- [ ] **Step 3: Add complete API helper and runner retry state**

  Add `completeSubmission(submissionId)` using `api(..., { method: "POST", body: "{}" })`. Keep `{ submissionId, attempt }` in controller-local pending state after creation; upload all blobs, call complete, then clear that state and refresh assignments. On error, leave blobs and pending id in memory, render a button that re-runs upload/complete, and show the server message.

- [ ] **Step 4: Update the E2E protocol test**

  Change the API E2E scenario to POST `/complete` after upload. Add an assertion that the teacher list is empty before the complete request and contains the audio afterward. Run: `npm test && make test-e2e`.

  Expected: PASS.

- [ ] **Step 5: Commit the client protocol**

  ```bash
  git add frontend/js/shared/api.js frontend/js/runner/runner-controller.js tests-js/unit/runner-controller.test.js tests-e2e/student-teacher.spec.js
  git commit -m "feat: finish audio submissions explicitly"
  ```
