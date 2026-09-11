# Material Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all material business orchestration, SQLite access, image processing, and storage writes out of the API controller while preserving every existing HTTP contract, audit event, transaction, storage key, and visibility rule.

**Architecture:** Keep the nine public controller functions as transport adapters. Add a transport-independent `MaterialService`, one high-level repository/session port, a SQLite adapter, and an injected Pillow encoder/storage port assembled by `trainer.api.runtime`.

**Tech Stack:** Python 3.12+, FastAPI controller layer, Pydantic request schemas, SQLite, Pillow, `typing.Protocol`, `unittest`, existing local/S3-compatible storage adapters.

**Spec:** `docs/superpowers/specs/2026-08-30-material-service-boundary-design.md`

## Global Constraints

- Preserve all nine public controller names/signatures and every route, payload, status code, error code/message, audit action/detail, visibility rule, and storage key.
- Do not change schemas, migrations, frozen SQLite baseline, frontend, official content, or material asset download cache/range behavior.
- `src/trainer/api/controllers/materials.py` must not import database/storage/Pillow or call `connect()`, `.execute()`, or filesystem writes.
- `src/trainer/services/materials.py` must not import `trainer.api` or database implementation modules.
- `src/trainer/services/material_repository.py` must not import `sqlite3`, Pillow, API, or infrastructure modules and must not expose connections/cursors.
- `src/trainer/infrastructure/database/material_repository.py` and `src/trainer/infrastructure/images.py` must not import `trainer.api`.
- Preserve the upload size range `1..min(MAX_AUDIO_BODY, 5_000_000)` and the existing WebP settings `quality=84, method=6`.
- Publication must retain assets referenced by immutable assignment snapshots and keep physical deletion best effort after commit.
- Upload must delete the new storage object after any post-put metadata failure and must always remove its temporary file.
- Use TDD for every production behavior: write a focused failing test, observe the expected failure, implement minimally, and observe green.
- Final mandatory verification is `make check`; UI is unchanged, so `make test-e2e` is not required.

## File Structure

- Create `src/trainer/services/material_repository.py`: adapter-neutral dataclasses, semantic adapter errors, repository/session/storage protocols.
- Rewrite `src/trainer/services/materials.py`: official-content helpers plus `MaterialService` and semantic `MaterialError`.
- Create `src/trainer/infrastructure/database/material_repository.py`: all material SQL, row mapping, transactions, conflicts, and audit persistence.
- Create `src/trainer/infrastructure/images.py`: Pillow-only material image validation and WebP encoding.
- Modify `src/trainer/api/runtime.py`: non-cached composition factory for `MaterialService`.
- Rewrite `src/trainer/api/controllers/materials.py`: transport conversion, semantic error mapping, result construction only.
- Modify `tests/unit/test_material_service.py`: stateful fake contracts for all service scenarios.
- Create `tests/unit/test_material_images.py`: real in-memory Pillow adapter contracts.
- Create `tests/integration/test_material_repository.py`: migrated SQLite adapter contracts.
- Modify `tests/integration/test_materials.py`: preserve HTTP coverage and move failure seams to runtime/service composition.
- Modify `tests/unit/test_architecture_boundaries.py`: enforce the dependency direction.
- Modify `docs/architecture.md`: document the material vertical boundary.

---

### Task 1: Define the Material Ports and Read Service

**Files:**
- Create: `src/trainer/services/material_repository.py`
- Modify: `src/trainer/services/materials.py`
- Create: `tests/unit/test_material_service.py`

**Interfaces:**
- Consumes: `editor_allowed`, `material_payload` from `trainer.domain.materials`; existing official JSON files under `content/variants`.
- Produces: `MaterialActor`, `MaterialRequestData`, `MaterialRequestMetadata`, `MaterialRecord`, `MaterialAssetRecord`, `MaterialAudit`, `MaterialConflictError`, `MaterialImageError`, `MaterialRepository`, `MaterialRepositorySession`, `MaterialAssetStorage`, `MaterialError`, and `MaterialService`.

- [ ] **Step 1: Write the failing read-service tests**

Create a stateful fake repository and begin with these contracts:

```python
class MaterialServiceTest(unittest.TestCase):
    def test_catalog_filters_official_materials_for_guest_and_adds_published_custom_for_user(self):
        repository = FakeMaterialRepository(
            published=[material_record(slug="author-task", status="published")]
        )
        service = self.service(repository)

        guest = service.catalog(None)
        user = service.catalog(MaterialActor(7, "author@example.test", True))

        self.assertEqual([item["id"] for item in guest["materials"]], ["open-2026"])
        self.assertIn("author-task", [item["id"] for item in user["materials"]])
        self.assertFalse(guest["canCreate"])
        self.assertTrue(user["canCreate"])

    def test_detail_applies_the_existing_visibility_rules(self):
        repository = FakeMaterialRepository(
            materials={
                "draft": material_record(slug="draft", owner_id=7, status="draft"),
                "published": material_record(slug="published", owner_id=8, status="published"),
                "archived": material_record(slug="archived", owner_id=7, status="archived"),
            }
        )
        service = self.service(repository)

        self.assertEqual(service.detail("draft", MaterialActor(7, "author@example.test", True))["id"], "draft")
        self.assertEqual(service.detail("published", MaterialActor(7, "author@example.test", True))["id"], "published")
        for slug, actor in (("draft", None), ("archived", MaterialActor(7, "author@example.test", True))):
            with self.subTest(slug=slug), self.assertRaises(MaterialError) as caught:
                service.detail(slug, actor)
            self.assertEqual(caught.exception.reason, "not_found")

    def test_mine_returns_only_repository_owned_rows_in_repository_order(self):
        repository = FakeMaterialRepository(
            owned=[material_record(slug="newer"), material_record(slug="older")]
        )
        service = self.service(repository)
        payload = service.mine(MaterialActor(7, "author@example.test", True))
        self.assertEqual([item["id"] for item in payload], ["newer", "older"])
```

The fake implements all port methods but raises `AssertionError` for mutation methods until later tasks use them.

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_material_service.py' -v
```

Expected: FAIL because `MaterialActor`, `MaterialService`, and the repository port do not exist.

- [ ] **Step 3: Define exact adapter-neutral types and protocols**

Create `src/trainer/services/material_repository.py` with these public shapes:

```python
@dataclass(frozen=True)
class MaterialActor:
    id: int
    email: str
    email_verified: bool

@dataclass(frozen=True)
class MaterialRequestMetadata:
    client_ip: str
    user_agent: str

@dataclass(frozen=True)
class MaterialRequestData:
    slug: str
    kind: str
    task_number: int | None
    title: str
    year: int
    source: str
    content: dict

@dataclass(frozen=True)
class MaterialRecord:
    id: int
    slug: str
    owner_id: int
    kind: str
    task_number: int | None
    title: str
    year: int
    source: str
    status: str
    content_json: str

@dataclass(frozen=True)
class MaterialAssetRecord:
    id: int
    material_id: int
    storage_key: str
    mime_type: str
    size_bytes: int

@dataclass(frozen=True)
class MaterialAssetAccess:
    storage_key: str
    mime_type: str
    size_bytes: int
    owner_id: int
    material_status: str

@dataclass(frozen=True)
class MaterialAudit:
    action: str
    actor: MaterialActor
    metadata: MaterialRequestMetadata
    details: Mapping[str, object]

class MaterialConflictError(Exception):
    pass

class MaterialImageError(Exception):
    pass

class MaterialAssetStorage(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...

class MaterialRepositorySession(Protocol):
    def create(self, owner_id: int, data: MaterialRequestData, now: int) -> int: ...
    def update(self, current_slug: str, owner_id: int, data: MaterialRequestData, now: int) -> bool: ...
    def owned_material(self, slug: str, owner_id: int) -> MaterialRecord | None: ...
    def owned_asset_ids(self, material_id: int, asset_ids: Collection[int]) -> set[int]: ...
    def assets(self, material_id: int) -> list[MaterialAssetRecord]: ...
    def assignment_snapshots(self) -> list[str]: ...
    def publish(self, material_id: int, content_json: str, now: int) -> None: ...
    def remove_assets(self, asset_ids: Collection[int]) -> None: ...
    def archive(self, material_id: int, now: int) -> None: ...
    def add_asset(self, material_id: int, storage_key: str, mime_type: str, size_bytes: int, created_at: int) -> int: ...
    def audit(self, event: MaterialAudit) -> None: ...

class MaterialRepository(Protocol):
    def published_materials(self) -> list[MaterialRecord]: ...
    def owned_materials(self, owner_id: int) -> list[MaterialRecord]: ...
    def material(self, slug: str) -> MaterialRecord | None: ...
    def owned_material(self, slug: str, owner_id: int) -> MaterialRecord | None: ...
    def asset_access(self, asset_id: int) -> MaterialAssetAccess | None: ...
    def transaction(self) -> ContextManager[MaterialRepositorySession]: ...
```

- [ ] **Step 4: Implement the read-only service surface**

In `src/trainer/services/materials.py`, retain `official_index`, `official_detail`, and `public_official_index`, delete the unused raw-connection `assignment_material`, and add:

```python
class MaterialError(Exception):
    def __init__(self, reason: str, message: str | None = None):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message

class MaterialService:
    def __init__(
        self,
        repository: MaterialRepository,
        *,
        project_root: Path,
        asset_root: Path,
        storage: MaterialAssetStorage,
        image_encoder: Callable[[bytes], bytes],
        editor_emails: str,
        max_image_body: int,
        now: Callable[[], int] = lambda: int(time.time()),
    ): ...

    def catalog(self, actor: MaterialActor | None) -> dict: ...
    def mine(self, actor: MaterialActor) -> list[dict]: ...
    def detail(self, material_id: str, actor: MaterialActor | None) -> dict: ...
```

Use `_material_index_payload(record)` and `_material_payload(record)` helpers to preserve the exact existing keys and values. `catalog()` calls `public_official_index(project_root, actor is not None)`, adds repository published rows only for authenticated actors, and evaluates `editor_allowed()` with `emailVerified` reconstructed from `actor.email_verified`.

- [ ] **Step 5: Run the focused tests to verify GREEN**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_material_service.py' -v
```

Expected: all read-service tests PASS.

- [ ] **Step 6: Commit the boundary and read service**

```bash
git add src/trainer/services/material_repository.py src/trainer/services/materials.py tests/unit/test_material_service.py
git commit -m "refactor: define material service boundary"
```

---

### Task 2: Implement SQLite Reads and Delegate Controller Reads

**Files:**
- Create: `src/trainer/infrastructure/database/material_repository.py`
- Create: `src/trainer/infrastructure/images.py`
- Create: `tests/integration/test_material_repository.py`
- Create: `tests/unit/test_material_images.py`
- Modify: `src/trainer/api/runtime.py`
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: all Task 1 ports; `runtime.connect`; `storage_from_env`; Pillow.
- Produces: `SQLiteMaterialRepository`, `_SQLiteMaterialRepositorySession`, `encode_material_image`, `runtime.material_service()`, and controller delegation for list/mine/detail.

- [ ] **Step 1: Write failing SQLite read-contract tests**

Create a migrated temporary DB and seed official-independent material rows:

```python
class SQLiteMaterialRepositoryTest(unittest.TestCase):
    def test_reads_preserve_public_owner_and_detail_ordering(self):
        repository = SQLiteMaterialRepository(self.connect)
        published = repository.published_materials()
        owned = repository.owned_materials(self.owner_id)
        detail = repository.material("published-newer")

        self.assertEqual([item.slug for item in published], ["published-newer", "published-older"])
        self.assertEqual([item.slug for item in owned], ["draft-newer", "published-older"])
        self.assertEqual(detail.owner_id, self.owner_id)

    def test_asset_read_returns_private_storage_metadata_without_transport_fields(self):
        asset = SQLiteMaterialRepository(self.connect).asset_access(self.asset_id)
        self.assertEqual(
            (asset.owner_id, asset.material_status, asset.storage_key, asset.mime_type, asset.size_bytes),
            (self.owner_id, "draft", "materials/1/source.webp", "image/webp", 14),
        )
```

- [ ] **Step 2: Run the adapter tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest discover -s tests/integration -p 'test_material_repository.py' -v
```

Expected: FAIL because `SQLiteMaterialRepository` does not exist.

- [ ] **Step 3: Implement row mapping and read methods**

Create `src/trainer/infrastructure/database/material_repository.py`. Use `contextlib.closing(self._connect())` for every standalone read and a private mapper:

```python
def _material(row: sqlite3.Row) -> MaterialRecord:
    return MaterialRecord(
        id=row["id"], slug=row["slug"], owner_id=row["owner_id"], kind=row["kind"],
        task_number=row["task_number"], title=row["title"], year=row["year"], source=row["source"],
        status=row["status"], content_json=row["content_json"],
    )
```

Implement exact existing queries:

```sql
SELECT * FROM materials WHERE status='published' ORDER BY year DESC,updated_at DESC
SELECT * FROM materials WHERE owner_id=? AND status!='archived' ORDER BY updated_at DESC
SELECT * FROM materials WHERE slug=?
SELECT * FROM materials WHERE slug=? AND owner_id=?
SELECT material_assets.storage_key,material_assets.mime_type,material_assets.size_bytes,
       materials.owner_id,materials.status
FROM material_assets JOIN materials ON materials.id=material_assets.material_id
WHERE material_assets.id=?
```

Define `transaction()` now with explicit commit/rollback/close, even though mutations arrive in later tasks.

- [ ] **Step 4: Run adapter tests to verify GREEN**

Run the Task 2 adapter command again. Expected: PASS.

- [ ] **Step 5: Write failing Pillow adapter tests and verify RED**

Create `tests/unit/test_material_images.py`:

```python
class MaterialImageEncoderTest(unittest.TestCase):
    def test_returns_bounded_webp(self):
        encoded = encode_material_image(png_bytes((2400, 1800)))
        with Image.open(io.BytesIO(encoded)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertLessEqual(max(image.size), 1600)

    def test_rejects_invalid_and_out_of_bounds_images(self):
        for body in (b"not-image", png_bytes((319, 240)), png_bytes((5000, 5000))):
            with self.subTest(size=len(body)), self.assertRaises(MaterialImageError):
                encode_material_image(body)
```

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_images -v
```

Expected: FAIL because `trainer.infrastructure.images` does not exist.

- [ ] **Step 6: Implement and verify the Pillow adapter**

Create `src/trainer/infrastructure/images.py` with `encode_material_image(body: bytes) -> bytes`. It must load the
image, require at least 320×240 and at most 20,000,000 pixels, thumbnail to 1600×1600, convert non-RGB/RGBA to
RGB, and save WebP with `quality=84, method=6`. Convert only `UnidentifiedImageError`, `OSError`, `ValueError`,
and explicit dimension failures to `MaterialImageError`.

Run the Step 5 command again. Expected: PASS.

- [ ] **Step 7: Add non-cached runtime composition**

Modify `src/trainer/api/runtime.py` to import the adapter, storage factory, and service, then add:

```python
def material_service() -> MaterialService:
    return MaterialService(
        SQLiteMaterialRepository(connect),
        project_root=ROOT,
        asset_root=MATERIAL_ASSET_DIR,
        storage=storage_from_env(MATERIAL_ASSET_DIR),
        image_encoder=encode_material_image,
        editor_emails=os.environ.get("TRAINER_EDITOR_EMAILS", ""),
        max_image_body=min(MAX_AUDIO_BODY, 5_000_000),
    )
```

Do not cache the service.

- [ ] **Step 8: Delegate list/mine/detail from the controller**

Add controller conversion helpers:

```python
def _actor(user: dict | None) -> MaterialActor | None:
    return MaterialActor(user["id"], user["email"], bool(user.get("emailVerified"))) if user else None

def _service_error(error: MaterialError) -> ApiError:
    if error.reason == "not_found":
        return ApiError("material_not_found", "Материал не найден", HTTPStatus.NOT_FOUND)
    raise error
```

Replace only the SQL blocks in `materials_list`, `materials_mine`, and `material_get` with service calls. Preserve `ActionResult` payload nesting exactly.

- [ ] **Step 9: Run focused unit, image, repository, and HTTP tests**

```bash
.venv/bin/python -m unittest discover -s tests/unit -p 'test_material_service.py' -v
.venv/bin/python -m unittest tests.unit.test_material_images -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_material_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_materials.py' -v
```

Expected: all PASS; guest still sees only `open-2026`.

- [ ] **Step 10: Commit the read adapter and delegation**

```bash
git add src/trainer/infrastructure/database/material_repository.py src/trainer/infrastructure/images.py src/trainer/api/runtime.py src/trainer/api/controllers/materials.py tests/unit/test_material_images.py tests/integration/test_material_repository.py tests/integration/test_materials.py
git commit -m "refactor: route material reads through repository"
```

---

### Task 3: Move Metadata Validation, Create, and Update

**Files:**
- Modify: `src/trainer/services/materials.py`
- Modify: `src/trainer/services/material_repository.py`
- Modify: `src/trainer/infrastructure/database/material_repository.py`
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `tests/unit/test_material_service.py`
- Modify: `tests/integration/test_material_repository.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: `MaterialRequestData`, `MaterialAudit`, `MaterialConflictError`, repository transaction/session from Tasks 1–2.
- Produces: `MaterialService.create()`, `MaterialService.update()`, SQLite create/update/audit methods, and controller request conversion/error mapping.

- [ ] **Step 1: Write failing service tests for validation and mutations**

Add at least these tests:

```python
def test_create_normalizes_metadata_and_audits_numeric_material_id(self):
    created = self.service().create(
        MaterialRequestData("  author-task  ", "task", 2, "  Название  ", 2026, "  Источник  ", {"2": {}}),
        self.actor,
        self.metadata,
    )
    self.assertEqual(created, {"id": "author-task", "status": "draft"})
    self.assertEqual(self.repository.created["data"].title, "Название")
    self.assertEqual(self.repository.audits[0].action, "material_created")
    self.assertEqual(self.repository.audits[0].details, {"materialId": 101})

def test_create_rejects_oversized_content_before_opening_transaction(self):
    data = replace(self.valid_data, content={"text": "x" * 150_001})
    with self.assertRaises(MaterialError) as caught:
        self.service().create(data, self.actor, self.metadata)
    self.assertEqual(caught.exception.reason, "invalid_metadata")
    self.assertEqual(self.repository.transaction_count, 0)

def test_update_resets_status_and_reports_missing_owner_material(self):
    self.repository.update_result = False
    with self.assertRaises(MaterialError) as caught:
        self.service().update("missing", self.valid_data, self.actor, self.metadata)
    self.assertEqual(caught.exception.reason, "not_found")

def test_slug_conflict_is_adapter_neutral(self):
    self.repository.conflict_on_create = True
    with self.assertRaises(MaterialError) as caught:
        self.service().create(self.valid_data, self.actor, self.metadata)
    self.assertEqual(caught.exception.reason, "slug_exists")
```

- [ ] **Step 2: Run focused unit tests to verify RED**

Run the Task 1 unit command. Expected: FAIL because mutation methods are missing.

- [ ] **Step 3: Move `_material_metadata` into the service**

Implement `_normalize(data: MaterialRequestData) -> MaterialRequestData` with the exact old rules and messages:

- task number is cleared for `kind == "full"`;
- only task 1/2/3 is accepted for `kind == "task"`;
- JSON content length is at most 150,000 with `ensure_ascii=False`;
- title/source trimming and lengths remain 2–120 and 2–200;
- year remains 2020–2100;
- `validate_slug()` supplies its original message.

Convert `ValueError` into `MaterialError("invalid_metadata", str(error))`.

- [ ] **Step 4: Implement service create/update transactions**

Add exact signatures:

```python
def create(self, data: MaterialRequestData, actor: MaterialActor, metadata: MaterialRequestMetadata) -> dict: ...
def update(self, material_id: str, data: MaterialRequestData, actor: MaterialActor, metadata: MaterialRequestMetadata) -> dict: ...
```

Create writes `material_created` audit in the same transaction. Update intentionally writes no audit, matching current behavior. Translate only `MaterialConflictError` to `MaterialError("slug_exists")`.

- [ ] **Step 5: Add failing SQLite transaction tests**

```python
def test_create_and_audit_commit_together_and_rollback_together(self):
    with self.repository.transaction() as session:
        material_id = session.create(self.owner_id, self.request_data, 100)
        session.audit(MaterialAudit("material_created", self.actor, self.metadata, {"materialId": material_id}))
    self.assertEqual(self.material_row("author-task")["status"], "draft")
    self.assertEqual(self.audit_row()["action"], "material_created")

    with self.assertRaises(RuntimeError):
        with self.repository.transaction() as session:
            session.create(self.owner_id, replace(self.request_data, slug="rolled-back"), 101)
            raise RuntimeError("rollback")
    self.assertIsNone(self.material_row("rolled-back"))

def test_create_and_update_translate_slug_integrity_conflict(self):
    with self.assertRaises(MaterialConflictError):
        with self.repository.transaction() as session:
            session.create(self.owner_id, replace(self.request_data, slug="existing"), 100)
```

Run adapter tests and observe failures for unimplemented session methods.

- [ ] **Step 6: Implement SQLite create/update/audit**

Use the existing INSERT/UPDATE SQL verbatim. Serialize content with `json.dumps(..., ensure_ascii=False)`. Catch `INTEGRITY_ERRORS` only around create/update and raise `MaterialConflictError`. Implement audit via `account_services.audit()` with the exact actor/context/details fields.

- [ ] **Step 7: Delegate controller create/update and extend error mapping**

Convert `MaterialRequest` to `MaterialRequestData` without validation logic in the controller. Map:

```text
invalid_metadata -> invalid_material / original message / 400
slug_exists      -> material_slug_exists / "Материал с таким идентификатором уже существует" / 409
not_found        -> material_not_found / "Материал не найден" / 404
```

Preserve create status 201 and update status 200.

- [ ] **Step 8: Run focused tests and commit**

Run all three Task 2 focused commands. Expected: PASS.

```bash
git add src/trainer/services/materials.py src/trainer/services/material_repository.py src/trainer/infrastructure/database/material_repository.py src/trainer/api/controllers/materials.py tests/unit/test_material_service.py tests/integration/test_material_repository.py tests/integration/test_materials.py
git commit -m "refactor: move material drafts into service"
```

---

### Task 4: Move Publish and Archive State Transitions

**Files:**
- Modify: `src/trainer/services/materials.py`
- Modify: `src/trainer/infrastructure/database/material_repository.py`
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `tests/unit/test_material_service.py`
- Modify: `tests/integration/test_material_repository.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: session methods defined in Task 1 and implemented incrementally here; `build_content()` and `material_asset_ids()` domain rules.
- Produces: `MaterialService.publish()`, `MaterialService.archive()`, atomic SQLite publication, assignment snapshot retention, and best-effort physical asset cleanup.

- [ ] **Step 1: Write failing publication service tests**

```python
def test_publish_retains_current_and_assignment_assets_and_deletes_only_unused_after_commit(self):
    self.repository.materials["author-task"] = material_record(
        id=10, slug="author-task", owner_id=self.actor.id, kind="task", task_number=2,
        content_json=json.dumps({"2": {"images": ["/api/material-assets/1"] * 3}}),
    )
    self.repository.assets_by_material[10] = [asset(1, 10), asset(2, 10), asset(3, 10)]
    self.repository.assignment_snapshot_json = [
        json.dumps({"tasks": {"2": {"images": ["/api/material-assets/2"] * 3}}})
    ]

    result = self.service().publish("author-task", self.actor, self.metadata)

    self.assertEqual(result, {"id": "author-task", "status": "published"})
    self.assertEqual(self.repository.removed_asset_ids, {3})
    self.assertEqual(self.storage.deleted, ["materials/10/3.webp"])
    self.assertEqual(self.repository.audits[-1].action, "material_published")

def test_publish_rejects_foreign_asset_without_mutation(self):
    self.repository.owned_asset_ids_result = set()
    with self.assertRaises(MaterialError) as caught:
        self.service().publish("author-task", self.actor, self.metadata)
    self.assertEqual(caught.exception.reason, "foreign_asset")
    self.assertFalse(self.repository.published)

def test_publish_ignores_malformed_historical_snapshots(self):
    self.repository.assignment_snapshot_json = ["{", "null", json.dumps({"tasks": {"bad": 1}})]
    self.service().publish("author-task", self.actor, self.metadata)

def test_physical_asset_delete_is_best_effort_after_successful_publish(self):
    self.storage.delete_error = OSError("offline")
    self.assertEqual(self.service().publish("author-task", self.actor, self.metadata)["status"], "published")

def test_archive_marks_only_owner_material_without_audit(self):
    self.assertEqual(self.service().archive("author-task", self.actor), {"ok": True})
    self.assertEqual(self.repository.archived_id, 10)
    self.assertEqual(self.repository.audits, [])
```

- [ ] **Step 2: Run unit tests to verify RED**

Run the focused unit command. Expected: missing publish/archive failures.

- [ ] **Step 3: Implement service publication calculation**

Inside one repository transaction:

1. Load `session.owned_material(material_id, actor.id)` or raise `not_found`.
2. Call `build_content(record.kind, record.task_number, json.loads(record.content_json))`; map `ValueError` to `MaterialError("incomplete", message)`.
3. Compute current `asset_ids`; require `session.owned_asset_ids(record.id, asset_ids) == asset_ids`, else `foreign_asset`.
4. Parse each `session.assignment_snapshots()` entry; union `material_asset_ids(snapshot.get("tasks", {}))`; continue on `JSONDecodeError`, `ValueError`, or `TypeError`.
5. Determine unused `MaterialAssetRecord`s from `session.assets(record.id)`.
6. Call `session.publish`, `session.remove_assets`, and `session.audit(MaterialAudit("material_published", ..., {"materialId": record.id}))`.
7. After commit, call `storage.delete()` for each unused key under `suppress(Exception)`.

Implement `archive()` in one transaction: load owner material, raise `not_found` if absent, call `session.archive(record.id, now)`, and return `{"ok": True}`. Do not audit.

- [ ] **Step 4: Add and run failing SQLite publication tests**

Seed a material with three assets and an assignment snapshot. Assert publication writes canonical content/status/timestamps, removes only unused metadata, retains snapshot assets, and records `material_published`. Add a rollback assertion by raising after `session.publish()` and verifying status/content remain unchanged.

Run adapter tests. Expected: FAIL until session methods exist.

- [ ] **Step 5: Implement SQLite publication/archive session methods**

Use the controller's existing SQL verbatim for owner lookup, asset ownership, all assets, assignment snapshots, publish update, asset metadata delete, and archive update. `remove_assets()` must issue one parameterized DELETE per id or a safe placeholder list; no string interpolation of values.

- [ ] **Step 6: Delegate controller publish/delete and map semantic errors**

Add mappings:

```text
incomplete    -> material_incomplete / original message / 400
foreign_asset -> invalid_material_asset / "Одно из изображений не принадлежит материалу" / 400
```

Preserve response payloads and status 200.

- [ ] **Step 7: Run focused tests and commit**

Run unit, adapter, and material HTTP tests. Expected: PASS, including assignment snapshot asset retention.

```bash
git add src/trainer/services/materials.py src/trainer/infrastructure/database/material_repository.py src/trainer/api/controllers/materials.py tests/unit/test_material_service.py tests/integration/test_material_repository.py tests/integration/test_materials.py
git commit -m "refactor: move material publication into service"
```

---

### Task 5: Move Pillow Encoding and Asset Upload Orchestration

**Files:**
- Modify: `src/trainer/services/materials.py`
- Modify: `src/trainer/infrastructure/database/material_repository.py`
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `tests/unit/test_material_service.py`
- Modify: `tests/integration/test_material_repository.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: injected `MaterialAssetStorage`, Task 2 `encode_material_image`, `MaterialImageError`, `MaterialAssetRecord`, `MaterialAssetAccess`, and repository add/read methods.
- Produces: `MaterialService.upload_asset()`, `MaterialService.asset()`, and controller upload/download metadata delegation.

- [ ] **Step 1: Write failing upload-service tests**

Add service contracts:

```python
def test_upload_rejects_mime_and_size_before_encoder_or_storage(self): ...

def test_upload_stores_webp_then_persists_metadata_and_removes_temporary_file(self):
    result = self.service().upload_asset("author-task", b"png", "image/png; charset=binary", self.actor)
    self.assertEqual(result, {"id": 41, "url": "/api/material-assets/41"})
    self.assertEqual(self.storage.puts[0][0], "materials/10/fixed-token.webp")
    self.assertFalse(self.storage.puts[0][1].exists())
    self.assertEqual(self.repository.added_asset["mime_type"], "image/webp")

def test_upload_deletes_new_object_when_metadata_insert_fails(self):
    self.repository.add_asset_error = RuntimeError("metadata failed")
    with self.assertRaises(RuntimeError):
        self.service().upload_asset("author-task", b"png", "image/png", self.actor)
    self.assertEqual(self.storage.deleted, [self.storage.puts[0][0]])

def test_asset_access_is_private_and_hides_archived_or_missing_rows(self):
    self.repository.asset_access_rows[5] = MaterialAssetAccess(
        "materials/10/5.webp", "image/webp", 14, owner_id=7, material_status="draft"
    )
    self.assertEqual(self.service().asset(5, self.actor).storage_key, "materials/10/5.webp")
    with self.assertRaises(MaterialError):
        self.service().asset(5, None)
```

Inject deterministic token callables into the test service if necessary; production defaults remain `secrets.token_urlsafe` and `secrets.token_hex`.

- [ ] **Step 2: Run service tests to verify RED**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_service -v
```

Expected: FAIL for missing upload/asset methods.

- [ ] **Step 3: Implement service upload and asset access**

Add:

```python
def upload_asset(self, material_id: str, body: bytes, content_type: str, actor: MaterialActor) -> dict: ...
def asset(self, asset_id: int, actor: MaterialActor | None) -> MaterialAssetAccess: ...
```

Normalize MIME before validation. Check the configured max body. Resolve owner material before encoding. Map only `MaterialImageError` to `MaterialError("invalid_image")`. Write encoded bytes to `asset_root / f".{secrets.token_hex(8)}.webp"`, call `storage.put(key, temporary, "image/webp")`, then add metadata in a transaction. On every exception after key creation, best-effort delete the key and re-raise; unlink temporary in `finally`.

For asset access, load asset and its material through repository reads. Allow only authenticated users when the material is published or the actor owns it. Otherwise raise `asset_not_found`.

- [ ] **Step 4: Add SQLite asset mutation/access tests and implement methods**

Test `session.add_asset()` commit/rollback and `repository.asset_access()`. Do not translate add-asset integrity failures into slug conflicts; let them propagate so the service compensation path runs.

- [ ] **Step 5: Delegate controller upload/asset metadata access**

Keep the public controller signature including unused `RequestContext`. Map:

```text
unsupported_image -> unsupported_image / "Поддерживаются JPG, PNG и WebP" / 415
image_too_large   -> image_too_large / "Изображение превышает 5 МБ" / 413
invalid_image     -> invalid_image / "Некорректное изображение" / 422
asset_not_found   -> asset_not_found / "Изображение не найдено" / 404
```

Return `FileResult` from the service asset record. Do not change `routes/materials.py` storage read, cache header, or response behavior.

- [ ] **Step 6: Adapt the metadata-failure HTTP seam**

Replace patches of `materials.connect` and `materials.storage_from_env` in `test_asset_upload_deletes_stored_object_when_metadata_insert_fails` with a patch of `runtime.material_service` that constructs the real service using a repository whose transaction fails on `add_asset` and the same `FailingStorage`. Keep assertions unchanged: response remains 500 and the exact stored key is deleted once.

- [ ] **Step 7: Run focused tests and commit**

Run unit, adapter, and material HTTP tests. Expected: PASS.

```bash
git add src/trainer/services/materials.py src/trainer/infrastructure/database/material_repository.py src/trainer/api/controllers/materials.py tests/unit/test_material_service.py tests/integration/test_material_repository.py tests/integration/test_materials.py
git commit -m "refactor: move material asset uploads into service"
```

---

### Task 6: Enforce the Boundary and Clean the Controller

**Files:**
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `src/trainer/api/runtime.py`
- Modify: `tests/unit/test_architecture_boundaries.py`
- Modify: `tests/unit/test_material_service.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: complete service/repository/image boundary from Tasks 1–5.
- Produces: final transport-only material controller and automated dependency-direction guards.

- [ ] **Step 1: Write failing architecture guards**

Extend `ArchitectureBoundaryTest`:

```python
def test_material_controller_has_no_database_storage_or_image_processing(self):
    path = PACKAGE / "api" / "controllers" / "materials.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    direct_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imports = file_imports(path)
    self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
    self.assertNotIn("PIL", imports)
    self.assertNotIn("execute", direct_calls)
    self.assertNotIn("runtime.connect", source)
    self.assertNotIn("write_bytes", direct_calls)

def test_material_boundary_dependency_direction(self):
    service_imports = file_imports(PACKAGE / "services" / "materials.py")
    port_imports = file_imports(PACKAGE / "services" / "material_repository.py")
    adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "material_repository.py")
    image_imports = file_imports(PACKAGE / "infrastructure" / "images.py")
    self.assertFalse(any(module.startswith("trainer.api") for module in service_imports), service_imports)
    self.assertFalse(any(module.startswith("trainer.infrastructure.database") for module in service_imports), service_imports)
    self.assertNotIn("sqlite3", port_imports)
    self.assertFalse(any(module.startswith("trainer.infrastructure") for module in port_imports), port_imports)
    self.assertFalse(any(module.startswith("trainer.api") for module in adapter_imports | image_imports))
```

- [ ] **Step 2: Run architecture tests to verify RED**

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries -v
```

Expected: FAIL until obsolete controller imports/helpers are removed.

- [ ] **Step 3: Reduce the controller to transport/error mapping**

Delete obsolete imports and helpers for `io`, `json`, `os`, `secrets`, `time`, `Path`, Pillow, domain validation, database, storage, audit, and official helpers. The final controller may import only `HTTPStatus`, API error/result/runtime helpers, and service boundary dataclasses/errors.

Every public function must follow this pattern:

```python
def material_publish(material_id: str, user: dict, context: RequestContext) -> ActionResult:
    try:
        material = runtime.material_service().publish(
            material_id,
            _actor(user),
            MaterialRequestMetadata(context.client_ip, context.user_agent),
        )
    except MaterialError as error:
        raise _service_error(error) from error
    return ActionResult({"material": material})
```

Ensure `_actor(user)` is statically understood as non-optional in authenticated functions, either with a dedicated `_required_actor()` helper or an assertion isolated to conversion.

- [ ] **Step 4: Run all focused suites**

```bash
.venv/bin/python -m unittest tests.unit.test_architecture_boundaries -v
.venv/bin/python -m unittest discover -s tests/unit -p 'test_material_service.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_material_repository.py' -v
.venv/bin/python -m unittest discover -s tests/integration -p 'test_materials.py' -v
```

Expected: PASS.

- [ ] **Step 5: Run lint on all touched Python files**

```bash
.venv/bin/ruff check src/trainer/api/controllers/materials.py src/trainer/api/runtime.py src/trainer/services/materials.py src/trainer/services/material_repository.py src/trainer/infrastructure/database/material_repository.py src/trainer/infrastructure/images.py tests/unit/test_material_service.py tests/unit/test_architecture_boundaries.py tests/integration/test_material_repository.py tests/integration/test_materials.py
.venv/bin/ruff format --check src/trainer/api/controllers/materials.py src/trainer/api/runtime.py src/trainer/services/materials.py src/trainer/services/material_repository.py src/trainer/infrastructure/database/material_repository.py src/trainer/infrastructure/images.py tests/unit/test_material_service.py tests/unit/test_architecture_boundaries.py tests/integration/test_material_repository.py tests/integration/test_materials.py
```

Expected: both commands exit 0.

- [ ] **Step 6: Commit the enforced boundary**

```bash
git add src/trainer/api/controllers/materials.py src/trainer/api/runtime.py tests/unit/test_architecture_boundaries.py tests/unit/test_material_service.py tests/integration/test_materials.py
git commit -m "refactor: enforce material service boundary"
```

---

### Task 7: Document, Verify, and Review the Completed Boundary

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/superpowers/specs/2026-08-30-material-service-boundary-design.md`
- Modify: `docs/superpowers/plans/2026-08-30-material-service-boundary.md`
- Review: every file changed since the spec commit.

**Interfaces:**
- Consumes: complete implementation from Tasks 1–6.
- Produces: current architecture documentation, verified full repository state, and review-ready branch.

- [ ] **Step 1: Update architecture documentation**

Add a sibling section after the review-request boundary:

```text
### Вертикальная граница материалов

materials controller
  → MaterialService
    → MaterialRepository port
      → SQLiteMaterialRepository
    → image encoder и storage port
```

State that controller owns API conversion/error mapping; service owns catalog visibility, drafts, publication, asset retention, and upload compensation; SQLite adapter owns SQL/transactions/audit; Pillow adapter owns image decoding/encoding.

- [ ] **Step 2: Record the implementation outcome in spec and plan**

Append a short `## Результат реализации` section to the spec and an `## Execution Record` section to this plan. List final file boundaries, preserved contracts, final controller line count, test counts, skipped tests, and coverage only after Step 5 produces fresh evidence.

- [ ] **Step 3: Run diff hygiene and architecture checks**

```bash
git diff --check main...HEAD
git status --short
rg -n "runtime\.connect|\.execute\(|trainer\.infrastructure|PIL|storage_from_env|write_bytes" src/trainer/api/controllers/materials.py
```

Expected: no diff errors; only intended tracked changes; `rg` returns no matches.

- [ ] **Step 4: Run the full mandatory verification**

```bash
make check
```

Expected: pre-commit, JavaScript unit tests, Python unit tests, Python integration tests, and coverage report all complete with exit code 0. PostgreSQL tests may be skipped only when `TEST_DATABASE_URL` is not configured.

- [ ] **Step 5: Perform code review against the spec**

Use `superpowers:requesting-code-review`. Review `main...HEAD` for:

- public behavior drift;
- transaction/rollback gaps;
- storage orphan paths;
- assignment snapshot asset loss;
- repository abstractions that leak SQLite;
- controller infrastructure access;
- missing error mapping or test coverage.

Fix every Critical/Important finding through a new failing test and rerun the relevant focused suite. If fixes touch executable code, rerun `make check` after the final fix.

- [ ] **Step 6: Fill execution records and commit documentation**

Use the actual fresh verification numbers from Step 4/5, then:

```bash
git add docs/architecture.md docs/superpowers/specs/2026-08-30-material-service-boundary-design.md docs/superpowers/plans/2026-08-30-material-service-boundary.md
git commit -m "docs: record material service boundary"
```

- [ ] **Step 7: Run final post-commit verification and inspect branch**

```bash
make check
git diff --check
git status --short
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: `make check` exits 0; worktree is clean; commits and files match this plan.

- [ ] **Step 8: Finish the development branch**

Use `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Do not merge, push, or remove the worktree without the user's explicit integration choice.

## Execution Record

- Implemented the planned controller → service → repository/storage/image boundary without changing routes,
  schemas, migrations, frontend, official content, payloads, status codes, messages, audit events, or storage keys.
- Final controller size: 180 lines, with no database, infrastructure, Pillow, storage selection, or filesystem
  access. SQLite owns SQL/transactions/audit; the image adapter owns validation/WebP encoding.
- Publication remains atomic, retains assignment-snapshot assets, ignores structurally malformed historical
  snapshots, and performs physical deletion after commit on a best-effort basis.
- Upload retains the 5 MB cap and WebP settings, removes temporary files, and compensates storage objects when
  metadata persistence fails.
- Independent review found two Important issues (malformed snapshot shapes and missing exact error-mapping
  coverage); both were fixed and the focused suites were rerun before the final full check.
- Fresh `make check`: 18 JavaScript tests, 154 Python unit tests, 104 Python integration tests, 2 PostgreSQL tests
  skipped because `TEST_DATABASE_URL` was not configured, and 91% total coverage.
