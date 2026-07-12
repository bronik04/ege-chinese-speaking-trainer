# Review Findings Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Исправить четыре замечания ревью, сделав изображения назначений независимыми от авторских материалов и закрыв два security-пробела.

**Architecture:** Авторские изображения копируются при создании назначения в отдельные assignment-assets, чьи метаданные принадлежат назначению и удаляются вместе с ним. Новый защищённый endpoint выдаёт копию только преподавателю назначения или участнику соответствующей группы; account links используют только настроенный URL либо фиксированный localhost fallback, а hygiene check распознаёт все PEM/OpenSSH private-key markers.

**Tech Stack:** Python 3.12+, FastAPI, sqlite3/psycopg, Alembic, Pillow-backed existing material pipeline, unittest, Playwright, local/S3 storage adapters.

## Global Constraints

- Legacy SQLite migrations 1–7 остаются замороженными; новая схема добавляется только Alembic-ревизией.
- Существующие назначения не требуют backfill: проект является прототипом без существующих учеников.
- Официальные `/assets/` не копируются; копируются только `/api/material-assets/<id>`.
- Ошибки доступа к assignment-assets маскируются одинаковым 404.
- Production account URLs берутся только из `TRAINER_PUBLIC_URL`; fallback равен `http://127.0.0.1:8080`.
- Каждый production change выполняется после наблюдаемого RED соответствующего теста.

---

### Task 1: Repository hygiene private-key detection

**Files:**
- Modify: `scripts/check_repository_hygiene.py:1-34`
- Test: `tests/unit/test_repository_hygiene.py`

**Interfaces:**
- Consumes: `check_repository(root: Path, tracked_paths: list[str]) -> list[str]`
- Produces: `PRIVATE_KEY_MARKER: re.Pattern[bytes]`, обнаруживающий PKCS#8, encrypted, RSA, EC, DSA и OpenSSH markers.

- [ ] **Step 1: Write the failing parameterized test**

```python
def test_rejects_common_private_key_markers(self):
    markers = ("", "ENCRYPTED ", "RSA ", "EC ", "DSA ", "OPENSSH ")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index, prefix in enumerate(markers):
            path = root / f"credential-{index}.pem"
            path.write_text(f"-----BEGIN {prefix}PRIVATE KEY-----\nsecret\n")
        failures = check_repository(root, [f"credential-{index}.pem" for index in range(len(markers))])
        self.assertEqual(len(failures), len(markers))
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.unit.test_repository_hygiene.RepositoryHygieneTest.test_rejects_common_private_key_markers -v`

Expected: FAIL because only generic PKCS#8 and RSA markers are detected.

- [ ] **Step 3: Implement general marker detection**

```python
import re

PRIVATE_KEY_MARKER = re.compile(br"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")

# inside check_repository
if PRIVATE_KEY_MARKER.search(content):
    failures.append(f"Tracked private key content: {relative}")
```

- [ ] **Step 4: Run GREEN and the full unit module**

Run: `.venv/bin/python -m unittest tests.unit.test_repository_hygiene -v`

Expected: all repository hygiene tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/check_repository_hygiene.py tests/unit/test_repository_hygiene.py
git commit -m "Усилить проверку приватных ключей"
```

### Task 2: Trusted account-link base URL

**Files:**
- Modify: `src/trainer/api/dependencies.py:1-115`
- Test: `tests/unit/test_account_links.py`
- Modify: `DEVELOPMENT.md`

**Interfaces:**
- Produces: `account_public_url() -> str`
- Consumes: environment variable `TRAINER_PUBLIC_URL`.

- [ ] **Step 1: Write failing pure-function tests**

```python
class AccountPublicUrlTest(unittest.TestCase):
    def test_uses_configured_public_url_without_trailing_slash(self):
        with patch.dict(os.environ, {"TRAINER_PUBLIC_URL": "https://trainer.example/"}):
            self.assertEqual(account_public_url(), "https://trainer.example")

    def test_uses_fixed_local_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(account_public_url(), "http://127.0.0.1:8080")
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.unit.test_account_links -v`

Expected: import failure because `account_public_url` does not exist.

- [ ] **Step 3: Add the pure helper and remove request-header fallback**

```python
def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"

# send_account_link
public_url = account_public_url()
```

- [ ] **Step 4: Document the production requirement**

Add to `DEVELOPMENT.md` configuration section: production deployments must set `TRAINER_PUBLIC_URL`; the localhost fallback is development-only and never uses request headers.

- [ ] **Step 5: Run GREEN and account integration tests**

Run: `.venv/bin/python -m unittest tests.unit.test_account_links tests.integration.test_accounts tests.integration.test_api_flows -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/trainer/api/dependencies.py tests/unit/test_account_links.py DEVELOPMENT.md
git commit -m "Защитить ссылки восстановления аккаунта"
```

### Task 3: Cross-dialect assignment-assets schema

**Files:**
- Create: `migrations/versions/20260712_04_assignment_material_assets.py`
- Modify: `tests/integration/test_migrations.py:17-163`
- Modify: `src/trainer/api/runtime.py`

**Interfaces:**
- Produces table `assignment_material_assets(id, assignment_id, storage_key, mime_type, size_bytes, created_at)`.
- Produces index `assignment_material_assets_assignment_idx`.
- Produces runtime path `ASSIGNMENT_ASSET_DIR = DATA_DIR / "assignment-assets"`.

- [ ] **Step 1: Extend the failing SQLite migration assertion**

Add `assignment_material_assets` to `EXPECTED_TABLES` and assert its required columns and index after `upgrade_sqlite_database(path)`.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.integration.test_migrations.SqliteMigrationTest.test_clean_database_gets_baseline_and_alembic_head -v`

Expected: FAIL because the table is absent.

- [ ] **Step 3: Create the cross-dialect Alembic revision**

```python
revision = "20260712_04"
down_revision = "20260711_03"

def upgrade() -> None:
    op.create_table(
        "assignment_material_assets",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("assignment_id", sa.BigInteger(), sa.ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("assignment_material_assets_assignment_idx", "assignment_material_assets", ["assignment_id"])

def downgrade() -> None:
    op.drop_index("assignment_material_assets_assignment_idx", table_name="assignment_material_assets")
    op.drop_table("assignment_material_assets")
```

- [ ] **Step 4: Add the runtime storage directory**

Define `ASSIGNMENT_ASSET_DIR`, create it during runtime initialization beside `MATERIAL_ASSET_DIR`, and expose it to the work controller.

- [ ] **Step 5: Run GREEN and migration suite**

Run: `.venv/bin/python -m unittest tests.integration.test_migrations -v`

Expected locally: SQLite tests PASS; PostgreSQL tests SKIP without `TEST_DATABASE_URL`.

- [ ] **Step 6: Commit**

```bash
git add migrations/versions/20260712_04_assignment_material_assets.py tests/integration/test_migrations.py src/trainer/api/runtime.py
git commit -m "Добавить схему изображений назначений"
```

### Task 4: Snapshot image copy service

**Files:**
- Create: `src/trainer/services/assignment_assets.py`
- Test: `tests/integration/test_assignment_assets.py`

**Interfaces:**
- Produces: `copy_assignment_assets(database, assignment_id: int, material: dict, source_storage: AudioStorage, target_storage: AudioStorage) -> dict`.
- Produces rewritten material snapshot with `/api/assignment-assets/<id>` URLs.
- Deletes every created target object before re-raising if any copy or metadata insert fails.

- [ ] **Step 1: Write failing service tests**

Create a temporary SQLite database upgraded to head, insert a user/material/material_asset/assignment fixture, store one WebP object, and assert:

```python
rewritten = copy_assignment_assets(database, assignment_id, material, source_storage, target_storage)
self.assertEqual(rewritten["tasks"]["2"]["images"][0], rewritten["tasks"]["2"]["images"][1])
self.assertRegex(rewritten["tasks"]["2"]["images"][0], r"^/api/assignment-assets/\d+$")
self.assertEqual(database.execute("SELECT COUNT(*) FROM assignment_material_assets").fetchone()[0], 1)
```

Add a failure adapter whose `put` raises and assert no target file or metadata remains.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.integration.test_assignment_assets -v`

Expected: import failure because the service does not exist.

- [ ] **Step 3: Implement minimal recursive replacement and copy**

Implement exact URL matching with `re.fullmatch(r"/api/material-assets/(\d+)", value)`, a per-call `source_id -> snapshot_url` cache, `storage.read`, a temporary file for `target_storage.put`, and metadata insertion. Work on a deep JSON copy so the caller's material object is unchanged.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m unittest tests.integration.test_assignment_assets -v`

Expected: copy, deduplication and cleanup tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/services/assignment_assets.py tests/integration/test_assignment_assets.py
git commit -m "Копировать изображения в снимок назначения"
```

### Task 5: Assignment creation integration

**Files:**
- Modify: `src/trainer/api/controllers/work.py:18-90`
- Modify: `tests/integration/test_api_flows.py`

**Interfaces:**
- Consumes: `copy_assignment_assets(...) -> dict` from Task 4.
- Produces assignments whose stored `material_snapshot_json` contains only assignment-asset URLs for author images.

- [ ] **Step 1: Write failing API regression**

Extend the teacher/student flow to create an author task with an uploaded image, assign it, and assert that the returned student assignment URL begins with `/api/assignment-assets/` rather than `/api/material-assets/`.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_teacher_student_progress_flow -v`

Expected: FAIL because the stored snapshot still references `/api/material-assets/`.

- [ ] **Step 3: Copy and rewrite inside assignment transaction**

After inserting the assignment, call the Task 4 service with `storage_from_env(MATERIAL_ASSET_DIR)` and `storage_from_env(ASSIGNMENT_ASSET_DIR)`, then update `material_snapshot_json` with the rewritten JSON before auditing and committing.

- [ ] **Step 4: Run GREEN and material/API tests**

Run: `.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_materials tests.integration.test_assignment_assets -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trainer/api/controllers/work.py tests/integration/test_api_flows.py
git commit -m "Изолировать изображения назначенных работ"
```

### Task 6: Protected assignment-asset endpoint and lifecycle regressions

**Files:**
- Modify: `src/trainer/api/routes/work.py`
- Modify: `src/trainer/api/controllers/work.py`
- Modify: `tests/integration/test_assignment_assets.py`
- Modify: `tests-e2e/variants-catalog.spec.js`

**Interfaces:**
- Produces controller method `assignment_asset_get(asset_id: int) -> None`.
- Produces route `GET /api/assignment-assets/{asset_id}`.

- [ ] **Step 1: Write failing authorization and lifecycle tests**

Using separate author, teacher, assigned student and outsider clients, assert:

- assigned student and assignment teacher receive 200;
- outsider receives 404;
- after source material update to draft, assigned student still receives 200;
- after author account deletion, assigned student still receives 200.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m unittest tests.integration.test_assignment_assets -v`

Expected: endpoint returns 404/route not found.

- [ ] **Step 3: Implement the protected endpoint**

Query `assignment_material_assets` joined to `assignments`; authorize `assignments.teacher_id == user.id` or existence of `group_members(group_id=assignments.group_id,user_id=user.id)`. Read from `storage_from_env(ASSIGNMENT_ASSET_DIR)` and return stored MIME type with private caching and `nosniff`.

- [ ] **Step 4: Update E2E snapshot assertion**

Change the existing snapshot scenario to assert `/api/assignment-assets/` and retain its post-source-deletion successful GET.

- [ ] **Step 5: Run GREEN**

Run: `.venv/bin/python -m unittest tests.integration.test_assignment_assets -v && make test-e2e`

Expected: authorization/lifecycle tests and all 13 browser tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/trainer/api/routes/work.py src/trainer/api/controllers/work.py tests/integration/test_assignment_assets.py tests-e2e/variants-catalog.spec.js
git commit -m "Защитить изображения назначенных работ"
```

### Task 7: Integration polish and complete verification

**Files:**
- Modify: `tests/unit/test_package_layout.py`
- Modify: `docs/superpowers/plans/2026-07-12-review-findings-fixes.md` only for checked boxes during execution.

**Interfaces:**
- Produces the sole useful task1 delta by checking removal of legacy `data/` and `assets/` directories.

- [ ] **Step 1: Add task1 package-layout assertions**

Change the legacy tuple to:

```python
for legacy in ("index.html", "js", "data", "assets", "styles.css"):
```

- [ ] **Step 2: Run focused package test**

Run: `.venv/bin/python -m unittest tests.unit.test_package_layout -v`

Expected: PASS because those legacy paths are absent.

- [ ] **Step 3: Run the complete local gate**

Run:

```bash
make check
make test-e2e
.venv/bin/python -m scripts.sqlite_restore_smoke
worker_data="$(mktemp -d)"
TRAINER_DATA_DIR="$worker_data" .venv/bin/python -m trainer.workers.transcription --once
rm -rf "$worker_data"
.venv/bin/python -m unittest discover -s legacy/tests -v
.venv/bin/python -m pip check
git diff --check
```

Expected: all available checks PASS. PostgreSQL tests may skip locally only when `TEST_DATABASE_URL` is absent. Docker/PostgreSQL/S3 deployment checks must be run when Docker is available or explicitly reported unavailable.

- [ ] **Step 4: Commit integration polish**

```bash
git add tests/unit/test_package_layout.py docs/superpowers/plans/2026-07-12-review-findings-fixes.md
git commit -m "Завершить проверку исправлений ревью"
```

- [ ] **Step 5: Integrate and publish**

Fetch `origin`, verify `origin/main` has not diverged, merge the verified task7 branch into local `main`, rerun `make check` in the main worktree, then push with `git push origin main`. Do not merge task1 or task6 separately because task7 already subsumes them.
