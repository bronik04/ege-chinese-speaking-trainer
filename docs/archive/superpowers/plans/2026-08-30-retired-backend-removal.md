# Retired Backend Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove executable code, tests, and runtime dependencies that exist only for the retired groups/assignments workflow while preserving migration data and active review requests.

**Architecture:** Keep the published SQLite/Alembic history intact and remove only runtime consumers. Active review snapshots remain in `services/review_assets.py`; their logical runtime constant becomes `REVIEW_ASSET_DIR` but continues to point at the existing `var/assignment-assets` directory for data compatibility.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2, SQLite/Alembic, unittest, coverage, Ruff

**Spec:** `docs/superpowers/specs/2026-08-30-technical-removal-cleanup-design.md`

## Global Constraints

- Do not edit or delete published Alembic revisions or SQLite baseline migrations 1–7.
- Do not drop legacy tables or delete existing assignment/review data.
- Preserve active API URLs, response bodies, statuses, cookies, and the 404 compatibility behavior for retired URLs.
- Existing review-assets must remain readable from the physical `var/assignment-assets` directory and existing S3 keys.
- `Pillow` remains in production requirements because material uploads use it.
- Run `make check` before declaring this package complete.

---

### Task 1: Remove retired API schemas and empty work modules

**Files:**
- Modify: `tests/unit/test_package_layout.py`
- Modify: `src/trainer/api/schemas.py:43-69,91-93`
- Delete: `src/trainer/api/routes/work.py`
- Delete: `src/trainer/api/controllers/work.py`

**Interfaces:**
- Consumes: active schema imports listed by `src/trainer/api/routes/*.py` and `src/trainer/api/controllers/*.py`
- Produces: `trainer.api.schemas` containing only schemas imported by active runtime code

- [x] **Step 1: Add a failing package-layout test**

Add this method to `PackageLayoutTest`:

```python
def test_retired_assignment_runtime_is_removed(self):
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "src/trainer/api/routes/work.py",
        "src/trainer/api/controllers/work.py",
    ):
        self.assertFalse((root / relative).exists(), relative)
    source = (root / "src/trainer/api/schemas.py").read_text(encoding="utf-8")
    for name in (
        "GroupRequest",
        "JoinGroupRequest",
        "AssignmentRequest",
        "AssignmentUpdateRequest",
        "SubmissionRequest",
        "SubmissionCompleteRequest",
        "ReviewRequest",
    ):
        self.assertNotIn(f"class {name}(", source)
```

- [x] **Step 2: Run the test and verify the current code fails it**

Run: `.venv/bin/python -m unittest tests.unit.test_package_layout.PackageLayoutTest.test_retired_assignment_runtime_is_removed -v`

Expected: FAIL because both work modules and the retired schema classes still exist.

- [x] **Step 3: Delete only the retired definitions and modules**

Remove the seven classes named by the test. Retain `ProgressRequest`, `PersonalRecordingUpload`,
`ReviewRequestCreate`, `ReviewScoresRequest`, and `MaterialRequest` unchanged. Delete the two five-line
work modules.

- [x] **Step 4: Verify imports and focused tests**

Run:

```bash
rg -n "GroupRequest|JoinGroupRequest|AssignmentRequest|AssignmentUpdateRequest|SubmissionRequest|SubmissionCompleteRequest|ReviewRequest\\b|api\\.(routes|controllers)\\.work" src tests
.venv/bin/python -m unittest tests.unit.test_package_layout tests.integration.test_asgi -v
```

Expected: `rg` returns no runtime references; package-layout and ASGI tests pass.

- [x] **Step 5: Commit**

```bash
git add tests/unit/test_package_layout.py src/trainer/api/schemas.py src/trainer/api/routes/work.py src/trainer/api/controllers/work.py
git commit -m "refactor: remove retired assignment api surface"
```

---

### Task 2: Remove retired queries, submission writer, and exports

**Files:**
- Modify: `tests/unit/test_package_layout.py`
- Modify: `tests/integration/test_queries.py`
- Create: `tests/integration/test_audio_validation.py`
- Delete: `tests/integration/test_media_exports.py`
- Modify: `src/trainer/infrastructure/database/queries/progress.py`
- Modify: `src/trainer/infrastructure/database/queries/__init__.py`
- Delete: `src/trainer/infrastructure/database/queries/combined.py`
- Delete: `src/trainer/infrastructure/database/queries/assignments.py`
- Delete: `src/trainer/infrastructure/database/queries/groups.py`
- Delete: `src/trainer/infrastructure/database/queries/submissions.py`
- Delete: `src/trainer/infrastructure/database/submissions.py`
- Delete: `src/trainer/infrastructure/exports.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `safe_progress(value: str | None) -> dict` from `queries.progress`
- Produces: focused `queries` package exporting only review-request queries; no PDF/CSV export interface

- [x] **Step 1: Extend the failing removal guard**

Add these paths to `test_retired_assignment_runtime_is_removed`:

```python
retired_paths = (
    "src/trainer/infrastructure/database/queries/combined.py",
    "src/trainer/infrastructure/database/queries/assignments.py",
    "src/trainer/infrastructure/database/queries/groups.py",
    "src/trainer/infrastructure/database/queries/submissions.py",
    "src/trainer/infrastructure/database/submissions.py",
    "src/trainer/infrastructure/exports.py",
)
for relative in retired_paths:
    self.assertFalse((root / relative).exists(), relative)
```

- [x] **Step 2: Run the guard and verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_package_layout.PackageLayoutTest.test_retired_assignment_runtime_is_removed -v`

Expected: FAIL listing the six existing retired modules.

- [x] **Step 3: Move the only live helper out of `combined.py`**

Replace `queries/progress.py` with:

```python
from __future__ import annotations

import json


def safe_progress(value: str | None) -> dict:
    if not value:
        return {"runs": []}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"runs": []}
    return parsed if isinstance(parsed, dict) else {"runs": []}


__all__ = ["safe_progress"]
```

Update `queries/__init__.py` to export only `review_request_detail`, `student_review_requests`, and
`teacher_review_requests` from `queries.review_requests`.

- [x] **Step 4: Remove retired tests without losing audio validation**

Delete `ConcurrentSubmissionTest` and its `threading`/`ThreadPoolExecutor` imports from
`tests/integration/test_queries.py`. Create `tests/integration/test_audio_validation.py` containing the
existing real-WAV duration test:

```python
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from trainer.infrastructure.audio import validate_duration


class AudioValidationTest(unittest.TestCase):
    def test_real_audio_duration_is_probed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            rate = 8000
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, rate, rate, "NONE", "not compressed"))
                audio.writeframes(
                    b"".join(struct.pack("<h", int(500 * math.sin(index / 20))) for index in range(rate))
                )
            self.assertAlmostEqual(validate_duration(path, 1), 1.0, delta=0.1)
```

Delete `test_media_exports.py`; its `ExportTest` is retired behavior.

- [x] **Step 5: Delete modules and remove ReportLab**

Delete the six guarded modules. Remove only `reportlab==4.4.3` from `requirements.txt`; keep `Pillow`,
`boto3`, Alembic, FastAPI, Pydantic, and Uvicorn.

- [x] **Step 6: Run focused verification**

Run:

```bash
rg -n "teacher_dashboard|student_assignments|teacher_assignments|teacher_submissions|submission_history|create_submission_with_retry|submissions_csv|submissions_pdf|trainer\.infrastructure\.exports" src scripts tests
.venv/bin/python -m unittest tests.integration.test_queries tests.integration.test_audio_validation tests.integration.test_migrations -v
.venv/bin/python -m unittest tests.unit.test_package_layout -v
```

Expected: `rg` finds nothing; all focused tests pass, including clean and upgraded SQLite migration tests.

- [x] **Step 7: Commit**

```bash
git add requirements.txt src/trainer/infrastructure/database tests/integration tests/unit/test_package_layout.py
git commit -m "refactor: remove retired assignment persistence"
```

---

### Task 3: Remove the legacy assignment-asset service and retain review coverage

**Files:**
- Modify: `tests/unit/test_package_layout.py`
- Modify: `tests/unit/test_application_services.py`
- Create: `tests/integration/test_review_assets.py`
- Delete: `tests/integration/test_assignment_assets.py`
- Delete: `src/trainer/services/assignment_assets.py`

**Interfaces:**
- Consumes: `copy_review_assets(...)` and `copy_review_assets_from_env(...)` from `trainer.services.review_assets`
- Produces: review-snapshot tests with no dependency on groups, assignments, or `assignment_material_assets`

- [x] **Step 1: Add the service path to the removal guard**

```python
self.assertFalse((root / "src/trainer/services/assignment_assets.py").exists())
```

Run the package-layout test and expect failure while the module exists.

- [x] **Step 2: Remove unit tests for the retired service**

Delete the `AssignmentStorageServiceTest` class and the import of
`copy_assignment_assets_from_env, read_assignment_asset` from `tests/unit/test_application_services.py`.
Keep recording, account-storage, review cleanup, and personal-recording tests unchanged.

- [x] **Step 3: Rebuild the integration fixture around review requests only**

Create `test_review_assets.py` from the active tests currently in `test_assignment_assets.py`:

- keep `FailingStorage` and `FailingSecondPutStorage`;
- keep the four tests beginning with `test_copies_material_assets_into_an_immutable_review_snapshot`;
- keep the complete `ReviewRequestQueryTest` class;
- delete `copy_assignment_assets` imports and the two tests that assert `/api/assignment-assets/...`;
- simplify `create_fixture()` to create a user, material, and `material_assets` row, returning only the material.

The simplified fixture must have this shape:

```python
def create_material_fixture(self, database) -> dict:
    owner_id = database.execute(
        "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
        ("author@example.test", "hash", "Author", "student", 1),
    ).lastrowid
    material_id = database.execute(
        """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,
                                  created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("author-task", owner_id, "task", 2, "Task", 2027, "Author", "published", "{}", 1, 1),
    ).lastrowid
    asset_id = database.execute(
        """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
           VALUES (?,?,?,?,?)""",
        (material_id, "materials/1/source.webp", "image/webp", 14, 1),
    ).lastrowid
    return {"id": "author-task", "tasks": {"2": {"images": [f"/api/material-assets/{asset_id}"] * 3}}}
```

- [x] **Step 4: Delete the legacy module and old mixed test file**

Delete `services/assignment_assets.py` and `test_assignment_assets.py` after the active tests exist in
`test_review_assets.py`.

- [x] **Step 5: Run focused tests**

Run:

```bash
rg -n "copy_assignment_assets|read_assignment_asset|delete_assignment_assets|trainer\.services\.assignment_assets" src tests scripts
.venv/bin/python -m unittest tests.integration.test_review_assets tests.unit.test_application_services -v
```

Expected: no search matches and all retained review/storage tests pass.

- [x] **Step 6: Commit**

```bash
git add src/trainer/services tests/unit/test_application_services.py tests/integration/test_review_assets.py tests/integration/test_assignment_assets.py tests/unit/test_package_layout.py
git commit -m "refactor: remove retired assignment asset service"
```

---

### Task 4: Rename the active private review-asset root without moving data

**Files:**
- Modify: `src/trainer/api/runtime.py`
- Modify: `src/trainer/services/review_assets.py`
- Modify: `src/trainer/api/routes/recordings.py`
- Modify: `src/trainer/api/controllers/review_requests.py`
- Modify: `src/trainer/api/controllers/auth.py`
- Modify: `scripts/cleanup_storage.py`
- Modify: `tests/unit/test_application_services.py`
- Modify: `tests/unit/test_storage_cleanup_command.py`
- Modify: `tests/integration/test_accounts.py`
- Modify: `tests/integration/test_api_flows.py`
- Modify: `tests/integration/test_review_assets.py`

**Interfaces:**
- Consumes: existing physical directory `DATA_DIR / "assignment-assets"`
- Produces: `runtime.REVIEW_ASSET_DIR: Path`, used for active review snapshots and legacy-key cleanup

- [x] **Step 1: Write the failing compatibility assertion**

Add to `PackageLayoutTest`:

```python
def test_review_asset_root_has_current_logical_name(self):
    from trainer.api import runtime

    self.assertEqual(runtime.REVIEW_ASSET_DIR, runtime.DATA_DIR / "assignment-assets")
    self.assertFalse(hasattr(runtime, "ASSIGNMENT_ASSET_DIR"))
```

Run it and expect `AttributeError` because `REVIEW_ASSET_DIR` does not exist yet.

- [x] **Step 2: Rename the runtime constant and active references**

In `runtime.py` define exactly:

```python
# Physical name is retained for compatibility with existing local review snapshots.
REVIEW_ASSET_DIR = DATA_DIR / "assignment-assets"
```

Replace active `runtime.ASSIGNMENT_ASSET_DIR` references with `runtime.REVIEW_ASSET_DIR` in the listed
controllers, route, service, cleanup command, and tests. Do not rename the database column
`assignment_keys_json` or `process_cleanup_jobs(..., assignment_root=...)` parameter in this package.

- [x] **Step 3: Verify existing files remain readable**

The existing API flow test that writes a review asset and reads `/api/review-assets/{id}` must continue to
use a temporary directory named `assignment-assets`. Run:

```bash
.venv/bin/python -m unittest \
  tests.integration.test_api_flows.ApiFlowTest.test_student_queues_single_task_for_owner_review \
  tests.integration.test_api_flows.ApiFlowTest.test_account_deletion_removes_private_review_recording_and_snapshot \
  tests.integration.test_review_assets -v
```

Expected: all tests pass without moving or copying a directory.

- [x] **Step 4: Verify no runtime constant references remain**

Run: `rg -n "ASSIGNMENT_ASSET_DIR" src scripts tests`

Expected: no matches. References to `assignment_root`, `assignment_keys_json`, legacy tables, migrations,
and the physical string `assignment-assets` are allowed.

- [x] **Step 5: Commit**

```bash
git add src scripts tests
git commit -m "refactor: rename review asset runtime root"
```

---

### Task 5: Complete backend verification

**Files:**
- Modify only if verification exposes a regression

**Interfaces:**
- Consumes: Tasks 1–4
- Produces: a passing backend cleanup package ready for documentation cleanup

- [x] **Step 1: Run stale-symbol and dependency searches**

```bash
rg -n "GroupRequest|JoinGroupRequest|AssignmentRequest|SubmissionRequest|copy_assignment_assets|submissions_pdf|submissions_csv|ASSIGNMENT_ASSET_DIR" src scripts tests
rg -n "reportlab" requirements.txt src tests
```

Expected: no matches.

- [x] **Step 2: Run the mandatory check**

Run: `make check`

Expected: all pre-commit hooks, JS tests, Python unit/integration tests, and coverage threshold pass.

- [x] **Step 3: Review the diff for migration safety**

Run:

```bash
git diff --check HEAD~4..HEAD
git diff --name-only HEAD~4..HEAD -- migrations src/trainer/infrastructure/database/sqlite_migrations.py
git status --short
```

Expected: no diff errors; no migration or SQLite-baseline files changed; only the pre-existing
`.superpowers/brainstorm/` may remain untracked.
