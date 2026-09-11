# Strict Material Content Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new material create/update request carry a strict, canonical draft-content structure while preserving incomplete drafts, publication validation, and read-only compatibility with legacy rows.

**Architecture:** Add one transport-independent draft normalizer to `trainer.domain.materials`, expose the same shape through nested strict Pydantic models, and revalidate it at the `MaterialService` boundary before persistence. Keep publication semantics in `build_content()`, and make the browser editor explicitly project loaded material data onto editable draft fields so enriched or legacy fields are never sent back.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, dataclasses, SQLite, vanilla JavaScript ES modules, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-08-material-content-contract-design.md`

## Global Constraints

- New create/update requests are strict; existing `materials.content_json` rows are not migrated, rewritten, or newly validated on read.
- A structurally valid draft may contain empty strings; minimum semantic lengths and owned asset URLs remain publication-time rules.
- Draft task 1 has exactly `situation`, `banner`, five `questions`, `image`, and `imageAlt`.
- Draft task 2 has exactly three `images`.
- Draft task 3 has exactly `title`, two `images`, and two `imageLabels`.
- `kind=full` has exactly content keys `1`, `2`, `3` and a null or omitted `taskNumber`; `kind=task` has exactly the key matching `taskNumber`.
- Nested values use strict JSON types, reject unknown fields, preserve strings without trimming or coercion, and enforce the maxima from the spec.
- `build_content()`, `EXAM_SPEC`, public routes, response envelopes, permissions, SQLite schema, and official variant validation remain unchanged.
- The obsolete 150 KB inner-content guard is removed; the existing global HTTP body limit remains unchanged.
- Production code, tests, and documentation are edited with `apply_patch`; user-owned `.superpowers/brainstorm/` remains untouched.
- Final verification is `make check` followed by `make test-e2e` from a clean committed branch.

## File Structure

- Create `tests/unit/test_material_content_contract.py`: isolated domain tests for strict draft normalization and input immutability.
- Create `frontend/js/materials/material-content.js`: pure projection of loaded task data onto the editable draft contract.
- Create `tests-js/unit/material-content.test.js`: browser-independent tests for that projection.
- Modify `src/trainer/domain/materials.py`: define the HTTP-neutral validation error and canonical draft normalizer; leave publication builders in place.
- Modify `src/trainer/services/materials.py`: normalize draft content before transactions and remove the arbitrary size guard.
- Modify `src/trainer/api/schemas.py`: describe the three strict nested task models and validate root relationships.
- Modify `src/trainer/api/controllers/materials.py`: dump the typed content model to a plain alias-keyed dictionary.
- Modify `frontend/js/materials/material-editor.js`: use the pure projection instead of spreading loaded published/legacy fields.
- Modify `tests/unit/test_material_service.py`: cover canonical persistence, rejection before transaction, and incomplete-draft behavior.
- Modify `tests/unit/test_material_controller.py`: use the typed request shape when exercising the controller.
- Modify `tests/integration/test_materials.py`: cover API 422 boundaries, SQLite canonical storage, publication behavior, and legacy read compatibility.
- Modify `tests-e2e/variants-catalog.spec.js`: save and republish an already published material through the editor.
- Modify `docs/architecture.md`: record the completed strict material-content boundary and remove the remaining-future-work statement.

---

### Task 1: Define the domain draft-content contract

**Files:**
- Create: `tests/unit/test_material_content_contract.py`
- Modify: `src/trainer/domain/materials.py`

**Interfaces:**
- Consumes: the existing material kinds `"full"` and `"task"`; editable field limits already used by `build_task()`.
- Produces: `MaterialContentValidationError(ValueError)` and `normalize_material_draft_content(kind: str, task_number: int | None, raw: object) -> dict[str, dict]`.

- [ ] **Step 1: Add valid-contract and immutability tests**

Create `tests/unit/test_material_content_contract.py` with a reusable full draft and assertions for canonical task/field order:

```python
from __future__ import annotations

import copy
import unittest

from trainer.domain.materials import (
    MaterialContentValidationError,
    normalize_material_draft_content,
)


def full_draft() -> dict:
    return {
        "3": {"imageLabels": ["", ""], "images": ["", ""], "title": ""},
        "1": {
            "questions": ["", "", "", "", ""],
            "imageAlt": "",
            "banner": "",
            "image": "",
            "situation": "",
        },
        "2": {"images": ["", "", ""]},
    }


class MaterialContentContractTest(unittest.TestCase):
    def test_full_draft_is_canonical_and_input_is_unchanged(self):
        raw = full_draft()
        original = copy.deepcopy(raw)

        normalized = normalize_material_draft_content("full", None, raw)

        self.assertEqual(list(normalized), ["1", "2", "3"])
        self.assertEqual(
            list(normalized["1"]),
            ["situation", "banner", "questions", "image", "imageAlt"],
        )
        self.assertEqual(list(normalized["3"]), ["title", "images", "imageLabels"])
        self.assertEqual(raw, original)
        self.assertIsNot(normalized, raw)

    def test_single_task_accepts_only_the_selected_key(self):
        normalized = normalize_material_draft_content(
            "task", 2, {"2": {"images": ["one", "two", "three"]}}
        )

        self.assertEqual(normalized, {"2": {"images": ["one", "two", "three"]}})
```

- [ ] **Step 2: Add a table of structural failures**

In the same test class, enumerate exact invalid relationships, fields, types, cardinalities, and maxima:

```python
    def test_invalid_structures_are_rejected(self):
        cases = (
            ("not-object", "full", None, []),
            ("full-missing-task", "full", None, {"1": full_draft()["1"], "2": full_draft()["2"]}),
            ("full-has-task-number", "full", 2, full_draft()),
            ("single-wrong-key", "task", 2, {"3": full_draft()["3"]}),
            ("single-missing-number", "task", None, {"2": full_draft()["2"]}),
            ("unknown-task", "task", 2, {"2": full_draft()["2"], "4": {}}),
            ("extra-field", "task", 2, {"2": {"images": ["", "", ""], "lead": "fixed"}}),
            ("wrong-string-type", "task", 3, {"3": {"title": 7, "images": ["", ""], "imageLabels": ["", ""]}}),
            ("wrong-list-type", "task", 2, {"2": {"images": ""}}),
            ("wrong-list-length", "task", 2, {"2": {"images": ["", ""]}}),
            ("wrong-item-type", "task", 2, {"2": {"images": ["", 2, ""]}}),
            ("too-long", "task", 3, {"3": {"title": "x" * 151, "images": ["", ""], "imageLabels": ["", ""]}}),
        )
        for label, kind, task_number, raw in cases:
            with self.subTest(label=label), self.assertRaises(MaterialContentValidationError):
                normalize_material_draft_content(kind, task_number, raw)
```

- [ ] **Step 3: Run the new domain test and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_content_contract -v
```

Expected: ERROR importing `MaterialContentValidationError` or `normalize_material_draft_content` from `trainer.domain.materials`.

- [ ] **Step 4: Implement strict canonical normalization**

In `src/trainer/domain/materials.py`, add a focused structural error and helpers before the existing publication builders:

```python
class MaterialContentValidationError(ValueError):
    pass


_DRAFT_FIELDS = {
    1: ("situation", "banner", "questions", "image", "imageAlt"),
    2: ("images",),
    3: ("title", "images", "imageLabels"),
}


def _draft_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str or len(value) > maximum:
        raise MaterialContentValidationError(f"Некорректное поле «{label}»")
    return value


def _draft_list(value: object, label: str, length: int, maximum: int) -> list[str]:
    if type(value) is not list or len(value) != length:
        raise MaterialContentValidationError(f"Некорректное поле «{label}»")
    return [_draft_text(item, label, maximum) for item in value]


def _draft_task(number: int, raw: object) -> dict:
    if type(raw) is not dict or set(raw) != set(_DRAFT_FIELDS[number]):
        raise MaterialContentValidationError(f"Некорректное содержание задания {number}")
    if number == 1:
        return {
            "situation": _draft_text(raw["situation"], "Ситуация", 1500),
            "banner": _draft_text(raw["banner"], "Объявление", 300),
            "questions": _draft_list(raw["questions"], "Вопросы", 5, 300),
            "image": _draft_text(raw["image"], "Изображение", 500),
            "imageAlt": _draft_text(raw["imageAlt"], "Описание изображения", 300),
        }
    if number == 2:
        return {"images": _draft_list(raw["images"], "Изображения", 3, 500)}
    return {
        "title": _draft_text(raw["title"], "Название проекта", 150),
        "images": _draft_list(raw["images"], "Изображения", 2, 500),
        "imageLabels": _draft_list(raw["imageLabels"], "Подписи", 2, 100),
    }


def normalize_material_draft_content(
    kind: str, task_number: int | None, raw: object
) -> dict[str, dict]:
    if type(raw) is not dict:
        raise MaterialContentValidationError("Некорректное содержание материала")
    if kind == "full":
        if task_number is not None or set(raw) != {"1", "2", "3"}:
            raise MaterialContentValidationError("Содержание не соответствует типу материала")
        numbers = (1, 2, 3)
    elif kind == "task" and task_number in {1, 2, 3} and set(raw) == {str(task_number)}:
        numbers = (task_number,)
    else:
        raise MaterialContentValidationError("Содержание не соответствует выбранному заданию")
    return {str(number): _draft_task(number, raw[str(number)]) for number in numbers}
```

Keep `build_task()`, `build_content()`, and their minimum-length publication rules unchanged.

- [ ] **Step 5: Run the domain tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_content_contract -v
.venv/bin/python -m unittest tests.integration.test_materials.MaterialApiTest.test_full_variant_uses_fixed_exam_spec -v
```

Expected: all material-content contract tests pass, and the existing publication builder test remains green.

- [ ] **Step 6: Commit the domain contract**

```bash
git add src/trainer/domain/materials.py tests/unit/test_material_content_contract.py
git commit -m "feat: define strict material draft contract"
```

---

### Task 2: Enforce canonical content at the service boundary

**Files:**
- Modify: `tests/unit/test_material_service.py`
- Modify: `src/trainer/services/materials.py`

**Interfaces:**
- Consumes: `normalize_material_draft_content(kind, task_number, raw) -> dict[str, dict]` and `MaterialContentValidationError` from Task 1.
- Produces: `MaterialService.create()` and `update()` that persist only normalized content and reject invalid direct calls before `repository.transaction()`.

- [ ] **Step 1: Replace the loose service fixture with a valid empty draft**

Change `MaterialServiceTest.setUp()` so `self.valid_data.content` is structurally complete for task 2:

```python
self.valid_data = MaterialRequestData(
    "author-task",
    "task",
    2,
    "Авторский материал",
    2026,
    "Автор",
    {"2": {"images": ["", "", ""]}},
)
```

- [ ] **Step 2: Replace the obsolete size test with boundary tests**

Delete `test_create_rejects_oversized_content_before_opening_transaction`. Add this
fixture beside `material_record()` so the service test does not import another
test module:

```python
def full_draft() -> dict:
    return {
        "1": {
            "situation": "",
            "banner": "",
            "questions": ["", "", "", "", ""],
            "image": "",
            "imageAlt": "",
        },
        "2": {"images": ["", "", ""]},
        "3": {"title": "", "images": ["", ""], "imageLabels": ["", ""]},
    }
```

Then add:

```python
def test_create_persists_a_canonical_copy_without_mutating_input(self):
    content = {"2": {"images": ["one", "two", "three"]}}
    data = replace(self.valid_data, content=content)

    self.service().create(data, self.actor, self.metadata)

    stored = self.repository.created["data"].content
    self.assertEqual(stored, {"2": {"images": ["one", "two", "three"]}})
    self.assertIsNot(stored, content)
    self.assertIsNot(stored["2"]["images"], content["2"]["images"])
    self.assertEqual(content, {"2": {"images": ["one", "two", "three"]}})


def test_create_rejects_invalid_content_before_opening_transaction(self):
    data = replace(self.valid_data, content={"2": {"images": ["", ""]}})

    with self.assertRaises(MaterialError) as caught:
        self.service().create(data, self.actor, self.metadata)

    self.assertEqual(caught.exception.reason, "invalid_metadata")
    self.assertEqual(self.repository.transaction_count, 0)


def test_create_rejects_full_material_with_task_number_before_transaction(self):
    data = replace(self.valid_data, kind="full", task_number=2, content=full_draft())

    with self.assertRaises(MaterialError) as caught:
        self.service().create(data, self.actor, self.metadata)

    self.assertEqual(caught.exception.reason, "invalid_metadata")
    self.assertEqual(self.repository.transaction_count, 0)
```

- [ ] **Step 3: Run service tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_service.MaterialServiceTest.test_create_persists_a_canonical_copy_without_mutating_input tests.unit.test_material_service.MaterialServiceTest.test_create_rejects_invalid_content_before_opening_transaction tests.unit.test_material_service.MaterialServiceTest.test_create_rejects_full_material_with_task_number_before_transaction -v
```

Expected: at least the invalid-list and full-with-task-number assertions fail because `_normalize()` still accepts or silently rewrites them; the copy assertion also fails because the input dictionary is passed through unchanged.

- [ ] **Step 4: Normalize content before creating a transaction**

Import the new domain boundary in `src/trainer/services/materials.py`:

```python
from trainer.domain.materials import (
    MaterialContentValidationError,
    build_content,
    editor_allowed,
    material_asset_ids,
    material_payload,
    normalize_material_draft_content,
    validate_slug,
)
```

In `_normalize()`, preserve numeric metadata conversion, but stop silently changing a full material's task number. Replace the loose dictionary/size branch with:

```python
try:
    content = normalize_material_draft_content(kind, task_number, data.content)
except MaterialContentValidationError as error:
    raise ValueError(str(error)) from error
```

Let the domain normalizer own invalid kind/task-number/content relationships. Keep title, source, year, and slug normalization unchanged, and return `content=content` in the new `MaterialRequestData`.

- [ ] **Step 5: Run all material service tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_service -v
```

Expected: all tests pass, including unchanged publication, assets, cleanup, and audit behavior.

- [ ] **Step 6: Commit service enforcement**

```bash
git add src/trainer/services/materials.py tests/unit/test_material_service.py
git commit -m "feat: enforce canonical material drafts in service"
```

---

### Task 3: Expose the strict request through FastAPI

**Files:**
- Modify: `src/trainer/api/schemas.py`
- Modify: `src/trainer/api/controllers/materials.py`
- Modify: `tests/unit/test_material_controller.py`
- Modify: `tests/integration/test_materials.py`

**Interfaces:**
- Consumes: the Task 1 domain normalizer and the existing `MaterialRequestData` service DTO.
- Produces: `MaterialDraftTask1`, `MaterialDraftTask2`, `MaterialDraftTask3`, `MaterialDraftContent`, and a validated `MaterialRequest` whose content dumps with aliases `"1"`, `"2"`, `"3"`.

- [ ] **Step 1: Add an integration helper for authenticated material editing**

In `tests/integration/test_materials.py`, add this module-level fixture:

```python
def full_draft() -> dict:
    return {
        "1": {
            "situation": "",
            "banner": "",
            "questions": ["", "", "", "", ""],
            "image": "",
            "imageAlt": "",
        },
        "2": {"images": ["", "", ""]},
        "3": {"title": "", "images": ["", ""], "imageLabels": ["", ""]},
    }
```

Also add a helper that registers and verifies the requested author once per test
flow:

```python
def register_verified_editor(self, email="author@example.test"):
    self.register(email)
    self.verify_email(email)
```

Call this helper with the fixed unique emails shown in Steps 2 and 3. Those tests
also use the unique slugs shown below, so they do not depend on execution order.

- [ ] **Step 2: Add API tests for nested structure and root relationships**

Add one table-driven integration test after the existing create/publish flow:

```python
def test_material_request_rejects_invalid_content_shapes(self):
    email = "strict-content@example.test"
    self.register_verified_editor(email)
    base = {
        "slug": "strict-content",
        "kind": "task",
        "taskNumber": 2,
        "title": "Строгий черновик",
        "year": 2026,
        "source": "Автор",
        "content": {"2": {"images": ["", "", ""]}},
    }
    invalid_contents = (
        {"2": {"images": ["", ""]}},
        {"2": {"images": ["", 2, ""]}},
        {"2": {"images": ["", "", ""], "lead": "лишнее"}},
        {"3": {"title": "", "images": ["", ""], "imageLabels": ["", ""]}},
    )
    for index, content in enumerate(invalid_contents):
        payload = {**base, "slug": f"strict-content-{index}", "content": content}
        response = self.client.post("/api/materials", headers=self.origin, json=payload)
        with self.subTest(index=index):
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()["code"], "request_validation_failed")

    full_with_number = {
        **base,
        "slug": "strict-full-number",
        "kind": "full",
        "taskNumber": 2,
        "content": full_draft(),
    }
    response = self.client.post("/api/materials", headers=self.origin, json=full_with_number)
    self.assertEqual(response.status_code, 422, response.text)
```

- [ ] **Step 3: Add canonical SQLite and legacy-read assertions**

Add a separate integration test:

```python
def test_material_draft_is_canonical_and_legacy_content_remains_readable(self):
    email = "canonical-content@example.test"
    self.register_verified_editor(email)
    draft = {
        "slug": "canonical-content",
        "kind": "task",
        "taskNumber": 2,
        "title": "Канонический черновик",
        "year": 2026,
        "source": "Автор",
        "content": {"2": {"images": ["", "", ""]}},
    }
    response = self.client.post("/api/materials", headers=self.origin, json=draft)
    self.assertEqual(response.status_code, 201, response.text)

    with runtime.connect() as database:
        stored = database.execute(
            "SELECT content_json FROM materials WHERE slug=?", (draft["slug"],)
        ).fetchone()["content_json"]
        self.assertEqual(json.loads(stored), draft["content"])
        owner_id = database.execute(
            "SELECT id FROM users WHERE email=?", (email,)
        ).fetchone()["id"]
        legacy = json.dumps({"legacy": True}, separators=(",", ":"))
        database.execute(
            """INSERT INTO materials
               (slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
            ("legacy-content", owner_id, "task", 2, "Legacy", 2026, "Legacy", legacy, 1, 1),
        )

    incomplete = self.client.post(
        "/api/materials/canonical-content/publish", headers=self.origin, json={}
    )
    self.assertEqual(incomplete.status_code, 400, incomplete.text)
    self.assertEqual(incomplete.json()["code"], "material_incomplete")

    detail = self.client.get("/api/materials/legacy-content")
    self.assertEqual(detail.status_code, 200, detail.text)
    self.assertEqual(detail.json()["material"]["tasks"], {"legacy": True})
    with runtime.connect() as database:
        unchanged = database.execute(
            "SELECT content_json FROM materials WHERE slug='legacy-content'"
        ).fetchone()["content_json"]
    self.assertEqual(unchanged, legacy)
```

Use the repository's actual row access style (`sqlite3.Row`) already configured by `runtime.connect()`.

- [ ] **Step 4: Run the new API tests and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_materials.MaterialApiTest.test_material_request_rejects_invalid_content_shapes tests.integration.test_materials.MaterialApiTest.test_material_draft_is_canonical_and_legacy_content_remains_readable -v
```

Expected: the invalid nested shapes return success or service-level 400 instead of 422, proving that the transport contract is still loose. The legacy-read portion must remain conceptually unchanged when the test later becomes green.

- [ ] **Step 5: Add strict nested Pydantic models**

In `src/trainer/api/schemas.py`, import `MaterialContentValidationError` and `normalize_material_draft_content`. Add a strict base and the nested models before `MaterialRequest`:

```python
class StrictMaterialSchema(ApiSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


DraftImage = Annotated[StrictStr, Field(max_length=500)]
DraftQuestion = Annotated[StrictStr, Field(max_length=300)]
DraftLabel = Annotated[StrictStr, Field(max_length=100)]


class MaterialDraftTask1(StrictMaterialSchema):
    situation: StrictStr = Field(max_length=1500)
    banner: StrictStr = Field(max_length=300)
    questions: list[DraftQuestion] = Field(min_length=5, max_length=5)
    image: DraftImage
    imageAlt: StrictStr = Field(max_length=300)


class MaterialDraftTask2(StrictMaterialSchema):
    images: list[DraftImage] = Field(min_length=3, max_length=3)


class MaterialDraftTask3(StrictMaterialSchema):
    title: StrictStr = Field(max_length=150)
    images: list[DraftImage] = Field(min_length=2, max_length=2)
    imageLabels: list[DraftLabel] = Field(min_length=2, max_length=2)


class MaterialDraftContent(StrictMaterialSchema):
    task1: MaterialDraftTask1 | None = Field(default=None, alias="1")
    task2: MaterialDraftTask2 | None = Field(default=None, alias="2")
    task3: MaterialDraftTask3 | None = Field(default=None, alias="3")
```

Change `MaterialRequest.content` to `MaterialDraftContent` and add:

```python
@model_validator(mode="after")
def valid_content_contract(self):
    content = self.content.model_dump(mode="json", by_alias=True, exclude_none=True)
    try:
        normalize_material_draft_content(self.kind, self.taskNumber, content)
    except MaterialContentValidationError as error:
        raise ValueError(str(error)) from error
    return self
```

Do not add minimum lengths to draft strings. Keep existing root metadata fields and defaults unchanged.
After changing `MaterialRequest.content`, remove `Any` from the `typing` import
because this was its last use in the module.

- [ ] **Step 6: Dump the typed content in the controller**

In `src/trainer/api/controllers/materials.py`, change only the `content` assignment in `_request_data()`:

```python
content=payload.content.model_dump(mode="json", by_alias=True, exclude_none=True),
```

In `tests/unit/test_material_controller.py`, replace the loose `SimpleNamespace`
request with the real `MaterialRequest` schema:

```python
from trainer.api.schemas import MaterialRequest

self.payload = MaterialRequest.model_validate({
    "slug": "author-task",
    "kind": "task",
    "taskNumber": 2,
    "title": "Авторский материал",
    "year": 2026,
    "source": "Автор",
    "content": {"2": {"images": ["", "", ""]}},
})
```

Remove the now-unused `SimpleNamespace` import.

- [ ] **Step 7: Run controller and material API tests**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_controller -v
.venv/bin/python -m unittest tests.integration.test_materials -v
```

Expected: all tests pass. Invalid shapes and root relationships return 422; empty valid drafts still return 201/200; legacy detail reads without a write.

- [ ] **Step 8: Commit the HTTP contract**

```bash
git add src/trainer/api/schemas.py src/trainer/api/controllers/materials.py tests/unit/test_material_controller.py tests/integration/test_materials.py
git commit -m "feat: enforce strict material content api"
```

---

### Task 4: Project loaded material data onto editable browser fields

**Files:**
- Create: `frontend/js/materials/material-content.js`
- Create: `tests-js/unit/material-content.test.js`
- Modify: `frontend/js/materials/material-editor.js`

**Interfaces:**
- Consumes: a material `tasks` object returned by detail, including enriched published or arbitrary legacy fields.
- Produces: `editableMaterialContent(kind: "full" | "task", taskNumber: number | null, source: object) -> object`, a pure, non-mutating projection with exact draft fields and list lengths.

- [ ] **Step 1: Write failing JavaScript projection tests**

Create `tests-js/unit/material-content.test.js`:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import { editableMaterialContent } from "../../frontend/js/materials/material-content.js";

test("published task content is projected onto editable draft fields", () => {
  const source = {
    "2": {
      prepSeconds: 120,
      answerSeconds: 120,
      title: "Fixed title",
      lead: "Fixed lead",
      prompts: ["fixed"],
      starter: "fixed",
      images: ["one", "two", "three"],
      unknown: true,
    },
  };

  assert.deepEqual(editableMaterialContent("task", 2, source), {
    "2": { images: ["one", "two", "three"] },
  });
  assert.equal(source["2"].unknown, true);
});

test("full draft gets every exact field and repairs invalid legacy value types", () => {
  const result = editableMaterialContent("full", null, {
    "1": { situation: 4, questions: ["one"], image: "asset" },
    "3": { title: "Project", images: null, imageLabels: ["First", 2] },
  });

  assert.deepEqual(result, {
    "1": { situation: "", banner: "", questions: ["one", "", "", "", ""], image: "asset", imageAlt: "" },
    "2": { images: ["", "", ""] },
    "3": { title: "Project", images: ["", ""], imageLabels: ["First", ""] },
  });
});
```

- [ ] **Step 2: Run the JavaScript test and confirm RED**

Run:

```bash
node --test tests-js/unit/material-content.test.js
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `frontend/js/materials/material-content.js`.

- [ ] **Step 3: Implement the pure projection helper**

Create `frontend/js/materials/material-content.js`:

```javascript
const text = value => typeof value === "string" ? value : "";

const strings = (value, length) => Array.from(
  { length },
  (_, index) => text(Array.isArray(value) ? value[index] : ""),
);

const taskContent = (number, source = {}) => {
  const task = source && typeof source === "object" && !Array.isArray(source) ? source : {};
  if (number === 1) return {
    situation: text(task.situation),
    banner: text(task.banner),
    questions: strings(task.questions, 5),
    image: text(task.image),
    imageAlt: text(task.imageAlt),
  };
  if (number === 2) return { images: strings(task.images, 3) };
  return {
    title: text(task.title),
    images: strings(task.images, 2),
    imageLabels: strings(task.imageLabels, 2),
  };
};

export function editableMaterialContent(kind, taskNumber, source = {}) {
  const tasks = {
    "1": taskContent(1, source?.["1"]),
    "2": taskContent(2, source?.["2"]),
    "3": taskContent(3, source?.["3"]),
  };
  return kind === "task" ? { [String(taskNumber)]: tasks[String(taskNumber)] } : tasks;
}
```

The helper deliberately defaults malformed legacy values to empty editable values. The server still does not mutate the legacy row until the user explicitly saves.

- [ ] **Step 4: Use explicit projection in the editor**

Import `editableMaterialContent` in `frontend/js/materials/material-editor.js`. Keep DOM collection responsible only for updating current editable values, then return the pure projection:

```javascript
import { editableMaterialContent } from "./material-content.js";

function collectContent() {
  ensureContent();
  content["1"] = {
    ...content["1"],
    situation: $("task1Situation").value.trim(),
    banner: $("task1Banner").value.trim(),
    imageAlt: $("task1ImageAlt").value.trim(),
    questions: [...document.querySelectorAll("[data-question]")].map(input => input.value.trim()),
  };
  content["3"] = {
    ...content["3"],
    title: $("task3Title").value.trim(),
    imageLabels: [...document.querySelectorAll("[data-task3-label]")].map(input => input.value.trim()),
  };
  return editableMaterialContent(
    $("materialKind").value,
    Number($("materialTaskNumber").value),
    content,
  );
}
```

Keep the two local spreads: the returned projection is the contract boundary and
removes every non-editable field. Leave `uploadSelectedAssets()` updating the
`content` image arrays before the second save.

- [ ] **Step 5: Run JavaScript tests and lint**

Run:

```bash
npm test
npm run lint:js
```

Expected: all Node tests, including the new projection tests, pass; ESLint reports no errors.

- [ ] **Step 6: Commit browser payload projection**

```bash
git add frontend/js/materials/material-content.js frontend/js/materials/material-editor.js tests-js/unit/material-content.test.js
git commit -m "fix: send canonical material drafts from editor"
```

---

### Task 5: Prove republishing compatibility and document the boundary

**Files:**
- Modify: `tests-e2e/variants-catalog.spec.js`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: the strict HTTP contract from Task 3 and browser projection from Task 4.
- Produces: an end-to-end regression proving enriched published fields are not resent, plus current architecture documentation with no remaining future-work item for `MaterialRequest.content`.

- [ ] **Step 1: Extend the existing editor E2E scenario**

In `registered user publishes a standalone task and opens it from catalog`, after navigating to `/variant-editor.html` and before switching to the mobile viewport, open the newly published material and save it again:

```javascript
await page.locator(`[data-edit-material="${slug}"]`).click();
await expect(page.locator("#materialTitle")).toHaveValue("Авторское описание фотографии");
await page.locator("#saveMaterialBtn").click();
await expect(page.locator("#editorMessage")).toHaveText("Черновик сохранён");
await expect(page.locator("#materialStatus")).toHaveText("Черновик");
await page.locator("#publishMaterialBtn").click();
await expect(page.locator("#editorMessage")).toHaveText("Материал опубликован и доступен в каталоге");
await expect(page.locator("#materialStatus")).toHaveText("Опубликован");
```

This request would return 422 if the editor resent `prepSeconds`, `lead`, `prompts`, or other publication-only fields.

- [ ] **Step 2: Run the focused browser scenario**

Run:

```bash
npx playwright test tests-e2e/variants-catalog.spec.js --grep "registered user publishes"
```

Expected: one test passes and demonstrates create, upload, publish, reload, save, and republish through the strict contract.

- [ ] **Step 3: Update architecture documentation**

In `docs/architecture.md`, expand the strict-contract paragraph near the Progress V2 and review-run description. Record:

```markdown
`MaterialRequest.content` использует отдельный строгий контракт редактируемого черновика: API и
`MaterialService` проверяют точный набор заданий, поля, типы и длины списков до transaction, а публикация
отдельно проверяет заполненность и добавляет фиксированный `EXAM_SPEC`. Существующие `content_json` читаются без
миграции; новый write-путь сохраняет только канонические редактируемые поля.
```

Remove the sentence saying `MaterialRequest.content` is the remaining later stage. Do not change the documentation for legacy assignment tables or official content validation.

- [ ] **Step 4: Run focused regression suites**

Run:

```bash
.venv/bin/python -m unittest tests.unit.test_material_content_contract tests.unit.test_material_service tests.unit.test_material_controller -v
.venv/bin/python -m unittest tests.integration.test_materials -v
npm test
npx playwright test tests-e2e/variants-catalog.spec.js
```

Expected: every focused Python, JavaScript, and Playwright test passes.

- [ ] **Step 5: Commit E2E coverage and documentation**

```bash
git add tests-e2e/variants-catalog.spec.js docs/architecture.md
git commit -m "test: cover strict material content workflow"
```

---

### Task 6: Run final verification and prepare integration

**Files:**
- Verify only; modify implementation files only if a failing check exposes a defect covered by the approved spec.

**Interfaces:**
- Consumes: all Tasks 1–5.
- Produces: a clean feature branch with fresh full-suite evidence and a reviewable commit series.

- [ ] **Step 1: Confirm no obsolete contract remains**

Run:

```bash
rg -n 'content: dict\[str, Any\]|Содержание материала слишком велико|150_000|последующим этапом остаётся только контракт `MaterialRequest.content`' src tests docs/architecture.md
```

Expected: no matches. Historical specs/plans are intentionally excluded from the search.

- [ ] **Step 2: Inspect the change set**

Run:

```bash
git diff --check main...HEAD
git status --short
git log --oneline main..HEAD
```

Expected: no whitespace errors, no generated artifacts, and only the planned source, test, and documentation changes. The user-owned `.superpowers/brainstorm/` may remain untracked in the original checkout but must not be staged or modified.

- [ ] **Step 3: Run the mandatory project check**

Run:

```bash
make check
```

Expected: pre-commit, repository hygiene, content validation, JavaScript tests, Python unit/integration tests, and coverage threshold all pass.

- [ ] **Step 4: Run the mandatory full browser suite**

Run:

```bash
make test-e2e
```

Expected: every Playwright scenario passes.

- [ ] **Step 5: Review and integrate through the branch-finishing workflow**

Read the fresh verification output, inspect `git status --short --branch`, and invoke `superpowers:requesting-code-review` before merge. Resolve only evidence-backed findings, rerun the checks affected by any fix, then invoke `superpowers:finishing-a-development-branch` and offer local merge, PR, or keeping the branch.
