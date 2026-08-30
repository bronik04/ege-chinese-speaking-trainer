# Teacher Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace group assignments with a single-owner teacher queue where students voluntarily submit one task or a complete attempt for oral review and later receive criterion scores.

**Architecture:** Keep review requests independent from legacy `assignments` and `submissions`. A request owns immutable per-task material snapshots, private copied assets, and private recordings; its state changes atomically from `uploading` to `queued` only after every required recording arrives, then to `reviewed` when the owner saves scores. API routes orchestrate the lifecycle, domain code validates request shapes and scores, and infrastructure persists/query-scopes data.

**Tech Stack:** FastAPI, Pydantic, SQLite + Alembic, local/S3 private storage adapters, vanilla JavaScript, Node test runner, Playwright, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-19-teacher-review-queue-design.md`

## Global Constraints

- `TRAINER_OWNER_EMAIL` is the exact, case-insensitive email of the only teacher; public registration has no role selector.
- A student explicitly submits either one task or a whole recorded attempt; completed practice never enters the teacher queue automatically.
- Only `uploading`, `queued`, and `reviewed` are valid review-request states; `uploading` is invisible to the teacher.
- Request content, image assets, and audio are immutable private snapshots; raw storage keys never enter API payloads.
- The application contains no new groups, invitation codes, assignment creation, deadlines, or text feedback/comments.
- Do not delete existing assignment/group rows or blobs during migration and do not silently convert them into review requests.
- Every public behavior change begins with a failing test; API changes require schema, route/controller, and Python integration coverage; UI changes require JS and Playwright coverage.
- Run `PYTHONPATH=src make check PYTHON=../../.venv/bin/python NPM=npm` and `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python make test-e2e PYTHON=../../.venv/bin/python NPM=npm` from a worktree before handoff.

---

## File Structure

- `src/trainer/domain/accounts/service.py` owns the pure rule that derives the sole teacher role from the configured owner email.
- `src/trainer/domain/review_requests.py` owns selection validation, required recording positions, and review-request state invariants.
- `migrations/versions/20260819_07_review_requests.py` adds isolated queue tables without changing legacy group or assignment data.
- `src/trainer/infrastructure/database/queries/review_requests.py` owns persistence and query scoping for the new queue; it never exposes storage keys.
- `src/trainer/services/review_assets.py` makes immutable private copies of material assets for a queue request.
- `src/trainer/api/controllers/review_requests.py` and `src/trainer/api/routes/review_requests.py` expose the voluntary-submit, queue, scoring, and private-file HTTP contracts.
- `frontend/js/runner/runner-controller.js` owns the explicit post-practice submission action; `frontend/js/account/account-review-requests-controller.js` owns student history; `frontend/js/account/account-reviews-controller.js` owns the owner queue.
- `frontend/js/account/account-assignments-controller.js` and `frontend/js/account/account-groups-controller.js` are removed only after the replacement paths are live; old database rows and private files remain archive data.
- `tests/unit/` fixes pure rules, `tests/integration/` fixes APIs/storage/migrations, `tests-js/` fixes rendering contracts, and `tests-e2e/` fixes the student-to-owner browser flow.

---

### Task 1: Restrict the product to one configured teacher

**Files:**
- Modify: `src/trainer/domain/accounts/service.py`
- Modify: `src/trainer/api/schemas.py`
- Modify: `src/trainer/api/controllers/auth.py`
- Modify: `src/trainer/api/dependencies.py`
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/account/account-auth-controller.js`
- Modify: `tests/unit/test_account_service.py`
- Modify: `tests/integration/test_api_flows.py`
- Modify: `tests/integration/test_asgi.py`
- Modify: `tests-e2e/account-workflows.spec.js`
- Modify: `.env.example`, `README.md`, `DEVELOPMENT.md`

**Interfaces:**
- Produces `owner_email_from_env() -> str` in `api/dependencies.py`; it returns the trimmed lowercase value of `TRAINER_OWNER_EMAIL`.
- Produces `registration_role(email: str, owner_email: str) -> Literal["student", "teacher"]` in `domain/accounts/service.py`.
- Changes `authorize_role(..., owner_email: str)` so teacher access requires a verified `teacher` account whose email exactly equals `owner_email`.
- Removes `RegisterRequest.role`; `/api/auth/register` derives the role and never accepts a caller-selected one.

- [ ] **Step 1: Write failing domain and API tests for derived ownership**

  In `tests/unit/test_account_service.py`, add a test proving that `registration_role("OWNER@example.test", "owner@example.test")` is `"teacher"`, another email is `"student"`, and `authorize_role` rejects a verified teacher if the configured owner differs.

  In `tests/integration/test_api_flows.py`, set `TRAINER_OWNER_EMAIL=owner@example.test` in the test environment and assert:

  ```python
  status, owner, _ = self.request("POST", "/api/auth/register", {
      "email": "owner@example.test", "password": "password123", "displayName": "Owner"
  })
  self.assertEqual(status, 201)
  self.assertEqual(owner["user"]["role"], "teacher")

  status, student, _ = self.request("POST", "/api/auth/register", {
      "email": "student@example.test", "password": "password123", "displayName": "Student"
  })
  self.assertEqual(status, 201)
  self.assertEqual(student["user"]["role"], "student")
  ```

  Also post an obsolete `role` field and assert the existing `validation_failed` contract, not role elevation.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.unit.test_account_service tests.integration.test_api_flows.ApiFlowTest.test_owner_registration_derives_teacher_role`

  Expected: FAIL because the role is still accepted from the request and authorization reads `TRAINER_TEACHER_EMAILS`.

- [ ] **Step 3: Implement owner-derived role and access control**

  Add pure helpers similar to:

  ```python
  def registration_role(email: str, owner_email: str) -> str:
      return "teacher" if owner_email and email.strip().lower() == owner_email else "student"

  def authorize_role(user, required_role, *, owner_email: str = "") -> AccessDecision:
      if not user:
          return AccessDecision(False, "authentication_required", "Authentication required")
      if user.get("role") != required_role:
          return AccessDecision(False, "insufficient_permissions", "Недостаточно прав")
      if required_role == "teacher" and not user.get("emailVerified"):
          return AccessDecision(False, "email_verification_required", "Подтвердите email для доступа к кабинету преподавателя")
      if required_role == "teacher" and str(user.get("email", "")).strip().lower() != owner_email:
          return AccessDecision(False, "teacher_not_allowed", "Роль преподавателя недоступна")
      return AccessDecision(True)
  ```

  Remove `role` from `RegisterRequest`, derive it in `auth_register`, and pass `owner_email_from_env()` to `authorize_role`. Keep the confirmation gate unchanged. When `TRAINER_PUBLIC_URL` is configured, make missing `TRAINER_OWNER_EMAIL` fail startup/config validation with a clear Russian operator error; local development without the variable creates students only.

  Remove `#authRoleLabel`/`#authRole` and the corresponding JavaScript request property. Keep registration, password reset, email verification, and student progress unchanged.

- [ ] **Step 4: Update focused E2E and documentation**

  Replace the multi-teacher registration helper in `tests-e2e/account-workflows.spec.js` with an owner helper that uses the configured owner email and confirms it. Assert the role selector is absent from the registration dialog. Document `TRAINER_OWNER_EMAIL` as required for a deployed teacher cabinet and remove instructions that ask an operator to allowlist multiple teacher emails.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.unit.test_account_service tests.integration.test_api_flows.ApiFlowTest.test_owner_registration_derives_teacher_role tests.integration.test_asgi.FastApiSmokeTest`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/account-workflows.spec.js --grep 'student registers|unverified owner'`

  Expected: all selected tests pass; a non-owner cannot create or use a teacher account.

- [ ] **Step 6: Commit the isolated access-control change**

  ```bash
  git add src/trainer/domain/accounts/service.py src/trainer/api/schemas.py src/trainer/api/controllers/auth.py src/trainer/api/dependencies.py frontend/pages/index.html frontend/js/account/account-auth-controller.js tests/unit/test_account_service.py tests/integration/test_api_flows.py tests/integration/test_asgi.py tests-e2e/account-workflows.spec.js .env.example README.md DEVELOPMENT.md
  git commit -m "feat: restrict teacher access to configured owner"
  ```

### Task 2: Add durable review-request storage and immutable material snapshots

**Files:**
- Create: `migrations/versions/20260819_07_review_requests.py`
- Create: `src/trainer/domain/review_requests.py`
- Create: `src/trainer/infrastructure/database/queries/review_requests.py`
- Create: `src/trainer/services/review_assets.py`
- Modify: `src/trainer/infrastructure/database/queries/__init__.py`
- Modify: `tests/unit/test_grading.py`
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_assignment_assets.py`

**Interfaces:**
- Produces `ReviewRequestSelection(kind: Literal["task", "attempt"], tasks: tuple[int, ...])` and `validate_review_selection(kind: object, tasks: object) -> ReviewRequestSelection`.
- Produces `required_recording_positions(tasks: Iterable[int]) -> set[tuple[int, int | None]]` for both request completion and tests.
- Produces `copy_review_assets_from_env(database, request_id, material_snapshot, created_keys) -> dict` that rewrites `/api/material-assets/<id>` values to `/api/review-assets/<id>` and copies bytes beneath `ASSIGNMENT_ASSET_DIR/review-requests/<request_id>/`.
- Produces read-only query helpers `student_review_requests`, `teacher_review_requests`, and `review_request_detail` that never return storage keys.

- [ ] **Step 1: Write failing tests for selection validation, snapshots, and clean migration**

  Add unit cases that accept `("task", [2])` and `("attempt", [1, 2, 3])`, reject an empty list, duplicate tasks, an out-of-range task, and a `task` request containing more than one task.

  Extend `tests/integration/test_migrations.py` so `EXPECTED_TABLES` includes `review_requests`, `review_request_items`, `review_request_recordings`, and `review_request_assets`; assert the queue and privacy indexes exist after a clean upgrade and a second upgrade is idempotent.

  In `tests/integration/test_assignment_assets.py`, add an integration fixture whose material image URL is `/api/material-assets/<id>`, then assert the returned snapshot uses `/api/review-assets/<id>`, its copied object bytes match, and changing the original material asset cannot change the returned snapshot.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.unit.test_grading tests.integration.test_migrations tests.integration.test_assignment_assets`

  Expected: FAIL because review selection/domain functions, tables, and snapshot copier do not exist.

- [ ] **Step 3: Create the migration and persistence shape**

  Add revision `20260819_07` after `20260818_06` with these tables and constraints:

  ```python
  op.create_table(
      "review_requests",
      sa.Column("id", sa.Integer(), primary_key=True),
      sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
      sa.Column("kind", sa.Text(), nullable=False),
      sa.Column("status", sa.Text(), nullable=False),
      sa.Column("variant_id", sa.Text(), nullable=False),
      sa.Column("run_json", sa.Text(), nullable=False),
      sa.Column("submitted_at", sa.Integer(), nullable=True),
      sa.Column("reviewed_at", sa.Integer(), nullable=True),
      sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
      sa.CheckConstraint("kind IN ('task', 'attempt')", name="review_requests_kind_check"),
      sa.CheckConstraint("status IN ('uploading', 'queued', 'reviewed')", name="review_requests_status_check"),
  )
  ```

  Add `review_request_items(request_id, task_number, task_snapshot_json, scores_json, total_score, max_score)` with `UNIQUE(request_id, task_number)`, `review_request_recordings(item_id, question_number, label, storage_key, mime_type, size_bytes, duration_seconds, created_at)` with one row per task/question, and `review_request_assets(request_id, storage_key, mime_type, size_bytes, created_at)`. Create indexes on `(student_id, submitted_at DESC)`, `(status, submitted_at ASC)`, item request IDs, recording item IDs, and asset request IDs. Downgrade drops only these new tables/indexes.

  Implement selection validation and the snapshot copier without reusing assignment tables. The copier must delete both just-created rows and storage objects if any image copy fails.

- [ ] **Step 4: Implement safe list/detail query contracts**

  Make list payloads expose only request id, student public name/email to the teacher, kind, selected tasks, status, dates, score totals, item-level scores, and recording/asset API URLs. Material snapshot JSON is returned only from the detail helper. Both helpers must filter `status IN ('queued', 'reviewed')` for the teacher, while the student may read their own `uploading` request to retry it.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.unit.test_grading tests.integration.test_migrations tests.integration.test_assignment_assets`

  Expected: all selected tests pass, original material changes do not mutate the copied review snapshot, and no database migration touches legacy assignment data.

- [ ] **Step 6: Commit durable review-request storage**

  ```bash
  git add migrations/versions/20260819_07_review_requests.py src/trainer/domain/review_requests.py src/trainer/infrastructure/database/queries/review_requests.py src/trainer/infrastructure/database/queries/__init__.py src/trainer/services/review_assets.py tests/unit/test_grading.py tests/integration/test_migrations.py tests/integration/test_assignment_assets.py
  git commit -m "feat: add durable review request snapshots"
  ```

### Task 3: Implement private review-request lifecycle, audio, and scoring API

**Files:**
- Create: `src/trainer/api/controllers/review_requests.py`
- Create: `src/trainer/api/routes/review_requests.py`
- Modify: `src/trainer/api/schemas.py`
- Modify: `src/trainer/api/routes/recordings.py`
- Modify: `src/trainer/api/controllers/recordings.py`
- Modify: `src/trainer/main.py`
- Modify: `src/trainer/api/controllers/auth.py`
- Modify: `src/trainer/services/storage_cleanup.py`
- Modify: `tests/integration/test_api_flows.py`
- Modify: `tests/integration/test_storage.py`

**Interfaces:**
- Produces `POST /api/review-requests`, `POST /api/review-requests/{id}/recordings`, `POST /api/review-requests/{id}/complete`, and `GET /api/student/review-requests` for students.
- Produces `GET /api/teacher/review-requests`, `GET /api/teacher/review-requests/{id}`, and `PUT /api/teacher/review-requests/{id}/scores` for the configured owner.
- Produces `GET /api/review-recordings/{id}` and `GET /api/review-assets/{id}`; both use existing `file_response` range behavior.
- Consumes `ReviewRequestCreate(kind: Literal["task", "attempt"], variantId: str, tasks: list[Literal[1,2,3]], run: dict)` and `ReviewScoresRequest(scores: dict[str, dict[str, int]])`.

- [ ] **Step 1: Write failing end-to-end API-flow tests for task and attempt requests**

  Add focused methods in `tests/integration/test_api_flows.py` that:

  ```python
  status, created, _ = self.request("POST", "/api/review-requests", {
      "kind": "task", "variantId": "demo-2026", "tasks": [2],
      "run": {"id": "review-task-2", "status": "completed", "completedTasks": [2]},
  }, student_cookie)
  self.assertEqual(created["reviewRequest"]["status"], "uploading")
  self.assertEqual(self.request("GET", "/api/teacher/review-requests", cookie=owner_cookie)[1]["requests"], [])
  ```

  Upload a valid task 2 recording, complete it, and assert it appears as `queued`. Repeat for an `attempt` request containing tasks 1 and 2, upload all five task 1 questions plus task 2, and assert completion succeeds only after all required positions are present. Assert another student gets `404` for both detail and audio, an owner gets range-capable audio, and a student cannot call the score endpoint. Save scores without `comment`, assert status `reviewed`, totals match `validate_scores`, and the student list exposes totals only after review.

- [ ] **Step 2: Run the focused API test and verify RED**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_student_queues_single_task_for_owner_review tests.integration.test_api_flows.ApiFlowTest.test_student_queues_complete_attempt_for_owner_review`

  Expected: FAIL with route-not-found or missing schema/controller errors.

- [ ] **Step 3: Add request creation and atomic completion**

  In `api/controllers/review_requests.py`, validate request kind/tasks with `validate_review_selection`, load the chosen material with the existing material service, trim it to the selected task numbers, copy its assets, and insert an `uploading` request plus items in one database transaction. If snapshot copying or insert fails, enqueue/delete copied objects exactly as the existing durable storage-cleanup convention requires.

  Completion must calculate required positions with `required_recording_positions`, return a 409 `review_request_incomplete` with a `missing` array if any are absent, and perform:

  ```python
  UPDATE review_requests
  SET status = 'queued', submitted_at = ?
  WHERE id = ? AND student_id = ? AND status = 'uploading'
  ```

  Audit `review_request_created`, `review_request_queued`, and `review_request_scored` with request id, selected tasks, and score totals; never audit audio bytes or storage keys.

- [ ] **Step 4: Add upload, private file access, and score updates**

  Reuse the existing MIME, byte-size, duration, temporary-file, replacement, and cleanup behavior from `recording_create`, but persist rows in `review_request_recordings` only after confirming the item belongs to the student’s `uploading` request. Route uploaded bytes under `review-requests/<request_id>/`.

  Keep old recording routes as archive-only reads for existing data; add new review recording/asset lookups that authorize only the request student or the configured owner. Delegate both to `file_response` so normal, `206`, and invalid `416` Range behavior is identical to private assignment audio.

  `PUT /api/teacher/review-requests/{id}/scores` must validate all selected tasks with `validate_scores`, write each item’s normalized score JSON/totals, set request `reviewed_at`, `reviewer_id`, and status `reviewed`, and permit a later owner correction. There is no comment field in the schema, SQL, response, or UI contract.

- [ ] **Step 5: Wire application routing, body limits, and account cleanup**

  Include `review_requests.router` in `main.py`. Add `^/api/review-requests/\d+/recordings$` to the audio body-limit matcher. Extend account deletion and durable cleanup selection to collect review recording keys and review snapshot asset keys before cascade deletion, using the already-private audio and assignment-asset storage roots. Add an integration test that account deletion leaves no copied review object behind.

- [ ] **Step 6: Run focused tests and verify GREEN**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_storage`

  Expected: single-task and complete-attempt flows pass; incomplete work stays hidden; authorization is enforced; score saves expose no comment payload; file ranges remain correct.

- [ ] **Step 7: Commit the API lifecycle**

  ```bash
  git add src/trainer/api/controllers/review_requests.py src/trainer/api/routes/review_requests.py src/trainer/api/schemas.py src/trainer/api/routes/recordings.py src/trainer/api/controllers/recordings.py src/trainer/main.py src/trainer/api/controllers/auth.py src/trainer/services/storage_cleanup.py tests/integration/test_api_flows.py tests/integration/test_storage.py
  git commit -m "feat: let students submit recordings for review"
  ```

### Task 4: Let students choose and submit a task or complete attempt

**Files:**
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/shared/api.js`
- Modify: `frontend/js/runner/runner-controller.js`
- Create: `frontend/js/account/account-review-requests-controller.js`
- Modify: `frontend/js/account/account-controller.js`
- Modify: `frontend/js/account/account-view.js`
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/styles/base.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/student-teacher.spec.js`

**Interfaces:**
- Produces `createReviewRequest(payload)`, `uploadReviewRecording(requestId, recording)`, and `completeReviewRequest(requestId)` in `shared/api.js`.
- Produces `createAccountReviewRequestsController(ctx)` with `loadStudentReviewRequests()` and `submitReviewRequest(selection)`.
- Consumes runner getters `getCompletedRecordings()`, `getCompletedTasks()`, and `getCompletedRun()`; expose these as read-only copies rather than sharing mutable recorder arrays.

- [ ] **Step 1: Write failing JS and Playwright tests for explicit student submission**

  In `tests-js/unit/views.test.js`, add `studentReviewRequestsMarkup` assertions that escape a student-controlled title, render `На разборе` without scores, and render `Разобрано: 7/7` only when `status === "reviewed"`.

  In `tests-e2e/student-teacher.spec.js`, replace the assigned-work setup with a student completing task 2, opening the result screen, choosing `Отправить одно задание`, and asserting the teacher queue is empty until that explicit click succeeds. Add a second scenario that completes tasks 1–3, chooses `Отправить всю попытку`, and asserts three task rows are shown in the student’s history.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `npm test -- --test-name-pattern='review request'`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/student-teacher.spec.js --grep 'single task|complete attempt'`

  Expected: FAIL because the result screen only exposes downloads and assigned runs submit automatically.

- [ ] **Step 3: Add a deliberate review-request chooser to the result screen**

  Add an initially hidden result-screen panel with two radio choices: `Одно задание` and `Всю попытку`. The one-task select contains only completed tasks; `Всю попытку` contains every completed task of the run and is enabled whenever at least one recording exists, including a one-task attempt. The submit button is disabled when no recording exists and reports upload/retry errors next to the panel.

  Remove automatic `submitAssignedRun()` from `finishRun()`. Build the selected request payload from immutable copies of the completed run/tasks/recordings, create the request, upload only recordings whose task belongs to the selection, complete the request, and retain the current retry button without creating a duplicate request id.

- [ ] **Step 4: Add the student review history**

  Implement `account-review-requests-controller.js` to load `/api/student/review-requests` after login and after a successful send. Replace the assignments panel on the home screen with `Мои разборы`; each row shows type, selected tasks, submitted date, `На разборе` or `Разобрано`, and scores only in `reviewed`. Do not render teacher identity, group, due date, assignment title, comment, or another student’s data.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `npm test`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/student-teacher.spec.js --grep 'single task|complete attempt'`

  Expected: student sends nothing until an explicit action, both selection formats upload the right recordings, and queued scores remain hidden.

- [ ] **Step 6: Commit student submission UI**

  ```bash
  git add frontend/pages/index.html frontend/js/shared/api.js frontend/js/runner/runner-controller.js frontend/js/account/account-review-requests-controller.js frontend/js/account/account-controller.js frontend/js/account/account-view.js frontend/js/runner/app.js frontend/styles/base.css tests-js/unit/views.test.js tests-e2e/student-teacher.spec.js
  git commit -m "feat: add student review request flow"
  ```

### Task 5: Replace the teacher cabinet with a score-only review queue

**Files:**
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/account/account-reviews-controller.js`
- Modify: `frontend/js/account/account-controller.js`
- Modify: `frontend/js/account/account-view.js`
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/styles/base.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/student-teacher.spec.js`

**Interfaces:**
- Consumes `GET /api/teacher/review-requests?student=&task=&status=` and detail payloads from Task 3.
- Produces `loadTeacherReviewRequests()`, `showStudentReviewHistory(requestId)`, and `saveReviewScores(form)` in `account-reviews-controller.js`.
- Uses existing `collectReviewScores(form, tasks)` and `reviewFields(tasks, existingScores)`; no comment textarea is passed to the API.

- [ ] **Step 1: Write failing markup and browser tests for the new teacher queue**

  Replace `teacherSubmissionsMarkup` tests with `teacherReviewRequestsMarkup` tests asserting that group name, due date, assignment title, and `textarea` are absent; audio URLs and escaped student names are present; a `reviewed` item shows its score.

  Add a Playwright assertion that the configured owner opens a dialog titled `Очередь разбора`, sees a queued student request, fills criterion scores, saves, and the student’s history changes to `Разобрано`. Assert no controls labelled `Создать группу`, `Назначить`, or `Комментарий` exist.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `npm test -- --test-name-pattern='review queue'`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/student-teacher.spec.js --grep 'owner scores queued review'`

  Expected: FAIL because the cabinet still renders groups, assignments, and a comment field.

- [ ] **Step 3: Render queue and detail data without legacy assignment concepts**

  Change the teacher modal title/lead to `Очередь разбора`. Keep the material editor entry. Replace group/assignment sections with a queue count, filters for student name/email, task number, and `queued`/`reviewed`, an accessible empty state, and request cards. A card shows student, request type, date, task numbers, private audio controls, score form, and a button for that student’s prior review requests.

  Rewrite `loadTeacherSubmissions`, `showAttemptHistory`, and `submitReview` into methods using review-request URLs and `PUT` scores. The submit payload must be exactly:

  ```js
  { scores: collectReviewScores(form, tasks) }
  ```

  Do not append `comment`, call export endpoints, or query groups. Preserve escaped rendering and existing focus/inert modal behavior.

- [ ] **Step 4: Rewire account refresh and modal events**

  Remove group/assignment controller dependencies from `account-controller.js` and `runner/app.js`. On owner login/open, load only review requests; on student login, load only their own review history. Reset both lists on logout. Replace obsolete DOM listeners with queue filter and score-save listeners; every referenced id must exist in `index.html`.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `npm test`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/student-teacher.spec.js`

  Expected: the owner can listen and score requests, the student sees saved scores, and no text-comment or assignment controls remain.

- [ ] **Step 6: Commit the teacher queue UI**

  ```bash
  git add frontend/pages/index.html frontend/js/account/account-reviews-controller.js frontend/js/account/account-controller.js frontend/js/account/account-view.js frontend/js/runner/app.js frontend/styles/base.css tests-js/unit/views.test.js tests-e2e/student-teacher.spec.js
  git commit -m "feat: replace teacher assignments with review queue"
  ```

### Task 6: Retire active group and assignment paths while preserving archived data

**Files:**
- Delete: `frontend/js/account/account-assignments-controller.js`
- Delete: `frontend/js/account/account-groups-controller.js`
- Modify: `src/trainer/api/routes/groups.py`
- Modify: `src/trainer/api/controllers/groups.py`
- Modify: `src/trainer/api/routes/work.py`
- Modify: `src/trainer/api/controllers/work.py`
- Modify: `src/trainer/api/routes/recordings.py`
- Modify: `src/trainer/main.py`
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`
- Modify: `tests/integration/test_api_flows.py`
- Modify: `tests-e2e/account-workflows.spec.js`
- Modify: `tests-e2e/variants-catalog.spec.js`
- Modify: `tests-js/unit/views.test.js`

**Interfaces:**
- Keeps `/api/progress` and archive-safe `GET /api/recordings/{id}`; removes active creation/listing routes for groups, memberships, assignments, assignment submissions, resend, assignment assets, assignment review, and exports.
- Keeps legacy database tables and existing private blobs untouched; new code must not query them for live teacher/student screens.

- [ ] **Step 1: Write failing route-retirement and UI tests**

  In `tests/integration/test_api_flows.py`, assert `POST /api/teacher/groups`, `POST /api/groups/join`, `POST /api/teacher/assignments`, and `POST /api/assignments/1/submissions` return the normal 404 API contract. Assert `/api/progress` still reads and writes a valid student document.

  Replace the assignment resend E2E test with a regression that opens both student and owner cabinets and asserts there are no group-code, assignment, deadline, resend, CSV, or PDF controls. Update catalog E2E setup to use a direct review request rather than an assigned snapshot.

- [ ] **Step 2: Run focused retirement tests and verify RED**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_legacy_assignment_routes_are_not_active`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/variants-catalog.spec.js --grep 'no assignment controls|direct review request'`

  Expected: FAIL because the legacy routes and controls are still registered.

- [ ] **Step 3: Remove active legacy endpoints and frontend controllers**

  Retain only progress handlers in `routes/groups.py`/`controllers/groups.py`; remove teacher groups, student membership, and dashboard handlers. Remove legacy assignment/submission/review/export/assignment-asset routes from `routes/work.py`; do not remove the database tables or their storage cleanup references. Remove obsolete frontend controllers, imports, selectors, markup functions, event handlers, and CSS that only support group/assignment creation.

  Keep `GET /api/recordings/{id}` as a private archive reader for data that existed before migration, but do not place legacy recordings in new lists. New requests always use Task 3’s review-recording route.

- [ ] **Step 4: Update documentation and fixtures to the single-owner model**

  Rewrite README teacher/student instructions around voluntary review requests and oral feedback. Remove group-code and assignment instructions from README/DEVELOPMENT. Update browser/API fixtures so one configured owner and independently registered students cover the same security behavior without creating legacy groups.

- [ ] **Step 5: Run focused tests and verify GREEN**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_asgi`

  Run: `npm test`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/variants-catalog.spec.js`

  Expected: old active APIs are absent, progress remains intact, and every browser scenario uses direct voluntary review requests.

- [ ] **Step 6: Commit migration away from assignments**

  ```bash
  git add src/trainer/api/routes/groups.py src/trainer/api/controllers/groups.py src/trainer/api/routes/work.py src/trainer/api/controllers/work.py src/trainer/api/routes/recordings.py src/trainer/main.py README.md DEVELOPMENT.md tests/integration/test_api_flows.py tests/integration/test_asgi.py tests-e2e/account-workflows.spec.js tests-e2e/variants-catalog.spec.js tests-js/unit/views.test.js
  git rm frontend/js/account/account-assignments-controller.js frontend/js/account/account-groups-controller.js
  git commit -m "refactor: retire assignment workflow"
  ```

### Task 7: Verify upgrade safety, complete workflows, and operator handoff

**Files:**
- Modify: `tests/integration/test_migrations.py`
- Modify: `tests/integration/test_accounts.py`
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`

**Interfaces:**
- Consumes all owner, review-request, private-storage, and UI contracts from Tasks 1–6.
- Produces documented deployment prerequisites: `TRAINER_OWNER_EMAIL`, owner email verification, and the fact that legacy assignment data is retained but inactive.

- [ ] **Step 1: Write failing migration and account-deletion regressions**

  Add a migration fixture that creates legacy group/assignment/submission rows before upgrade, upgrades to head, and asserts those rows still exist alongside the new review tables. Add an account-deletion test that creates a queued review request with audio and copied image assets, deletes the student, processes cleanup jobs, and asserts neither object remains in private storage.

- [ ] **Step 2: Run the focused safety tests and verify RED**

  Run: `PYTHONPATH=src ../../.venv/bin/python -m unittest tests.integration.test_migrations tests.integration.test_accounts`

  Expected: FAIL until retention and cleanup behavior are covered by the implementation from earlier tasks.

- [ ] **Step 3: Fill any implementation gaps exposed by the regressions**

  Make only the smallest corrections required for migration idempotency, legacy-row retention, or review-object cleanup. Preserve the no-comments/no-assignments constraints; do not add new product behavior during this task.

- [ ] **Step 4: Run final required verification**

  Run: `PYTHONPATH=src make check PYTHON=../../.venv/bin/python NPM=npm`

  Run: `PYTHONPATH=src E2E_PYTHON=../../.venv/bin/python make test-e2e PYTHON=../../.venv/bin/python NPM=npm`

  Expected: all pre-commit hooks,  JavaScript tests, unit tests, integration tests, coverage threshold, and every Playwright scenario pass.

- [ ] **Step 5: Commit final verification fixes and documentation**

  ```bash
  git add tests/integration/test_migrations.py tests/integration/test_accounts.py README.md DEVELOPMENT.md
  git commit -m "test: cover review queue migration safety"
  ```
