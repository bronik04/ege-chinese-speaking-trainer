# Frontend Code Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the JavaScript custom-select polyfill and duplicate home-page CSS layer while keeping the current native-select behavior, layout, accessibility, and visual hierarchy.

**Architecture:** Browser-native `<select>` elements become the only form-select implementation. The hidden home-page variant selector remains an internal synchronization control because visible material cards provide that choice; editor and account filters use styled native controls. `base.css` keeps one canonical home-page rule set and no selectors for deleted JavaScript-generated markup.

**Tech Stack:** HTML5, vanilla JavaScript ES modules, CSS, Node test runner, ESLint, Playwright

**Spec:** `docs/superpowers/specs/2026-08-30-technical-removal-cleanup-design.md`

## Global Constraints

- Preserve all current form values, change events, filtering, editor behavior, and material-card synchronization.
- Keep `#variantSelect` visually hidden because `#materialList` is its accessible visible choice surface.
- Native selects shown to users must remain at least 44 px high and retain visible keyboard focus.
- Do not change colors, typography, spacing, responsive breakpoints, or application copy beyond selectors required by the cleanup.
- Update JavaScript and Playwright coverage before deleting the implementation.
- Run both `make test-e2e` and `make check` before declaring this package complete.

---

### Task 1: Replace the custom-select polyfill with native controls

**Files:**
- Modify: `tests-e2e/variants-catalog.spec.js:154-163`
- Modify: `tests-e2e/account-workflows.spec.js:158`
- Modify: `frontend/js/runner/app.js:10,379`
- Modify: `frontend/js/materials/material-editor.js:2,33,193`
- Modify: `frontend/pages/index.html:27`
- Modify: `frontend/styles/base.css:89-99,640-695`
- Modify: `frontend/styles/pages/variant-editor.css:70-80,134`
- Delete: `frontend/js/shared/project-select.js`

**Interfaces:**
- Consumes: native `HTMLSelectElement.value`, `change`, `selectOption()`, and browser keyboard semantics
- Produces: visible native `#materialKind`, `#materialTaskNumber`, `#reviewTaskFilter`, and `#reviewStatusFilter`; hidden synchronization-only `#variantSelect`

- [ ] **Step 1: Change the browser tests to describe native controls**

In `variants-catalog.spec.js`, replace the custom menu assertions with:

```javascript
const materialKind = page.locator("#materialKind");
const materialTaskNumber = page.locator("#materialTaskNumber");
await expect(materialKind).toBeVisible();
await expect(materialKind).toHaveCSS("min-height", "44px");
await expect(materialTaskNumber).toHaveCSS("min-height", "44px");
await materialKind.selectOption("task");
await expect(materialKind).toHaveValue("task");
await expect(page.locator("#taskNumberField")).toBeVisible();
await expect(page.locator(".project-select")).toHaveCount(0);
```

In `account-workflows.spec.js`, replace the readiness assertion with:

```javascript
for (const selector of ["#reviewTaskFilter", "#reviewStatusFilter"]) {
  await expect(teacherPage.locator(selector)).toBeVisible();
  await expect(teacherPage.locator(selector)).toHaveCSS("min-height", "44px");
}
await expect(teacherPage.locator(".project-select")).toHaveCount(0);
```

- [ ] **Step 2: Run the focused tests and verify the old implementation fails them**

Run:

```bash
npx playwright test tests-e2e/variants-catalog.spec.js tests-e2e/account-workflows.spec.js
```

Expected: FAIL because the polyfill hides the native selects and inserts `.project-select` wrappers.

- [ ] **Step 3: Remove JavaScript enhancement calls**

Delete the `project-select.js` imports from both entry points. Delete `enhanceProjectSelects()` from both
initialization flows and `syncProjectSelects()` from `showTasks()`. Do not replace these calls: native
controls update themselves, and the existing `change` listeners already drive application behavior.

Delete `frontend/js/shared/project-select.js`.

- [ ] **Step 4: Keep the home-page synchronization select hidden explicitly**

In `index.html`, simplify the select to:

```html
<label class="material-list-native-label"><span id="variantSource">Выберите вариант</span><select id="variantSelect" aria-label="Выбор варианта"></select></label>
```

Rename the corresponding visually-hidden rule from `.project-select-native-label` to
`.material-list-native-label`. Do not globally hide native selects.

- [ ] **Step 5: Style native form selects and remove generated-markup rules**

Replace the `.project-select*` block in `base.css` with:

```css
select {
  min-height: 44px;
  padding: 10px 36px 10px 12px;
  border: 1px solid var(--action-border);
  border-radius: var(--radius-sm);
  color: var(--ink);
  background-color: var(--paper);
  font: 15px/1.35 var(--font-body);
}

select:focus-visible {
  outline: 3px solid var(--crimson);
  outline-offset: 3px;
  border-color: var(--crimson);
}
```

Remove `.project-select-trigger` and `.project-select-option` from the shared `:is(...)` groups and the
44 px utility group. In `variant-editor.css`, change every `.project-select-trigger` entry in `:where(...)`
to `select`, retaining the editor-specific border and focus colors.

- [ ] **Step 6: Verify the focused behavior**

Run:

```bash
npm run lint
npm test
npx playwright test tests-e2e/variants-catalog.spec.js tests-e2e/account-workflows.spec.js
rg -n "project-select|enhanceProjectSelects|syncProjectSelects|data-project-select" frontend tests-js tests-e2e
```

Expected: lint, unit tests, and focused browser tests pass; `rg` returns no matches.

- [ ] **Step 7: Commit**

```bash
git add frontend tests-e2e
git commit -m "refactor: use native select controls"
```

---

### Task 2: Collapse the duplicate home-page CSS layer

**Files:**
- Create: `tests-js/unit/styles.test.js`
- Modify: `frontend/styles/base.css:49-60,464-470`

**Interfaces:**
- Consumes: the final home-page declarations currently applied by browser cascade
- Produces: one canonical declaration for each home-page selector and a static guard against reintroducing the retired layers

- [ ] **Step 1: Add a failing static CSS regression test**

Create `tests-js/unit/styles.test.js`:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../../frontend/styles/base.css", import.meta.url), "utf8");

test("base stylesheet has no retired override layers or custom-select markup", () => {
  assert.doesNotMatch(css, /Главная 2A|Финальные overrides главного экрана|legacy-правил/);
  assert.doesNotMatch(css, /\.project-select/);
});
```

- [ ] **Step 2: Run the test and verify the duplicate markers fail it**

Run: `npm test`

Expected: FAIL on `Главная 2A` or `Финальные overrides главного экрана` before the stylesheet cleanup.

- [ ] **Step 3: Delete only the overridden preliminary home rules**

Remove the preliminary home block beginning with `/* Главная 2A` and ending immediately before the
shared base component declarations. Keep the later declarations that currently win the cascade as the
canonical block, but remove the comment that calls them “final overrides” or “legacy rules”.

Before deleting the preliminary block, relocate into the canonical block every declaration from it that
still contributes to the current cascade. In particular, preserve the current rules for `.brand-mark`,
`.brand-divider`, `.brand-name`, `.material-catalog-link`, `.material-row:hover`, `.material-action`,
`.hero-text`, `.hero-meta b`, `.speed-switch span`, `.speed-switch span::after`, `.task-card i`,
`.mic-state`, `.status-dot`, and `.status-dot.ok/.bad`. When the same property occurs in both blocks, keep
the value from the later block because that is the value users currently see (for example, the selected
material-row shadow). Rename `.project-select-native-label` to `.material-list-native-label` while moving
it. The result must have one desktop home rule layer followed only by its two responsive media overrides.

- [ ] **Step 4: Run static and focused browser verification**

Run:

```bash
npm test
npm run lint
npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/variants-catalog.spec.js
```

Expected: all tests pass and the material cards, home hero, editor controls, and 390 px layout remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/styles/base.css tests-js/unit/styles.test.js
git commit -m "refactor: collapse duplicate frontend styles"
```

---

### Task 3: Complete visual and repository verification

**Files:**
- Modify only if verification exposes a regression introduced by Tasks 1–2

**Interfaces:**
- Consumes: native-select and CSS cleanup changes
- Produces: verified desktop/mobile UI with no removed frontend references

- [ ] **Step 1: Inspect the two affected surfaces at desktop width**

Start the documented local server and use the in-app browser to inspect:

- `/` with the teacher cabinet open: both review filters are visible, aligned, keyboard-focusable, and usable;
- `/variant-editor.html`: both native selects align with adjacent inputs and switching to `task` reveals the task-number field;
- `/`: the material list remains the visible selector and the synchronization-only `#variantSelect` does not create extra space.

Capture screenshots only for comparison during implementation; do not commit them.

- [ ] **Step 2: Repeat at 390 × 844**

Verify there is no horizontal overflow, each visible select is at least 44 px high, labels remain associated,
and native dropdown use does not depend on deleted custom-menu keyboard handlers.

- [ ] **Step 3: Run all required checks**

Run:

```bash
make test-e2e
make check
rg -n "project-select|enhanceProjectSelects|syncProjectSelects|data-project-select|Главная 2A|Финальные overrides главного экрана" frontend tests-js tests-e2e
git diff --check
git status --short
```

Expected: E2E and mandatory checks pass; `rg` returns no matches; only intentional cleanup changes and the
pre-existing untracked `.superpowers/brainstorm/` are present.

---

### Task 4: Archive the completed cleanup package

**Files:**
- Move: `docs/superpowers/specs/2026-08-30-technical-removal-cleanup-design.md`
- Move: `docs/superpowers/plans/2026-08-30-retired-backend-removal.md`
- Move: `docs/superpowers/plans/2026-08-30-active-documentation-cleanup.md`
- Move: `docs/superpowers/plans/2026-08-30-frontend-code-pruning.md`
- Modify: `docs/archive/superpowers/README.md`

**Interfaces:**
- Consumes: the four cleanup documents after all three implementation packages pass
- Produces: no completed implementation records in the active `docs/superpowers/` directories

- [ ] **Step 1: Confirm every preceding task is complete**

Do not start this task until backend removal, documentation cleanup, frontend pruning, `make test-e2e`, and
`make check` all have fresh successful output.

- [ ] **Step 2: Move the current cleanup documents into the historical archive**

Move the spec to `docs/archive/superpowers/specs/` and all three plans to
`docs/archive/superpowers/plans/`. Add a short dated entry to the archive README naming this cleanup package.

- [ ] **Step 3: Verify links and the active/archive boundary**

Run:

```bash
rg -n "docs/superpowers/(specs/2026-08-30-technical-removal-cleanup-design|plans/2026-08-30-(retired-backend-removal|active-documentation-cleanup|frontend-code-pruning))" . --glob '!docs/archive/**' --glob '!.git/**'
find docs/superpowers/plans docs/superpowers/specs -maxdepth 1 -type f -print | sort
git diff --check
```

Expected: no stale active links and no completed files remain in the active plan/spec directories.

- [ ] **Step 4: Commit**

```bash
git add docs/archive docs/superpowers
git commit -m "docs: archive technical cleanup records"
```
