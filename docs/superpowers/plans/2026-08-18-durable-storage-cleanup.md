# Durable Storage Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure private storage objects remain queued for deletion until a successful, repeatable cleanup finishes.

**Architecture:** SQL stores opaque storage keys before database rows are deleted. A focused service deletes each key idempotently, records an error on failure, and is invoked after account deletion, at startup and by a command-line recovery tool.

**Tech Stack:** SQLite/Alembic, Python service layer, local/S3 storage adapter, unittest.

**Spec:** `docs/superpowers/specs/2026-08-18-core-reliability-design.md`

## Global Constraints

- The migration in `2026-08-18-submission-integrity.md` is present first and owns `storage_cleanup_jobs`.
- A failed cleanup never rolls back a committed account deletion and never blocks application startup.
- Do not log keys, audio contents, session tokens or credentials.
- Treat deletion of an already-missing object as successful.
- Run focused tests, `make check`, and the relevant local storage smoke test after implementation.

---

### Task 1: Add cleanup job schema to the submission-state migration

**Files:**
- Modify: `migrations/versions/20260818_06_submission_states.py`
- Modify: `tests/integration/test_migrations.py:16-120`
- Test: `tests/integration/test_migrations.py`

**Interfaces:**
- Produces: `storage_cleanup_jobs(id, audio_keys_json, material_keys_json, assignment_keys_json, attempts, last_error, created_at, updated_at)` and `storage_cleanup_jobs_created_idx`.
- Consumes: one `20260818_06` migration revision, not a second competing revision.

- [ ] **Step 1: Write a failing schema assertion**

  Add `storage_cleanup_jobs` to `EXPECTED_TABLES`; assert the exact columns and the created-time index on a clean database.

  ```python
  self.assertEqual(cleanup_columns, {
      "id", "audio_keys_json", "material_keys_json", "assignment_keys_json",
      "attempts", "last_error", "created_at", "updated_at",
  })
  ```

- [ ] **Step 2: Run the migration test to verify failure**

  Run: `python -m pytest tests/integration/test_migrations.py -k cleanup -v`.

  Expected: FAIL because the table does not exist.

- [ ] **Step 3: Create the table in the existing new revision**

  In `upgrade`, call `op.create_table` with JSON text columns, `attempts INTEGER NOT NULL DEFAULT 0`, nullable `last_error`, and integer timestamps; add the created-time index. `downgrade` drops the index and table before reverting the submissions constraint.

- [ ] **Step 4: Re-run migration tests**

  Run: `python -m pytest tests/integration/test_migrations.py -v`.

  Expected: PASS for a clean database and an upgrade from the prior head.

- [ ] **Step 5: Amend the schema-foundation commit before it is shared**

  ```bash
  git add migrations/versions/20260818_06_submission_states.py tests/integration/test_migrations.py
  git commit --amend --no-edit
  ```

### Task 2: Implement persisted cleanup jobs

**Files:**
- Create: `src/trainer/services/storage_cleanup.py`
- Modify: `src/trainer/services/accounts.py:72-102`
- Test: `tests/unit/test_application_services.py`

**Interfaces:**
- Produces: `enqueue_cleanup_job(database, *, audio_keys, material_keys, assignment_keys, now) -> int` and `process_cleanup_jobs(connect_factory, roots, *, limit=50) -> CleanupSummary`.
- Consumes: `storage_from_env(root).delete(key)`.

- [ ] **Step 1: Write unit tests for persistence and retry**

  Use a temporary SQLite database with the head schema and mocked storage adapters. Assert a successful job removes its row, a failing key increments `attempts` and stores only the exception type/message, and a second run clears the same row after the adapter succeeds.

  ```python
  summary = process_cleanup_jobs(connect, roots, limit=10)
  self.assertEqual((summary.completed, summary.failed), (0, 1))
  self.assertEqual(job["attempts"], 1)
  ```

- [ ] **Step 2: Run the tests to verify failure**

  Run: `python -m pytest tests/unit/test_application_services.py -k cleanup_job -v`.

  Expected: import error because the service is not defined.

- [ ] **Step 3: Implement queue creation and idempotent processing**

  Serialize only de-duplicated nonempty string keys. Read jobs oldest first, attempt every root/key even after one failure, delete the row only when all three groups complete, otherwise increment attempts and update `last_error`/`updated_at`. Catch `FileNotFoundError` as success; return counts without printing keys.

  ```python
  if failures:
      database.execute("UPDATE storage_cleanup_jobs SET attempts=attempts+1, last_error=?, updated_at=? WHERE id=?", (...))
  else:
      database.execute("DELETE FROM storage_cleanup_jobs WHERE id=?", (job_id,))
  ```

- [ ] **Step 4: Run focused service tests**

  Run: `python -m pytest tests/unit/test_application_services.py -v`.

  Expected: PASS, including existing `delete_account_storage` tests until that obsolete wrapper is removed in the next task.

- [ ] **Step 5: Commit the service**

  ```bash
  git add src/trainer/services/storage_cleanup.py src/trainer/services/accounts.py tests/unit/test_application_services.py
  git commit -m "feat: persist failed storage cleanup"
  ```

### Task 3: Wire account deletion, startup and recovery command

**Files:**
- Modify: `src/trainer/api/controllers/auth.py:293-366`
- Modify: `src/trainer/api/runtime.py:21-28`
- Create: `scripts/cleanup_storage.py`
- Modify: `tests/integration/test_api_flows.py:150-180`
- Create: `tests/unit/test_storage_cleanup_command.py`

**Interfaces:**
- Consumes: `enqueue_cleanup_job` and `process_cleanup_jobs` from `storage_cleanup.py`.
- Produces: account deletion that enqueues keys transactionally, startup best-effort cleanup, and `python -m scripts.cleanup_storage` exit status 0 only when no failures remain.

- [ ] **Step 1: Write failing integration and command tests**

  Replace the old failure-only account test with one that injects a failing storage adapter, deletes an account, and confirms the account is gone while one cleanup job remains. Run the processor with a successful adapter and assert the job disappears. Add a command test expecting exit 1 when summary.failed is nonzero.

  ```python
  self.assertIsNone(database.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone())
  self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 1)
  ```

- [ ] **Step 2: Run the tests to verify failure**

  Run: `python -m pytest tests/integration/test_api_flows.py -k storage_cleanup tests/unit/test_storage_cleanup_command.py -v`.

  Expected: FAIL because no persistent job exists and no command module exists.

- [ ] **Step 3: Enqueue before deleting and process after commit**

  In `account_delete`, collect keys as today, call `enqueue_cleanup_job()` in the same connection before `DELETE FROM users`, then call `process_cleanup_jobs()` after the context commits. Replace broad exception logging with summary-count logging only. In `init_database`, call the processor with the three runtime roots inside `try/except`, logging counts but continuing startup.

- [ ] **Step 4: Add recovery command**

  In `scripts/cleanup_storage.py`, initialize runtime, call the processor with a high bounded limit, print only `completed=<n> failed=<n> pending=<n>`, and return `1` if `failed` or `pending` is nonzero.

  ```python
  if __name__ == "__main__":
      raise SystemExit(main())
  ```

- [ ] **Step 5: Verify all cleanup entry points**

  Run: `python -m pytest tests/unit/test_application_services.py tests/unit/test_storage_cleanup_command.py tests/integration/test_api_flows.py -k "cleanup or account_deletion" -v && python -m scripts.cleanup_storage`.

  Expected: tests PASS; command reports zero failed/pending in the local test runtime.

- [ ] **Step 6: Commit integration**

  ```bash
  git add src/trainer/api/controllers/auth.py src/trainer/api/runtime.py scripts/cleanup_storage.py tests/integration/test_api_flows.py tests/unit/test_storage_cleanup_command.py
  git commit -m "fix: retry cleanup after account deletion"
  ```
