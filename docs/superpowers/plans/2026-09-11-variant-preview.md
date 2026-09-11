# Variant Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Открывать из каталога отдельный предпросмотр варианта со всеми изображениями заданий и явным переходом к тренировке, не помещая вопросы и подсказки в DOM.

**Architecture:** Detail API остаётся без изменений, а чистая frontend-проекция сокращает материал до метаданных и разрешённых same-origin изображений. Отдельные model/view/page модули не дают сетевому payload напрямую попасть в HTML; каталог меняет только цель своего основного действия.

**Tech Stack:** Vanilla JavaScript ES modules, HTML/CSS, Node test runner, Playwright, FastAPI static page allowlist.

**Spec:** `docs/superpowers/specs/2026-09-11-attempt-comparison-and-variant-preview-design.md`

## Global Constraints

- Утверждена отдельная страница предпросмотра (макет A), не accordion и не drawer.
- Полный вариант показывает секции 1–3 и изображения в составе 1 + 3 + 2; task-only материал показывает только своё задание.
- В view model и DOM запрещены `situation`, `banner`, `questions`, `lead`, `prompts`, `starter` и неизвестные поля.
- Разрешены только same-origin image paths `assets/`, `/assets/`, `/api/material-assets/`.
- Detail API, схема материала, база данных и правила доступа не меняются.
- CTA ведёт на `index.html?variant=<material-id>`; возврат ведёт в каталог.
- Сетевые строки экранируются, invalid image URL создаёт пустое состояние, а не `<img>`.
- UI должен помещаться в 360 px, иметь touch targets не менее 44 px и корректный focus management.
- Изменение UI требует JavaScript unit-тестов и Playwright-тестов; финальные проверки — `make check` и `make test-e2e`.

---

## File Structure

- Create `frontend/js/catalog/variant-preview.js`: strict projection and safe image normalization.
- Create `frontend/js/catalog/variant-preview-view.js`: escaped metadata/task gallery markup and state markup.
- Create `frontend/js/catalog/variant-preview-page.js`: URL parsing, detail loading, stale-response guard, retry and focus.
- Modify `frontend/js/catalog/variant-catalog.js`: catalog href and action copy.
- Create `frontend/pages/variant-preview.html`: dedicated preview shell.
- Create `frontend/styles/pages/variant-preview.css`: approved responsive layout.
- Modify `src/trainer/main.py`: allowlist `variant-preview.html`.
- Create `tests-js/unit/variant-preview.test.js`: projection contract.
- Create `tests-js/unit/variant-preview-view.test.js`: escaping and URL safety.
- Create `tests-js/unit/variant-preview-page.test.js`: request generation, status mapping and retry lifecycle.
- Modify `tests-js/unit/views.test.js`: catalog link contract.
- Modify `tests/integration/test_asgi.py`: static page/cache headers.
- Modify `tests-e2e/variants-catalog.spec.js`: catalog → preview → trainer, full and task-only material.
- Create `tests-e2e/variant-preview.spec.js`: hidden content, error, mobile and keyboard scenarios.
- Modify `tests-e2e/history.spec.js`: public navigation matrix includes the new page.
- Modify `README.md`: preview instructions.

### Task 1: Strict preview projection

**Files:**
- Create: `frontend/js/catalog/variant-preview.js`
- Create: `tests-js/unit/variant-preview.test.js`

**Interfaces:**
- Consumes: raw material returned by `/api/materials/{id}`.
- Produces: `projectVariantPreview(material): { id, label, source, year, kind, taskNumber, totalMinutes, tasks }`.
- Each task is `{ number, title, images }`; each image is `{ src, alt, label }`.
- Produces: `isSafeMaterialImageUrl(value): boolean` for view defense in depth.
- Throws `VariantPreviewError` with code `invalid_material` when required metadata/task structure is unusable.

- [ ] **Step 1: Write a failing full-material projection test**

```js
test("projection keeps all six images but no question content", () => {
  const preview = projectVariantPreview(fullMaterialFixture());
  assert.deepEqual(preview.tasks.map(task => task.images.length), [1, 3, 2]);
  assert.equal(preview.tasks[2].images[0].label, "Осень");
  const serialized = JSON.stringify(preview);
  for (const secret of ["situation", "banner", "questions", "lead", "prompts", "starter", "минимальный возраст"]) {
    assert.doesNotMatch(serialized, new RegExp(secret));
  }
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test tests-js/unit/variant-preview.test.js`

Expected: FAIL because `variant-preview.js` does not exist.

- [ ] **Step 3: Implement explicit allowlist projection**

Use fixed neutral titles:

```js
const TASK_TITLES = {
  1: "Задание 1 · Вопросы к объявлению",
  2: "Задание 2 · Описание фотографии",
  3: "Задание 3 · Проектная работа",
};
```

Copy metadata fields one by one. For `kind === "task"`, use only validated `taskNumber`; otherwise iterate `[1,2,3]`. Read task 1 from `image`, tasks 2/3 from `images`; never spread the raw material or raw task object.

- [ ] **Step 4: Add safe URL and alt tests**

Accept `assets/variants/a.webp`, `/assets/variants/a.webp`, and exact `/api/material-assets/17`; reject `javascript:`, `data:`, protocol-relative, absolute URLs, query/fragment suffixes, backslashes, control characters, empty path segments, literal or percent-decoded traversal, and non-positive/non-numeric material asset IDs. Assert `imageAlt`/`imageLabels` are used only as text, and missing labels become `Изображение <N> задания <task>`.

- [ ] **Step 5: Add task-only and invalid-material tests**

Assert task-only number 2 returns one section with three images. Assert missing ID, invalid kind/task number, or missing requested task throws `VariantPreviewError("invalid_material")`. Invalid individual image URL remains in the projected slot as `{ src: null, ... }` so the view can show an explicit placeholder.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `node --test tests-js/unit/variant-preview.test.js`

Expected: all projection tests PASS.

- [ ] **Step 7: Commit projection model**

```bash
git add frontend/js/catalog/variant-preview.js tests-js/unit/variant-preview.test.js
git commit -m "feat: project safe variant preview data"
```

### Task 2: Escaped preview view

**Files:**
- Create: `frontend/js/catalog/variant-preview-view.js`
- Create: `tests-js/unit/variant-preview-view.test.js`

**Interfaces:**
- Consumes: only the projected view model from Task 1.
- Produces: `variantPreviewMarkup(preview): string` and `variantPreviewStateMarkup({ kind, message }): string`.
- The view repeats the image URL allowlist before emitting `<img>`.

- [ ] **Step 1: Write a failing safe markup test**

```js
test("preview markup renders galleries and escapes all network text", () => {
  const html = variantPreviewMarkup(previewFixture({ label: "<script>bad</script>" }));
  assert.equal((html.match(/<img /g) || []).length, 6);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.match(html, /Перейти к тренировке/);
  assert.doesNotMatch(html, /<script>|javascript:|минимальный возраст/);
});
```

- [ ] **Step 2: Run the view test and verify RED**

Run: `node --test tests-js/unit/variant-preview-view.test.js`

Expected: FAIL because the view module does not exist.

- [ ] **Step 3: Implement header, facts and task gallery markup**

Use `escapeHtml` and `pluralize`. Render task sections with `aria-labelledby`, `<figure>`, `<img loading="lazy">` and optional escaped `<figcaption>`. Build the CTA with `new URLSearchParams({ variant: preview.id })` and a relative `index.html?...` href.

- [ ] **Step 4: Implement unavailable-image and page-state markup**

For `src === null` render `.variant-preview-image-missing` with text `Изображение недоступно`. Define loading, `not_found`, `forbidden`, `network`, and `invalid_material` messages without including raw server HTML.

- [ ] **Step 5: Add defense-in-depth tests**

Pass an invalid URL directly in a forged view model and assert no `<img>` is emitted. Assert malicious label/source/alt/caption/ID values are escaped and cannot add attributes. Assert task-only markup has one section.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `node --test tests-js/unit/variant-preview.test.js tests-js/unit/variant-preview-view.test.js`

Expected: PASS.

- [ ] **Step 7: Commit the view**

```bash
git add frontend/js/catalog/variant-preview-view.js tests-js/unit/variant-preview-view.test.js
git commit -m "feat: render safe variant preview galleries"
```

### Task 3: Dedicated preview page, loader and static route

**Files:**
- Create: `frontend/js/catalog/variant-preview-page.js`
- Create: `frontend/pages/variant-preview.html`
- Create: `frontend/styles/pages/variant-preview.css`
- Modify: `src/trainer/main.py:199-207`
- Modify: `tests/integration/test_asgi.py:36-55`
- Create: `tests-js/unit/variant-preview-page.test.js`
- Create: `tests-e2e/variant-preview.spec.js`

**Interfaces:**
- Consumes: `api`, `projectVariantPreview`, `variantPreviewMarkup`, `variantPreviewStateMarkup`.
- Produces: a static `variant-preview.html?variant=<id>` route with retryable detail loading.
- Exports: `createVariantPreviewPageController({ request, render, focus }): { load, retry }` for deterministic unit tests.
- Only the latest request generation may mutate the DOM.

- [ ] **Step 1: Add failing static route coverage**

Extend `test_health_static_and_private_data_boundary` to assert 200/no-cache/nosniff for:

```python
"/variant-preview.html",
"/js/catalog/variant-preview-page.js",
"/styles/pages/variant-preview.css",
```

Run: `.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary -v`

Expected: FAIL with 404 for `/variant-preview.html`.

- [ ] **Step 2: Create the page shell and add its allowlist entry**

Add `variant-preview.html` to the `pages` set in `src/trainer/main.py`. The HTML contains shared navigation, `#variantPreviewTitle` with `tabindex="-1"`, back link, `#variantPreviewStatus`, `#variantPreviewContent`, and retry button container. Rerun the integration test and expect PASS.

- [ ] **Step 3: Write failing controller tests**

Test success, 403, 404, network failure, invalid projected payload, retry, and two overlapping `load()` calls resolved out of order. Assert only the newest generation renders and focuses. Run:

`node --test tests-js/unit/variant-preview-page.test.js`

Expected: FAIL because the page controller does not exist.

- [ ] **Step 4: Implement the generation-safe loader and retry**

Export an injectable controller with no top-level DOM dependency. Parse and validate the variant ID in the browser bootstrap, then pass it to the controller. Each `load()` increments generation, renders loading, requests `/api/materials/${encodeURIComponent(id)}`, projects the response and renders only if its generation is current. Map 403/404/network/invalid payload to stable state codes; `retry()` calls `load()`. Focus only after the current generation reaches success or terminal error.

- [ ] **Step 5: Run controller tests and verify GREEN**

Run: `node --test tests-js/unit/variant-preview-page.test.js`

Expected: PASS.

- [ ] **Step 6: Write failing E2E for a full preview**

Visit `/variant-preview.html?variant=open-2026`; assert six images grouped as 1/3/2, all task headings, material metadata, and CTA URL. Assert known secret strings from `content/variants/open-2026.json` such as `минимальный возраст`, `欢迎你们加入轮滑鞋俱乐部`, and `我选择第` are absent from `page.content()`.

- [ ] **Step 7: Connect the browser bootstrap and retry**

Parse exact `variant` once; reject empty/over-80-character IDs before fetch. Bind the injected controller to `#variantPreviewStatus`, `#variantPreviewContent`, the retry container and `#variantPreviewTitle`; delegate `[data-preview-retry]` to `retry()`.

- [ ] **Step 8: Implement the approved responsive page CSS**

Desktop: metadata/CTA header followed by sequential task sections; task 1 single wide image, task 2 three columns, task 3 two columns. Mobile ≤700 px: one image column, no horizontal overflow, 44 px back/retry/CTA targets, visible focus outlines, preserved image aspect ratios.

- [ ] **Step 9: Add error, mobile and keyboard E2E tests**

Cover 404 with retry, malicious payload text escaping, invalid image placeholder, 360×800 overflow, touch sizes, and focus on `#variantPreviewTitle` after success/error. The out-of-order response race stays in the deterministic controller unit test.

- [ ] **Step 10: Run focused tests**

Run: `node --test tests-js/unit/variant-preview.test.js tests-js/unit/variant-preview-view.test.js tests-js/unit/variant-preview-page.test.js`

Run: `.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary -v`

Run: `npx playwright test tests-e2e/variant-preview.spec.js`

Expected: PASS.

- [ ] **Step 11: Commit the standalone preview page**

```bash
git add frontend/js/catalog/variant-preview-page.js frontend/pages/variant-preview.html frontend/styles/pages/variant-preview.css src/trainer/main.py tests/integration/test_asgi.py tests-js/unit/variant-preview-page.test.js tests-e2e/variant-preview.spec.js
git commit -m "feat: add dedicated variant preview page"
```

### Task 4: Route catalog cards through preview

**Files:**
- Modify: `frontend/js/catalog/variant-catalog.js`
- Modify: `frontend/styles/pages/variants.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/variants-catalog.spec.js`
- Modify: `tests-e2e/history.spec.js`

**Interfaces:**
- Consumes: preview route from Task 3.
- Produces: catalog card href `variant-preview.html?variant=<encoded id>` and action label `Предпросмотр`.
- The preview CTA remains the only transition from catalog browsing to `index.html?variant=...`.

- [ ] **Step 1: Write a failing catalog unit test**

```js
const html = catalogMarkup([variantFixture]);
assert.match(html, /href="variant-preview\.html\?variant=open-2026"/);
assert.match(html, />Предпросмотр →<\/a>/);
assert.doesNotMatch(html, /href="index\.html\?variant=/);
```

- [ ] **Step 2: Run the unit test and verify RED**

Run: `node --test tests-js/unit/views.test.js`

Expected: FAIL because catalog still links directly to `index.html`.

- [ ] **Step 3: Change catalog href, copy and stretched-link behavior**

Build the preview href with `URLSearchParams`; rename `.variant-open` text to `Предпросмотр →`. Make `.variant-card` positioned and the single anchor cover the understandable card surface through `::after`, while preserving visible focus and not creating nested controls.

- [ ] **Step 4: Update guest catalog E2E flow**

After clicking the official card action, assert `variant-preview.html?variant=open-2026`, six preview images and no question content; then click `Перейти к тренировке` and retain existing assertions for selected material and 14 minutes.

- [ ] **Step 5: Update task-only catalog E2E flow**

After publishing task 2, click preview, assert one task section and three images, then use CTA and retain the existing trainer-selection assertions. Confirm direct revisit to `/` still uses the saved material as before.

- [ ] **Step 6: Extend public navigation coverage**

Add `/variant-preview.html?variant=open-2026` to the loop that checks shared History navigation. Do not add Compare here because it is an authenticated contextual page and is covered in the comparison plan.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `node --test tests-js/unit/views.test.js tests-js/unit/variant-preview.test.js tests-js/unit/variant-preview-view.test.js tests-js/unit/variant-preview-page.test.js`

Run: `npx playwright test tests-e2e/variants-catalog.spec.js tests-e2e/variant-preview.spec.js tests-e2e/history.spec.js`

Expected: PASS.

- [ ] **Step 8: Commit catalog integration**

```bash
git add frontend/js/catalog/variant-catalog.js frontend/styles/pages/variants.css tests-js/unit/views.test.js tests-e2e/variants-catalog.spec.js tests-e2e/history.spec.js
git commit -m "feat: open catalog materials in preview"
```

### Task 5: Documentation, mandatory verification and review

**Files:**
- Modify: `README.md:5-52`

**Interfaces:**
- Consumes: complete preview flow from Tasks 1-4.
- Produces: user-facing instructions; no runtime interface.

- [ ] **Step 1: Update README feature and training flow**

Add safe image preview to «Что доступно». Replace direct catalog-to-trainer wording with: choose a material, inspect every task image without questions, then press «Перейти к тренировке». Explain that the preview intentionally hides questions and answer prompts.

- [ ] **Step 2: Run all focused tests**

Run: `node --test tests-js/unit/variant-preview.test.js tests-js/unit/variant-preview-view.test.js tests-js/unit/variant-preview-page.test.js tests-js/unit/views.test.js`

Run: `.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary -v`

Run: `npx playwright test tests-e2e/variant-preview.spec.js tests-e2e/variants-catalog.spec.js tests-e2e/history.spec.js`

Expected: PASS.

- [ ] **Step 3: Run mandatory verification**

Run: `make check`

Run: `make test-e2e`

Expected: both exit 0 with no skipped preview tests.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain variant image previews"
```

- [ ] **Step 5: Request code review before integration**

Review the full branch against the spec, emphasizing absence of hidden question fields in DOM/accessibility, image URL allowlist, stale-response isolation, task-only behavior, mobile galleries and changed catalog navigation. Resolve every Critical/Important finding and rerun mandatory verification before offering merge/PR/keep options.
