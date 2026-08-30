# Personal Recording Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give registered students a private, playable six-calendar-month audio archive while guest recordings never leave the browser.

**Architecture:** Audio blobs are uploaded only after a registered student finishes a run. Metadata and private storage keys live in a new `personal_recordings` table; API routes are owner-scoped. An expiry sweep removes archive and review metadata transactionally and enqueues physical deletion in the existing durable storage-cleanup queue.

**Tech Stack:** FastAPI, Pydantic, SQLite/Alembic PostgreSQL migrations, private filesystem/S3 storage adapter, vanilla JavaScript, Playwright, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-28-personal-recording-archive-design.md`

## Global Constraints

- Keep guest audio in memory only; never call a personal-recording endpoint for a guest.
- Use six calendar months in UTC, not a fixed number of seconds or days.
- All personal audio remains in `AUDIO_DIR` and is exposed only through authenticated owner-scoped streaming routes.
- Keep review-request copies separate and expire them under the same six-month rule.
- An expired row must become unreadable before the storage object is physically deleted.
- Preserve existing review upload, scoring, account deletion, local-history, and range-response behavior.
- `clearHistory()` clears progress only; it must not delete archived audio.
- Use test-first red/green cycles; run `make check` and `make test-e2e` before completion.

---

## File Structure

- `src/trainer/domain/recording_retention.py` — pure UTC calendar-month calculation and expiry predicate.
- `src/trainer/services/personal_recordings.py` — archive write/list/read metadata operations and archive key creation.
- `src/trainer/services/storage_cleanup.py` — expiry sweep plus durable physical deletion queue.
- `src/trainer/api/controllers/personal_recordings.py` — authenticated HTTP actions, validation and owner-scoped file lookup.
- `src/trainer/api/routes/personal_recordings.py` — FastAPI routes for upload, list and stream.
- `src/trainer/api/schemas.py` — bounded archive upload metadata schema.
- `migrations/versions/20260828_08_personal_recordings.py` — PostgreSQL/Alembic table and review expiry column.
- `src/trainer/infrastructure/database/sqlite_migrations.py` — SQLite equivalent and backfill.
- `frontend/js/account/account-personal-recordings-controller.js` — archive upload, list loading and safe markup rendering.
- `frontend/js/shared/api.js` — archive API client helpers.
- `frontend/js/runner/app.js` and `frontend/js/account/account-controller.js` — trigger upload after a completed run and load archive history.
- `frontend/pages/index.html`, `frontend/js/shared/material-list.js`, `frontend/js/catalog/variant-catalog.js`, `frontend/js/catalog/variants-page.js`, `frontend/styles/base.css`, `frontend/styles/pages/variants.css` — registration disclosure, guest access notices and archive history UI.
- `scripts/cleanup_storage.py`, `docs/runbooks/recording-retention.md`, `DEVELOPMENT.md` — daily retention operation and runbook.

### Task 1: Add retention rule and portable database schema

**Files:**
- Create: `src/trainer/domain/recording_retention.py`
- Create: `migrations/versions/20260828_08_personal_recordings.py`
- Modify: `src/trainer/infrastructure/database/sqlite_migrations.py`
- Modify: `tests/unit/test_recording_retention.py`
- Modify: `tests/integration/test_migrations.py`

**Interfaces:**
- Produces `RETENTION_MONTHS = 6`, `expires_at(created_at: int) -> int`, and `is_expired(expires_at: int, now: int) -> bool`.
- Produces table `personal_recordings` and nullable-to-backfilled `review_request_recordings.expires_at` with indexes on expiry lookup.

- [ ] **Step 1: Write failing pure-rule and migration tests**

```python
from trainer.domain.recording_retention import expires_at, is_expired

def test_expiry_uses_calendar_months_and_clamps_month_end():
    created = int(datetime(2026, 8, 31, tzinfo=UTC).timestamp())
    assert datetime.fromtimestamp(expires_at(created), UTC) == datetime(2027, 2, 28, tzinfo=UTC)
    assert is_expired(expires_at(created), expires_at(created)) is True
```

Add migration assertions that SQLite has `personal_recordings` with `student_id`, `run_id`, `storage_key`, `expires_at`, and an `expires_at` index; create an old review row, upgrade it, and assert its expiry is derived from `created_at`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_recording_retention tests.integration.test_migrations -v`

Expected: FAIL because the retention module/table/column do not exist.

- [ ] **Step 3: Implement the pure UTC rule and both migrations**

```python
def expires_at(created_at: int) -> int:
    created = datetime.fromtimestamp(created_at, UTC)
    month = created.month - 1 + RETENTION_MONTHS
    year, month = created.year + month // 12, month % 12 + 1
    day = min(created.day, calendar.monthrange(year, month)[1])
    return int(created.replace(year=year, month=month, day=day).timestamp())
```

Create `personal_recordings` with owner/run/position uniqueness, private storage metadata and a `(student_id, expires_at DESC)` index. Add `expires_at` to review recordings, fill it from each row’s `created_at`, then enforce a non-null expiry in both database implementations.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_recording_retention tests.integration.test_migrations -v`

Expected: PASS with clean-database, upgrade and idempotency coverage.

- [ ] **Step 5: Commit the schema slice**

```bash
git add src/trainer/domain/recording_retention.py migrations/versions/20260828_08_personal_recordings.py src/trainer/infrastructure/database/sqlite_migrations.py tests/unit/test_recording_retention.py tests/integration/test_migrations.py
git commit -m "feat: add personal recording retention schema"
```

### Task 2: Implement private archive API and storage lifecycle

**Files:**
- Create: `src/trainer/services/personal_recordings.py`
- Create: `src/trainer/api/controllers/personal_recordings.py`
- Create: `src/trainer/api/routes/personal_recordings.py`
- Modify: `src/trainer/api/schemas.py`
- Modify: `src/trainer/main.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Consumes `expires_at`, `validate_duration`, `write_recording`, `FileResult`, authenticated user dependency and `AUDIO_DIR`.
- Produces `POST /api/personal-recordings`, `GET /api/personal-recordings`, and `GET /api/personal-recordings/{recording_id}`.
- Upload metadata is `PersonalRecordingUpload(runId, variantId, taskNumber, questionNumber, label)`; body is raw supported audio.

- [ ] **Step 1: Write failing owner-bound API tests**

```python
status, payload = self.request_audio(
    "/api/personal-recordings?runId=run-1&variantId=open-2026&taskNumber=2&label=Answer",
    sample_audio,
    student_cookie,
)
self.assertEqual(status, 201)
recording_id = payload["recording"]["id"]
self.assertEqual(self.request("GET", "/api/personal-recordings", cookie=student_cookie)[0], 200)
self.assertEqual(self.request_bytes(f"/api/personal-recordings/{recording_id}", other_cookie)[0], 404)
self.assertEqual(self.request("GET", "/api/personal-recordings")[0], 401)
```

Upload the same `(student_id, run_id, task_number, question_number)` twice and assert the second request returns `409` with `personal_recording_exists`; also assert invalid task/question/MIME is rejected and storage objects are private rather than written under `public/`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest -v`

Expected: FAIL with missing routes or 404 responses.

- [ ] **Step 3: Add schema, service, controller and routes**

```python
def personal_recording_get(recording_id: int, user: dict) -> FileResult:
    row = database.execute(
        "SELECT storage_key,mime_type,size_bytes FROM personal_recordings WHERE id=? AND student_id=? AND expires_at>?",
        (recording_id, user["id"], int(time.time())),
    ).fetchone()
    if not row:
        raise ApiError("recording_not_found", "Запись не найдена", HTTPStatus.NOT_FOUND)
    return FileResult(key=row["storage_key"], mime_type=row["mime_type"], size_bytes=row["size_bytes"])
```

Validate raw audio with the existing duration/size rules, stage the body in `DATA_DIR/tmp`, write to `personal-recordings/{student_id}/{token}.{extension}`, and insert metadata with the computed expiry in a write transaction. On any post-write failure, enqueue the key for cleanup; do not disclose a storage key in JSON.

- [ ] **Step 4: Run focused integration tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest -v`

Expected: PASS, including 401 for a guest and 404 for a different authenticated user.

- [ ] **Step 5: Commit the API slice**

```bash
git add src/trainer/services/personal_recordings.py src/trainer/api/controllers/personal_recordings.py src/trainer/api/routes/personal_recordings.py src/trainer/api/schemas.py src/trainer/main.py tests/integration/test_api_flows.py
git commit -m "feat: add private personal recording archive api"
```

### Task 3: Expire archive and review audio through durable cleanup

**Files:**
- Modify: `src/trainer/services/storage_cleanup.py`
- Modify: `src/trainer/services/accounts.py`
- Modify: `src/trainer/api/runtime.py`
- Modify: `scripts/cleanup_storage.py`
- Modify: `tests/unit/test_application_services.py`
- Modify: `tests/unit/test_storage_cleanup_command.py`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Consumes `personal_recordings.expires_at`, `review_request_recordings.expires_at`, `enqueue_cleanup_job`, and private audio root.
- Produces `expire_recordings(database, *, now: int, limit: int = 500) -> int` and a cleanup command that first expires rows then deletes queued keys.

- [ ] **Step 1: Write failing expiry and account-deletion tests**

```python
with database:
    database.execute(
        """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
           label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
           VALUES (1,'run-1','open-2026',2,NULL,'Ответ','personal-recordings/1/a.webm',
           'audio/webm',10,1.0,1,10)"""
    )
expired = expire_recordings(database, now=10, limit=50)
assert expired == 1
assert database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0] == 0
assert json.loads(database.execute("SELECT audio_keys_json FROM storage_cleanup_jobs").fetchone()[0]) == ["personal-recordings/1/a.webm"]
```

Mock a failing audio adapter and assert the metadata remains absent, the cleanup job remains pending, and a second successful processor deletes the key. Extend the account-deletion fixture to include a personal key and assert it joins the same cleanup job.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_api_flows -v`

Expected: FAIL because expiry selection and personal keys are not handled.

- [ ] **Step 3: Implement transactional expiry and operation entry points**

```python
def expire_recordings(database, *, now: int | None = None, limit: int = 500) -> int:
    moment = int(time.time()) if now is None else int(now)
    archive_rows = database.execute(
        "SELECT id,storage_key FROM personal_recordings WHERE expires_at<=? ORDER BY expires_at,id LIMIT ?",
        (moment, limit),
    ).fetchall()
    review_rows = database.execute(
        "SELECT id,storage_key FROM review_request_recordings WHERE expires_at<=? ORDER BY expires_at,id LIMIT ?",
        (moment, max(0, limit - len(archive_rows))),
    ).fetchall()
    database.executemany("DELETE FROM personal_recordings WHERE id=?", [(row["id"],) for row in archive_rows])
    database.executemany("DELETE FROM review_request_recordings WHERE id=?", [(row["id"],) for row in review_rows])
    enqueue_cleanup_job(database, audio_keys=[row["storage_key"] for row in [*archive_rows, *review_rows]], material_keys=[], assignment_keys=[])
    return len(archive_rows) + len(review_rows)
```

Use `begin_immediate(database)` before both table scans. Delete metadata and enqueue deduplicated audio keys in the same transaction. Add archive keys to account storage collection. Call expiry before `process_cleanup_jobs` in the CLI and best-effort `runtime.init_database`; return non-zero from the command when queued deletions remain.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_api_flows -v`

Expected: PASS with failed-storage retry and expired-route 404 coverage.

- [ ] **Step 5: Commit the retention slice**

```bash
git add src/trainer/services/storage_cleanup.py src/trainer/services/accounts.py src/trainer/api/runtime.py scripts/cleanup_storage.py tests/unit/test_application_services.py tests/unit/test_storage_cleanup_command.py tests/integration/test_api_flows.py
git commit -m "feat: expire archived recordings after six months"
```

### Task 4: Upload registered runs and render the archive in history

**Files:**
- Create: `frontend/js/account/account-personal-recordings-controller.js`
- Modify: `frontend/js/shared/api.js`
- Modify: `frontend/js/account/account-controller.js`
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/pages/index.html`
- Modify: `frontend/styles/base.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/student-teacher.spec.js`

**Interfaces:**
- Consumes archive upload/list client calls, `account.user`, `runner.getCompletedRun()`, `runner.getCompletedRecordings()`, and `formatHistoryDate`.
- Produces `archiveCompletedRun(run, recordings)`, `loadPersonalRecordings()`, and `personalRecordingsMarkup(recordings)`.

- [ ] **Step 1: Write failing markup and browser tests**

```javascript
test("personal recording markup escapes labels and shows the expiry date", () => {
  const markup = personalRecordingsMarkup([{ id: 7, label: "<answer>", expiresAt: 1800000000 }]);
  assert.match(markup, /&lt;answer&gt;/);
  assert.match(markup, /\/api\/personal-recordings\/7/);
  assert.match(markup, /Удалится/);
});
```

In Playwright, finish task 2 as a guest and assert no `POST /api/personal-recordings` request occurs. Repeat as a registered student, await the archive request, open history, and assert an audio element with an owner-only archive URL and a visible deletion date.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test && npm exec playwright test tests-e2e/student-teacher.spec.js -- --grep 'personal archive'`

Expected: FAIL because no archive client, markup or upload exists.

- [ ] **Step 3: Implement archive client, controller and history UI**

```javascript
async function archiveCompletedRun(run, recordings) {
  if (!getUser() || !run || !recordings.length) return;
  for (const recording of recordings) {
    await uploadPersonalRecording(run, recording);
  }
  await loadPersonalRecordings();
}
```

Call the method from `onRunFinished` without awaiting it before rendering the result screen. Update `#submissionStatus` to show successful archive sync or a retry-safe warning; preserve local playback/download. Add an archive section to `#progressModal`; render `<audio controls src="/api/personal-recordings/{id}">` with escaped labels and a localized expiry date. Do not alter `clearHistory()`.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `npm test && npm exec playwright test tests-e2e/student-teacher.spec.js -- --grep 'personal archive'`

Expected: PASS for guest non-upload, registered upload and playable history.

- [ ] **Step 5: Commit the archive UI slice**

```bash
git add frontend/js/account/account-personal-recordings-controller.js frontend/js/shared/api.js frontend/js/account/account-controller.js frontend/js/runner/app.js frontend/pages/index.html frontend/styles/base.css tests-js/unit/views.test.js tests-e2e/student-teacher.spec.js
git commit -m "feat: show personal recording archive in account history"
```

### Task 5: Add registration and guest-access disclosures

**Files:**
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/account/account-auth-controller.js`
- Modify: `frontend/js/shared/material-list.js`
- Modify: `frontend/js/catalog/variant-catalog.js`
- Modify: `frontend/js/catalog/variants-page.js`
- Modify: `frontend/styles/base.css`
- Modify: `frontend/styles/pages/variants.css`
- Modify: `tests-e2e/reference.spec.js`
- Modify: `tests-e2e/variants-catalog.spec.js`

**Interfaces:**
- Consumes the existing auth modal `setAuthMode`, material list and catalog render functions.
- Produces a register-only retention notice and guest-only calls to the existing `?account=1` modal route.

- [ ] **Step 1: Write failing disclosure tests**

```javascript
await page.goto("/");
await expect(page.locator("#guestArchiveNotice")).toContainText("После регистрации доступны остальные варианты");
await page.locator("#authButton").click();
await expect(page.locator("#recordingRetentionNotice")).toBeHidden();
await page.locator("#registerTab").click();
await expect(page.locator("#recordingRetentionNotice")).toContainText("6 месяцев");
```

In the guest catalog test, assert the registration callout is visible and points to `index.html?account=1`; authenticate a context and assert guest-only callouts are absent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm exec playwright test tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js -- --grep 'registration|guest archive'`

Expected: FAIL because disclosure selectors and text are absent.

- [ ] **Step 3: Implement the two clear disclosures**

```javascript
$("recordingRetentionNotice").classList.toggle("hidden", mode !== "register");
```

Place the registration disclosure immediately before `#authSubmitBtn`. Render the home notice beside `#materialList` and render the catalog notice when the materials response identifies an unauthenticated guest. Use a normal link to `index.html?account=1`; style notices as small cream cards with the existing gold accent and ensure they remain readable on mobile.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `npm exec playwright test tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js -- --grep 'registration|guest archive'`

Expected: PASS for text, mode switching, link target and authenticated absence.

- [ ] **Step 5: Commit the disclosure slice**

```bash
git add frontend/pages/index.html frontend/js/account/account-auth-controller.js frontend/js/shared/material-list.js frontend/js/catalog/variant-catalog.js frontend/js/catalog/variants-page.js frontend/styles/base.css frontend/styles/pages/variants.css tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js
git commit -m "feat: disclose registration access and recording retention"
```

### Task 6: Document daily retention operation

**Files:**
- Create: `docs/runbooks/recording-retention.md`
- Modify: `DEVELOPMENT.md`
- Modify: `tests/unit/test_storage_cleanup_command.py`

**Interfaces:**
- Consumes `python -m scripts.cleanup_storage`, which prints completed, expired, failed and pending counts.
- Produces a daily cron/systemd timer example and a recovery procedure for pending cleanup jobs.

- [ ] **Step 1: Write failing command-output test**

```python
with patch("scripts.cleanup_storage.expire_recordings", return_value=2):
    self.assertEqual(main(), 0)
    self.assertIn("expired=2", captured_stdout.getvalue())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_storage_cleanup_command -v`

Expected: FAIL because the command does not report an expiry sweep.

- [ ] **Step 3: Finalize command wording and write the runbook**

Document a daily invocation such as `15 3 * * * /app/.venv/bin/python -m scripts.cleanup_storage`, sample successful output `expired=2 completed=2 failed=0 pending=0`, and recovery steps that keep database metadata deleted while retrying private storage cleanup. Link the runbook from `DEVELOPMENT.md`.

- [ ] **Step 4: Run documentation-adjacent checks**

Run: `.venv/bin/python -m unittest tests.unit.test_storage_cleanup_command -v && make check`

Expected: PASS with `expired` output and repository checks clean.

- [ ] **Step 5: Commit the operation documentation**

```bash
git add docs/runbooks/recording-retention.md DEVELOPMENT.md tests/unit/test_storage_cleanup_command.py scripts/cleanup_storage.py
git commit -m "docs: add recording retention runbook"
```

### Task 7: Verify the integrated feature

**Files:**
- Verify: all files from Tasks 1–6

- [ ] **Step 1: Run migration and API regression coverage**

Run: `.venv/bin/python -m unittest tests.unit.test_recording_retention tests.unit.test_application_services tests.unit.test_storage_cleanup_command tests.integration.test_migrations tests.integration.test_api_flows -v`

Expected: PASS with calendar expiry, owner isolation, account cleanup and failed-storage retry.

- [ ] **Step 2: Run JavaScript and browser coverage**

Run: `npm test && npm exec playwright test tests-e2e/reference.spec.js tests-e2e/variants-catalog.spec.js tests-e2e/student-teacher.spec.js`

Expected: PASS with guest non-upload, registered playback and visible disclosures.

- [ ] **Step 3: Run required repository checks**

Run: `make check && make test-e2e && git diff --check`

Expected: all commands exit 0; Playwright reports zero failed tests.

- [ ] **Step 4: Review retention requirements against the spec**

Confirm each item: guest audio never uploads; registered audio is owner-only and playable; all personal and review audio gets six calendar months; expired metadata returns 404 before storage cleanup; cleanup retry is durable; UI disclosures are present; runbook schedules daily cleanup.
