# UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the agreed three-mode UI so choosing material, speaking practice, and teacher review are clear, responsive, and visually consistent.

**Architecture:** Keep the existing FastAPI APIs, review-request lifecycle, and material JSON unchanged unless a UI contract makes a change unavoidable. Rework the learner flow in the current `index.html` runner, and move teacher review from an account modal into a separate static page with its own small browser controller that consumes the existing teacher review endpoints. Keep page-specific layout CSS in `frontend/styles/pages/` and retain shared tokens/base controls in `frontend/styles/base.css`.

**Tech Stack:** FastAPI static-file server, semantic HTML, CSS custom properties, vanilla ES modules, Node test runner, Playwright, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-25-ui-ux-redesign-design.md`

## Global Constraints

- Preserve the warm paper background, dark brown text, deep red accent, and editorial serif visual language.
- The landing motto is horizontal: `熟能生巧` appears above the Russian translation; pinyin and vertical writing are removed.
- Do not add an “About me” block, groups, assignments, deadlines, written feedback, or new review/scoring rules.
- The user’s existing recordings, progress, request states, review scores, and API routes remain compatible.
- Task 2 shows all source photographs; task 3 shows both source photographs with equal visual weight. Images stay visible in preparation, recording, playback, and retry states.
- The teacher workspace is a full page, not a modal. It supports the current score-only review flow and no text comments.
- Preserve semantic controls, focus management for the remaining dialogs, visible textual state, 44×44px touch targets, `prefers-reduced-motion`, and WCAG-AA contrast.
- Every user-facing markup/behavior change begins with a failing JavaScript or Playwright test.
- Run `make check` and `make test-e2e` before handoff.

---

## File Structure

- `frontend/pages/index.html` remains the public landing, runner, result, and account page; its hero, format selection, runner landmarks, and account action change.
- `frontend/styles/base.css` retains shared tokens, button styles, global header/footer, dialog primitives, and shared responsive rules; obsolete teacher-modal rules are removed.
- `frontend/styles/pages/teacher.css` contains only the dedicated teacher workspace layout and responsive rules.
- `frontend/js/runner/task-view.js` continues to render task material; it makes photo material precede task guidance and gives photo groups stable semantics.
- `frontend/js/teacher/teacher-view.js` renders the teacher queue rows and selected request detail without raw API data or storage keys.
- `frontend/js/teacher/teacher-page.js` guards the page to the configured teacher, loads/filter/selects requests, and saves score-only reviews via existing APIs.
- `frontend/pages/teacher.html` is the teacher workspace shell and loads the dedicated controller.
- `frontend/js/account/account-controller.js`, `frontend/js/account/account-auth-controller.js`, and `frontend/js/runner/app.js` stop mounting the teacher modal and route a signed-in teacher to `teacher.html`.
- `src/trainer/main.py` allowlists `teacher.html` in the current safe static-page route.
- `tests-js/unit/views.test.js` gains stable renderer checks for photo ordering/semantics and teacher queue/detail markup.
- `tests-e2e/reference.spec.js`, `tests-e2e/account-workflows.spec.js`, and `tests-e2e/student-teacher.spec.js` cover the new public hero, persistent photo material, teacher navigation, filtering, and score save flow.

---

### Task 1: Establish the landing-page hierarchy and remove obsolete hero/footer content

**Files:**
- Modify: `frontend/pages/index.html`
- Modify: `frontend/styles/base.css`
- Modify: `tests-e2e/reference.spec.js`

**Interfaces:**
- Produces the stable public landmarks `#homeScreen`, `#variantSelect`, `[data-start="exam"]`, `[data-start="1"]`, `[data-start="2"]`, and `[data-start="3"]`; existing JavaScript keeps using them unchanged.
- Produces a hero with `.hero-chinese` before `.hero-translation`, no `.hero-reading`, and horizontal CSS writing mode.
- Keeps `#authButton` as the last header action and keeps `#referenceLink` available outside an active runner screen.

- [ ] **Step 1: Write failing landing-page browser assertions**

  In `tests-e2e/reference.spec.js`, replace the broad bilingual-motto test with assertions that the hero contains `熟能生巧`, does not contain `shú néng`, and has a computed horizontal writing mode. Assert that the Chinese phrase precedes the Russian translation in the hero, that the three task cards remain individually enabled after materials load, and that the footer has no `.footer-about` element.

  ```js
  test("home presents a horizontal motto and a direct practice choice", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".hero-chinese")).toHaveText("熟能生巧");
    await expect(page.locator(".hero-reading")).toHaveCount(0);
    await expect(page.locator(".hero-chinese")).toHaveCSS("writing-mode", "horizontal-tb");
    await expect(page.locator(".hero-copy")).toContainText("Мастерство приходит с практикой");
    await expect(page.locator(".footer-about")).toHaveCount(0);
    await expect(page.locator('[data-start="2"]')).toBeEnabled();
  });
  ```

- [ ] **Step 2: Run the focused test and verify RED**

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js --grep 'horizontal motto'`

  Expected: FAIL because `.hero-reading` and vertical CSS still exist and the footer still includes the biography block.

- [ ] **Step 3: Rebuild the public page hierarchy without changing runner IDs**

  In `frontend/pages/index.html`:

  - change `.hero-couplet` to a normal heading stack: `.hero-chinese` then `.hero-translation`;
  - remove `.hero-reading` entirely;
  - make the page copy explain preparation, recording, and optional teacher review in one short paragraph;
  - add a visible, non-interactive three-step explanation after the facts row;
  - label the material select as a choice of material and group the full simulation separately from individual task cards;
  - retain `#variantSelect`, `#fastMode`, `#checkMicBtn`, all `[data-start]` buttons, and all account/review request IDs used by `app.js`;
  - remove `.footer-about` while retaining the legal/footer navigation and contact links.

  In `frontend/styles/base.css`:

  - replace the `.hero-couplet` grid and `.hero-chinese { writing-mode: vertical-rl; }` with a vertical text stack;
  - remove the pinyin selector;
  - give the hero one primary action visual treatment without making a second duplicate call-to-action;
  - keep the existing color variables; do not introduce a second palette;
  - use `min-height: 44px` for new interactive controls and add only short transition rules guarded by the existing reduced-motion rule.

- [ ] **Step 4: Run focused browser coverage and inspect the narrow layout**

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js --grep 'horizontal motto|mobile navigation'`

  Expected: PASS. The hero reads left-to-right on desktop and mobile, no horizontal scrollbar appears at 390px, and existing public navigation still has finger-sized targets.

- [ ] **Step 5: Commit the landing hierarchy change**

  ```bash
  git add frontend/pages/index.html frontend/styles/base.css tests-e2e/reference.spec.js
  git commit -m "feat: simplify practice landing page"
  ```

### Task 2: Make photographic task material persistently primary in practice mode

**Files:**
- Modify: `frontend/js/runner/task-view.js`
- Modify: `frontend/styles/base.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/reference.spec.js`

**Interfaces:**
- `taskMarkup(task, data, state)` keeps returning a safe HTML string and continues to consume `{ phase, questionIndex, selectedPhoto, photoChoiceMade }`.
- For task 2 it produces one labelled `.photo-grid` before `.prompt-list`; selecting a photo changes only the selected-state indicator and never hides, blurs, removes, or demotes the other source photos.
- For task 3 it produces `.photo-grid.project-photos` containing exactly two labelled, equally-sized photographs before `.prompt-list`.
- `#taskContent` remains `inert` and `aria-hidden="true"` until preparation starts, preserving the existing anti-spoiler accessibility contract.

- [ ] **Step 1: Add failing renderer tests for photo order and equal visibility**

  In `tests-js/unit/views.test.js`, add fixtures for tasks 2 and 3. Assert that task 2 markup contains all three source URLs, places `photo-grid` before `prompt-list`, gives each selectable photo a unique accessible label, and does not emit a class that hides non-selected photos. Assert that task 3 emits two `figure`/image labels before the prompts and uses `project-photos`.

  ```js
  test("photo tasks render their source images before speaking guidance", () => {
    const html = taskMarkup(3, {
      title: "Сравнение", lead: "Сравните", prompts: ["Сходства"],
      images: ["one.webp", "two.webp"], imageLabels: ["Осень", "Зима"],
    }, { phase: "answer", questionIndex: 0, selectedPhoto: 1, photoChoiceMade: false });
    assert.ok(html.indexOf('src="one.webp"') < html.indexOf("prompt-list"));
    assert.ok(html.indexOf('src="two.webp"') < html.indexOf("prompt-list"));
    assert.match(html, /project-photos/);
  });
  ```

- [ ] **Step 2: Run the unit suite and verify RED**

  Run: `npm test -- --test-name-pattern='photo tasks render' tests-js/unit/views.test.js`

  Expected: FAIL because task markup currently renders the guidance before the photo grid and task 3 uses generic `div` image cards.

- [ ] **Step 3: Change photo markup and CSS without changing material JSON or recorder behavior**

  In `frontend/js/runner/task-view.js`:

  - render task 2’s photo-choice fieldset/group immediately after the title/lead and before the starter/prompt list; retain click target `data-photo` so `runner-controller.js` needs no selection API change;
  - give each task-2 choice a visible `Фотография N` label and an accessible group label; preserve the selected indicator through preparation and answer phases;
  - render task 3 photographs as semantic `figure` elements with their existing `imageLabels` as both visible captions and image alternatives;
  - keep `escapeHtml` around every content URL, label, and prompt.

  In `frontend/styles/base.css`:

  - place photo grids before dense instruction text visually as well as in DOM order;
  - remove the selected-photo expansion/blur/opacity rule so every task-2 photo remains legible after selection;
  - make task 3’s two figures equal-width at desktop and stack without cropping at narrow widths;
  - ensure images use `object-fit: contain` where a source photo would otherwise be cropped, and preserve a visible selected border independent of color with text/aria state.

- [ ] **Step 4: Add a failing browser regression for persistent image material**

  In `tests-e2e/reference.spec.js`, add a task-2 flow that starts preparation, selects a photo, then advances to the answer phase with the existing “Перейти к ответу” control. Assert that all `.photo-choice img` remain visible and that the selected photo has a visible state. Add the equivalent task-3 assertion that exactly two project-photo figures are visible after the task opens.

  ```js
  await page.locator('[data-start="2"]').click();
  await page.locator("#mainActionBtn").click();
  await page.locator('[data-photo="1"]').click();
  await page.locator("#skipBtn").click();
  await expect(page.locator(".photo-choice img")).toHaveCount(3);
  await expect(page.locator(".photo-choice img").first()).toBeVisible();
  ```

- [ ] **Step 5: Run focused unit and browser tests and verify GREEN**

  Run: `npm test -- --test-name-pattern='photo tasks render|task markup' tests-js/unit/views.test.js`

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js --grep 'persistent image|runner keeps locked'`

  Expected: PASS. Task content is still inaccessible before preparation, while all required photographs remain visibly available after the runner reveals the task.

- [ ] **Step 6: Commit the photo-first practice change**

  ```bash
  git add frontend/js/runner/task-view.js frontend/styles/base.css tests-js/unit/views.test.js tests-e2e/reference.spec.js
  git commit -m "feat: keep task photos visible during practice"
  ```

### Task 3: Refocus the runner around the current stage and one next action

**Files:**
- Modify: `frontend/pages/index.html`
- Modify: `frontend/styles/base.css`
- Modify: `frontend/js/runner/runner-controller.js`
- Modify: `tests-e2e/reference.spec.js`

**Interfaces:**
- `createRunnerController(ctx)` keeps its current exported methods: `startRun`, `ensureMicrophone`, `startPreparation`, `skipPhase`, `exitRun`, and `toggleSound`.
- `render()` continues updating `#taskBadge`, `#phaseCaption`, `#timerEyebrow`, `#timerValue`, `#timerHint`, `#recordingState`, `#mainActionBtn`, and `#skipBtn`.
- The runner emits a visually explicit task progress rail from existing `#stepList`; no progress data model change is introduced.

- [ ] **Step 1: Write failing stage-focused browser assertions**

  In `tests-e2e/reference.spec.js`, add a test that starts a task and checks for: one visible current task label, one enabled primary runner action, a visible preparation/answer textual state, and task-progress status. Advance once and assert the primary button label/state changes rather than introducing a second primary action.

  ```js
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#stepList .step-pill.active")).toContainText("Задание 1");
  await expect(page.locator("#mainActionBtn")).toHaveText("Начать подготовку");
  await expect(page.locator("#mainActionBtn")).toBeEnabled();
  ```

- [ ] **Step 2: Run the focused assertion and verify RED**

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js --grep 'stage-focused'`

  Expected: FAIL until the new progress/state landmarks are present in the redesigned layout.

- [ ] **Step 3: Recompose runner markup and styles around existing state controls**

  In `frontend/pages/index.html` and `frontend/styles/base.css`:

  - preserve the current IDs and button handlers, but make the runner header compact and reserve it for exit, progress, and truthful mode/saving state;
  - turn `#stepList` into a narrow desktop progress rail and a concise mobile progress summary;
  - keep task material as the dominant document area and timer/recording state as an adjacent, non-obscuring control area;
  - make `#mainActionBtn` the only visually primary action for the active phase; `#skipBtn` remains clearly secondary;
  - retain sticky timer behavior only when sufficient horizontal space exists, avoiding hidden content or focus traps on mobile;
  - preserve `aria-hidden`/`inert` locking and do not move the timer into a live region.

  In `frontend/js/runner/runner-controller.js`, update only the state copy needed by the new visual labels. Do not change timing, recorder setup, object URL lifetime, progress persistence, or review submission eligibility.

- [ ] **Step 4: Run focused browser coverage at desktop and mobile widths**

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js --grep 'stage-focused|runner keeps locked|mobile navigation'`

  Expected: PASS. Keyboard focus reaches exit, primary action, optional skip, and recording controls in a logical order; a 390px viewport has no horizontal overflow.

- [ ] **Step 5: Commit the focused runner layout**

  ```bash
  git add frontend/pages/index.html frontend/styles/base.css frontend/js/runner/runner-controller.js tests-e2e/reference.spec.js
  git commit -m "feat: focus practice runner on current stage"
  ```

### Task 4: Extract a dedicated teacher workspace while preserving the review API

**Files:**
- Create: `frontend/pages/teacher.html`
- Create: `frontend/styles/pages/teacher.css`
- Create: `frontend/js/teacher/teacher-view.js`
- Create: `frontend/js/teacher/teacher-page.js`
- Modify: `src/trainer/main.py`
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/account/account-controller.js`
- Modify: `frontend/js/account/account-auth-controller.js`
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/js/account/account-view.js`
- Modify: `frontend/js/account/account-reviews-controller.js`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/account-workflows.spec.js`
- Modify: `tests-e2e/student-teacher.spec.js`
- Modify: `tests-e2e/reference.spec.js`

**Interfaces:**
- `GET /teacher.html` serves a static page through the existing safe allowlist in `src/trainer/main.py`; no catch-all or unsafe filesystem lookup is added.
- `bootstrapTeacherWorkspace()` in `frontend/js/teacher/teacher-page.js` calls existing `/api/auth/me`, `/api/teacher/review-requests`, `/api/teacher/review-requests/{id}`, and `/api/teacher/review-requests/{id}/scores` contracts only.
- `teacherQueueMarkup(requests, selectedId)` and `teacherDetailMarkup(request)` in `frontend/js/teacher/teacher-view.js` output escaped queue/detail HTML, audio URLs from API payloads, existing score fields, and no text-comment inputs.
- The learner page owns student review history only. It no longer creates, loads, or closes `#teacherModal`.

- [ ] **Step 1: Write failing markup tests for the separate queue and detail renderers**

  In `tests-js/unit/views.test.js`, import the new teacher view module and add fixtures proving that:

  - queue rows escape `studentName` and `studentEmail`, expose a selected row marker, status, request type, selected tasks, and date;
  - a detail includes the existing private audio URL, score controls from `reviewFields`, and immutable material photos;
  - the generated HTML has no `textarea`, “Комментарий”, “Группа”, “Срок”, or assignment-control markup.

  ```js
  const queue = teacherQueueMarkup([{ id: 3, studentName: "<b>Анна</b>", studentEmail: "a@example.test", kind: "task", status: "queued", tasks: [2], submittedAt: 1780000000 }], 3);
  assert.match(queue, /data-review-request-id="3"/);
  assert.match(queue, /&lt;b&gt;Анна&lt;\/b&gt;/);
  assert.doesNotMatch(queue, /textarea|Комментарий/);
  ```

- [ ] **Step 2: Run the focused renderer test and verify RED**

  Run: `npm test -- --test-name-pattern='separate queue|teacher workspace' tests-js/unit/views.test.js`

  Expected: FAIL because the new teacher view module does not exist.

- [ ] **Step 3: Add the static page and safe route**

  Create `frontend/pages/teacher.html` with:

  - the common brand and a return link to `index.html`;
  - a `<main>` labelled “Кабинет преподавателя”;
  - a desktop-local navigation with Queue, Reviewed, Materials, and Profile labels, while only Queue/Reviewed filtering and Materials’ existing editor link are interactive in this iteration;
  - a semantic `<form id="teacherReviewFilters">` with `#reviewStudentFilter`, `#reviewTaskFilter`, `#reviewStatusFilter`, and `#reviewDateFilter`, retaining the existing filter meanings;
  - an empty-state/live-message region, queue list, and selected-review region;
  - no account/auth dialog markup, no group/assignment copy, and no comment field.

  Add `teacher.html` to the `pages` allowlist in `src/trainer/main.py`. Create `frontend/styles/pages/teacher.css` for the workspace grid, selected queue row, review split pane, score card, and a single-column mobile fallback. Use base color variables and `min-height: 44px` controls rather than duplicating base tokens.

- [ ] **Step 4: Implement page-only queue loading, selection, and score saving**

  Create `frontend/js/teacher/teacher-view.js` with the escaping render functions defined in Step 1. Move/reuse only presentation helpers from `frontend/js/account/account-view.js`; leave `studentReviewRequestsMarkup` in its original module for the learner page.

  Create `frontend/js/teacher/teacher-page.js` that:

  1. calls `/api/auth/me` at startup and redirects non-teachers to `index.html?account=1` without exposing queue data;
  2. loads the filtered list using the same `student`, `task`, `status`, `submittedFrom`, and `submittedBefore` query parameters as the previous controller;
  3. selects the first queued request when no explicit selection remains, fetches its detail only after selection, and clears the detail on an empty list;
  4. handles a queue-row click by fetching one detail, updates `aria-current`/selected state, and does not fetch another student’s history unless the user selects their request;
  5. submits `collectReviewScores(form, tasks)` to the existing PUT score endpoint, shows the returned total with the existing toast/message pattern, then refreshes list and detail;
  6. treats API errors as text in the live message region and leaves the user’s selected request stable when possible.

  Remove the teacher list/detail renderer exports and `createAccountReviewsController` use from the learner account controller. Delete `#teacherModal` markup and its app-level event handlers. Replace `#teacherCabinetBtn` with an ordinary `teacher.html` link/button that `account-auth-controller.js` only shows to a teacher. Preserve the learner account dialog, student review history, password reset, and progress dialog behavior.

- [ ] **Step 5: Add browser tests for teacher access and score-only review**

  In `tests-e2e/account-workflows.spec.js`, update the authenticated owner assertion to follow the teacher cabinet link and expect `/teacher.html`, the heading, the materials editor link, and no dialog/modal role around the workspace.

  In `tests-e2e/student-teacher.spec.js`, update the teacher-side checks to visit `teacher.html`; submit a student request through the existing helper; assert a queue row appears, select it, assert its audio and material snapshot appear, save scores, and assert the reviewed total appears. Keep the existing assertion that no comment endpoint or textarea is introduced.

  In `tests-e2e/reference.spec.js`, add `teacher.html` to the shared static-page header/footer check only if the page intentionally includes both shared elements; otherwise add a targeted availability/access test instead of asserting a false shared layout contract.

- [ ] **Step 6: Run focused unit, API-flow, and browser tests and verify GREEN**

  Run: `npm test -- --test-name-pattern='teacher workspace|review queue' tests-js/unit/views.test.js`

  Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest`

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/account-workflows.spec.js tests-e2e/student-teacher.spec.js`

  Expected: PASS. A non-teacher cannot use the page, an owner can review exactly the existing submitted data, and saving scores continues to update the student-visible reviewed state.

- [ ] **Step 7: Commit the teacher workspace extraction**

  ```bash
  git add src/trainer/main.py frontend/pages/teacher.html frontend/styles/pages/teacher.css frontend/js/teacher frontend/pages/index.html frontend/js/account/account-controller.js frontend/js/account/account-auth-controller.js frontend/js/runner/app.js frontend/js/account/account-view.js frontend/js/account/account-reviews-controller.js tests-js/unit/views.test.js tests-e2e/account-workflows.spec.js tests-e2e/student-teacher.spec.js tests-e2e/reference.spec.js
  git commit -m "feat: move teacher reviews into workspace"
  ```

### Task 5: Integrate responsive/accessibility checks and remove obsolete UI paths

**Files:**
- Modify: `frontend/styles/base.css`
- Modify: `frontend/styles/pages/teacher.css`
- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/runner/app.js`
- Modify: `tests-e2e/reference.spec.js`
- Modify: `tests-e2e/account-workflows.spec.js`
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`

**Interfaces:**
- The public student flow still begins at `/`, and teacher review begins at `/teacher.html` for the configured owner.
- Account, progress, and password-reset dialogs retain their existing `openModal`/`closeModal` focus behavior; teacher workspace navigation does not use those functions.
- No remaining `teacherModal`, `teacherCloseBtn`, or teacher-modal-only controller code is referenced from learner JavaScript.

- [ ] **Step 1: Add failing regression checks for removal and narrow-screen ergonomics**

  Add Playwright assertions that `/` has no `#teacherModal`, `/teacher.html` has no `.modal-backdrop`, both a 390px learner runner and a 390px teacher queue have `document.documentElement.scrollWidth <= window.innerWidth`, and the primary controls on those screens have at least 44px minimum height.

  ```js
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/teacher.html");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await expect(page.locator("#teacherReviewFilters button")).toHaveCSS("min-height", "44px");
  ```

- [ ] **Step 2: Run the targeted checks and verify RED**

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python npx playwright test tests-e2e/reference.spec.js tests-e2e/account-workflows.spec.js --grep 'narrow|teacher workspace'`

  Expected: FAIL until obsolete modal wiring is fully removed and responsive rules cover the new workspace.

- [ ] **Step 3: Remove dead teacher-modal styles/listeners and tune responsive behavior**

  Remove obsolete teacher-modal CSS selectors and any `teacherCloseBtn`, `teacherModal`, `loadTeacherReviewRequests`, `showStudentReviewHistory`, or `saveReviewScores` listener/import that remains in `frontend/js/runner/app.js` after Task 4. Keep shared modal code only for auth and progress.

  Ensure `frontend/styles/base.css` has no desktop-only grid that causes the learner runner, result view, or home task choice to overflow under 700px. In `teacher.css`, collapse navigation, filter controls, queue rows, detail/audio, and score fields to one readable column below the breakpoint. Add focus-visible outlines only where base styles do not already provide a clearly visible equivalent.

  Update `README.md` and `DEVELOPMENT.md` with the teacher workspace URL and explain that `TRAINER_OWNER_EMAIL` is still required for teacher access; do not add deployment, credentials, or API changes.

- [ ] **Step 4: Run all mandatory validation**

  Run: `PYTHONPATH=src make check PYTHON=.venv/bin/python NPM=npm`

  Run: `PYTHONPATH=src E2E_PYTHON=.venv/bin/python make test-e2e PYTHON=.venv/bin/python NPM=npm`

  Expected: both commands PASS with the full JavaScript, Python unit/integration, lint, and Playwright suites.

- [ ] **Step 5: Manually verify the three agreed modes in a browser**

  Run the local application with `TRAINER_OWNER_EMAIL` set. Verify:

  1. learner: horizontal motto, material selection, task 2 images after selection/answer, task 3 paired images, completed-result review chooser;
  2. student: voluntary request submission and score visibility after review;
  3. owner: direct teacher workspace, filters, queue selection, audio playback, score save, and no text-comment field.

  Capture only actual regressions as follow-up bugs; do not widen scope with new product features during this pass.

- [ ] **Step 6: Commit the responsive/accessibility pass**

  ```bash
  git add frontend/styles/base.css frontend/styles/pages/teacher.css frontend/pages/index.html frontend/js/runner/app.js tests-e2e/reference.spec.js tests-e2e/account-workflows.spec.js README.md DEVELOPMENT.md
  git commit -m "fix: polish responsive review and practice flows"
  ```

## Plan self-review

- **Spec coverage:** Task 1 covers the visual language, horizontal motto, no pinyin, no biography block, and direct practice selection. Tasks 2–3 cover persistent task photographs, focused practice, timing, recording state, and responsive behavior. Task 4 covers the full-page score-only teacher workspace. Task 5 covers keyboard/mobile/reduced-motion boundaries, documentation, regression removal, and mandatory checks.
- **No out-of-scope expansion:** all calls reuse current review APIs, scoring, material JSON, and persistence. No assignment/group/comment/speech-evaluation feature is planned.
- **Type/interface consistency:** the learner continues using existing runner IDs and `taskMarkup` signature; the new teacher page owns only existing API routes and calls `collectReviewScores(form, tasks)` already used by the former modal controller.
- **Placeholder scan:** no implementation step relies on unspecified functions or deferred behavior.
