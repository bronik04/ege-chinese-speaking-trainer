# Attempt Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать авторизованному ученику выбрать в истории две завершённые попытки с одинаковыми заданиями и сопоставить их оценки и аудиозаписи на отдельной странице.

**Architecture:** Существующий `createHistoryPageController` остаётся единственной клиентской границей загрузки прогресса, личных записей и разборов. Новые чистые модули отвечают отдельно за выбор совместимых попыток, сбор модели сравнения и безопасный HTML; `compare.html` только связывает эти части и не добавляет API или состояние БД.

**Tech Stack:** Vanilla JavaScript ES modules, HTML/CSS, Node test runner, Playwright, FastAPI static page allowlist.

**Spec:** `docs/superpowers/specs/2026-09-11-attempt-comparison-and-variant-preview-design.md`

## Global Constraints

- Полноценное сравнение доступно только пользователю с ролью `student`.
- Сравниваются ровно две завершённые, не recovered попытки с одинаковым отсортированным набором заданий.
- Варианты материалов могут различаться; название каждого варианта остаётся видимым.
- Последний reviewed-разбор выбирается по `reviewedAt`, затем `submittedAt`, затем `id`.
- Personal recording имеет приоритет над копией review recording для той же позиции.
- Ошибка одного источника не скрывает успешно загруженные источники; retry остаётся раздельным.
- Новые API, таблицы, миграции и поля progress V2 запрещены.
- Сетевые строки экранируются; audio URL проходят существующие same-origin allowlists.
- UI должен помещаться в 360 px и иметь touch targets не менее 44 px.
- Изменение UI требует JavaScript unit-тестов и Playwright-тестов; финальные проверки — `make check` и `make test-e2e`.

---

## File Structure

- Create `frontend/js/history/attempt-comparison.js`: чистые правила eligibility, совместимости, выбора, score/audio alignment.
- Create `frontend/js/history/attempt-comparison-view.js`: безопасный HTML страницы сравнения и названия критериев.
- Create `frontend/js/history/attempt-comparison-page.js`: URL selection, reuse history controller, loading/error/retry wiring.
- Modify `frontend/js/history/history-controller.js`: expose per-source loading state without changing existing consumers.
- Modify `frontend/js/history/history-view.js`: optional comparison selector outside `<summary>` semantics.
- Modify `frontend/js/history/history-page.js`: удержание двух выбранных run IDs и переход на compare page.
- Modify `frontend/pages/history.html`: comparison action bar.
- Create `frontend/pages/compare.html`: dedicated comparison shell.
- Modify `frontend/styles/pages/history.css`: selection controls and action bar.
- Create `frontend/styles/pages/attempt-comparison.css`: responsive two-column comparison layout.
- Modify `src/trainer/main.py`: allowlist `compare.html`.
- Create `tests-js/unit/attempt-comparison.test.js`: domain/model tests.
- Create `tests-js/unit/attempt-comparison-view.test.js`: escaping and empty-state tests.
- Modify `tests-js/unit/history-page.test.js`: source-loading lifecycle contract.
- Modify `tests-js/unit/history-view.test.js`: optional selector markup contract.
- Modify `tests/integration/test_asgi.py`: static page/cache headers.
- Modify `tests-e2e/history.spec.js`: selection behavior and guest/teacher restrictions.
- Create `tests-e2e/attempt-comparison.spec.js`: end-to-end comparison and partial failures.
- Modify `README.md`: student comparison instructions.

### Task 1: Compatibility and two-attempt selection model

**Files:**
- Create: `frontend/js/history/attempt-comparison.js`
- Create: `tests-js/unit/attempt-comparison.test.js`

**Interfaces:**
- Consumes: history entries returned by `buildHistoryTimeline({ runs, recordings, reviewRequests })`.
- Produces: `isSelectableAttempt(entry): boolean`, `sameTaskSet(left, right): boolean`, and `buildComparisonSelection(entries, selectedRunIds): { selectedIds, choices, canCompare }`.
- `choices` items are `{ runId, selected, selectable, reason }`; `reason` is `null`, `"incomplete"`, or `"different_tasks"`.

- [ ] **Step 1: Write failing eligibility and compatibility tests**

```js
import { buildComparisonSelection, isSelectableAttempt, sameTaskSet } from "../../frontend/js/history/attempt-comparison.js";

test("only completed concrete runs can be selected", () => {
  assert.equal(isSelectableAttempt(entry("done", [2], "completed")), true);
  assert.equal(isSelectableAttempt(entry("stopped", [2], "interrupted")), false);
  assert.equal(isSelectableAttempt({ ...entry("recovered", [2], "completed"), recovered: true }), false);
});

test("task compatibility ignores variant and task order but not task set", () => {
  assert.equal(sameTaskSet(entry("a", [3, 1, 2]), entry("b", [1, 2, 3])), true);
  assert.equal(sameTaskSet(entry("a", [2]), entry("b", [3])), false);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test tests-js/unit/attempt-comparison.test.js`

Expected: FAIL because `frontend/js/history/attempt-comparison.js` does not exist.

- [ ] **Step 3: Implement the minimal pure selection contract**

```js
const taskKey = entry => [...new Set(entry?.run?.tasks || [])].sort((a, b) => a - b).join(",");

export const isSelectableAttempt = entry => Boolean(
  entry?.runId && !entry.recovered && entry.run?.status === "completed",
);

export const sameTaskSet = (left, right) => taskKey(left) === taskKey(right);

export function buildComparisonSelection(entries, selectedRunIds = []) {
  const byId = new Map(entries.map(item => [item.runId, item]));
  const selectedIds = [...new Set(selectedRunIds)]
    .filter(id => isSelectableAttempt(byId.get(id)))
    .slice(0, 2);
  const anchor = byId.get(selectedIds[0]);
  const choices = entries.map(item => {
    const selected = selectedIds.includes(item.runId);
    const eligible = isSelectableAttempt(item);
    const compatible = !anchor || sameTaskSet(anchor, item);
    return {
      runId: item.runId,
      selected,
      selectable: eligible && compatible,
      reason: !eligible ? "incomplete" : compatible ? null : "different_tasks",
    };
  });
  return { selectedIds, choices, canCompare: selectedIds.length === 2 };
}
```

- [ ] **Step 4: Add selection normalization tests**

Cover duplicate/unknown IDs, maximum two IDs, disabled incompatible choices, and removing the first selection so all completed choices become selectable again.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `node --test tests-js/unit/attempt-comparison.test.js`

Expected: all selection tests PASS.

- [ ] **Step 6: Commit the selection model**

```bash
git add frontend/js/history/attempt-comparison.js tests-js/unit/attempt-comparison.test.js
git commit -m "feat: model comparable training attempts"
```

### Task 2: Score and recording comparison model

**Files:**
- Modify: `frontend/js/history/attempt-comparison.js`
- Modify: `tests-js/unit/attempt-comparison.test.js`

**Interfaces:**
- Consumes: two compatible history entries and exact `leftRunId`, `rightRunId`.
- Produces: `buildAttemptComparison(entries, leftRunId, rightRunId): { left, right, tasks }`.
- `left` and `right` are `{ runId, variantId, variantLabel, completedAt, tasks }` and preserve the URL-selected side order.
- Each task is `{ number, left: side, right: side, delta }`; each side is `{ score, recordings }`.
- `score` is `null` or `{ total, maximum, criteria }`; `recordings` contains fixed ordered slots `{ key, label, recording, source }`.
- Throws `AttemptComparisonError` with code `attempt_missing`, `attempt_ineligible`, or `attempt_incompatible`.

- [ ] **Step 1: Write failing reviewed-score ordering test**

```js
test("comparison uses the latest reviewed item for each task", () => {
  const comparison = buildAttemptComparison([
    comparisonEntry("old", 4, { reviewedAt: 100, id: 1 }),
    comparisonEntry("new", 6, { reviewedAt: 200, id: 2 }),
  ], "old", "new");
  assert.deepEqual(comparison.tasks[0].right.score, {
    total: 6,
    maximum: 7,
    criteria: { content: 3, organization: 2, language: 1 },
  });
  assert.equal(comparison.tasks[0].delta, 2);
});
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `node --test tests-js/unit/attempt-comparison.test.js`

Expected: FAIL because `buildAttemptComparison` is not exported.

- [ ] **Step 3: Implement deterministic reviewed item lookup and delta**

Use `entry.run.tasks` as the authoritative task set. Implement helpers that filter `status === "reviewed"`, find the requested task item, sort by numeric `reviewedAt || 0`, `submittedAt || 0`, `id || 0`, and accept a score only when total/maximum are finite non-negative integers and `scores` is an object. Return `delta` only when both maxima are equal.

- [ ] **Step 4: Write failing recording alignment test**

```js
test("personal audio wins and missing slots stay aligned", () => {
  const task = buildAttemptComparison(entriesWithTaskOneAudio(), "left", "right").tasks[0];
  assert.deepEqual(task.left.recordings.map(slot => slot.key), ["1:1", "1:2", "1:3", "1:4", "1:5"]);
  assert.equal(task.left.recordings[0].source, "personal");
  assert.equal(task.left.recordings[1].source, "review");
  assert.equal(task.right.recordings[4].recording, null);
});
```

- [ ] **Step 5: Implement fixed slot alignment**

Use slots `[1,2,3,4,5]` for task 1 and `[1]` for tasks 2 and 3. Normalize personal fields from `taskNumber/questionNumber`; normalize review fields from parent `item.task` and `question_number ?? questionNumber ?? 1`. Fill personal first and review only when the slot is empty.

- [ ] **Step 6: Add validation and error tests**

Assert exact error codes for missing, interrupted/recovered, and mismatched task-set pairs; assert that a queued request newer than a reviewed request does not hide the reviewed score; assert `delta === null` for unequal maxima or missing scores.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `node --test tests-js/unit/attempt-comparison.test.js`

Expected: all model tests PASS.

- [ ] **Step 8: Commit comparison assembly**

```bash
git add frontend/js/history/attempt-comparison.js tests-js/unit/attempt-comparison.test.js
git commit -m "feat: assemble attempt score and audio comparison"
```

### Task 3: Two-attempt selection on the history page

**Files:**
- Modify: `frontend/js/history/history-view.js`
- Modify: `frontend/js/history/history-page.js`
- Modify: `frontend/pages/history.html`
- Modify: `frontend/styles/pages/history.css`
- Modify: `tests-js/unit/history-view.test.js`
- Modify: `tests-e2e/history.spec.js`

**Interfaces:**
- Consumes: `buildComparisonSelection(entries, selectedRunIds)` from Task 1.
- Produces: optional `comparison` argument to `historyTimelineMarkup(entries, { comparison })` and navigation to `compare.html?left=...&right=...`.
- Existing callers without `comparison` must render byte-for-byte compatible history details except for unavoidable formatting.

- [ ] **Step 1: Write a failing view test for external selection controls**

```js
const comparison = {
  selectedIds: ["run-a"],
  canCompare: false,
  choices: [{ runId: "run-a", selected: true, selectable: true, reason: null }],
};
const markup = historyTimelineMarkup([completedEntry], { comparison });
assert.match(markup, /data-compare-run="run-a"/);
assert.match(markup, /aria-pressed="true"/);
assert.doesNotMatch(markup, /<summary[^>]*>.*<button/s);
```

- [ ] **Step 2: Run view tests and verify RED**

Run: `node --test tests-js/unit/history-view.test.js`

Expected: FAIL because the optional comparison UI is not rendered.

- [ ] **Step 3: Render a sibling selection button for eligible student entries**

When the optional comparison model is present, wrap every completed concrete entry in `.history-entry-wrap`, place `.history-compare-toggle` before `<details>`, and include escaped `data-compare-run`, `aria-pressed`, label `Выбрать для сравнения`/`Выбрано`. Incompatible choices remain visible with a disabled selector and visible helper text for `different_tasks`; incomplete/recovered entries get no selector. Without the optional model, preserve existing markup.

- [ ] **Step 4: Add the comparison action bar shell**

Add to `history.html` before `#historyTimeline`:

```html
<section class="history-compare-bar hidden" id="historyCompareBar" aria-live="polite">
  <span id="historyCompareStatus">Выберите две завершённые попытки</span>
  <button class="primary-btn" id="historyCompareBtn" type="button" disabled>Сравнить</button>
</section>
```

- [ ] **Step 5: Wire persistent-in-render selection state**

Keep `selectedRunIds` in `history-page.js`. On every student render, build the timeline, normalize selection, render the optional controls and update the bar. Event delegation on `[data-compare-run]` toggles one ID; clicking `#historyCompareBtn` navigates with both values encoded through `URLSearchParams`. Guest/teacher renders clear selection and hide the bar.

- [ ] **Step 6: Add CSS for selected, disabled, focus and mobile states**

Ensure selector and compare button are at least 44 px, selected state has text/icon in addition to color, the wrapper retains existing card shadow/radius, and 360 px has no horizontal overflow.

- [ ] **Step 7: Write Playwright tests for selection constraints**

Extend student fixtures to include two task-2 completed runs, one task-3 completed run, and one interrupted task-2 run. Assert only completed concrete runs get controls; after selecting task 2, task 3 disables; selecting the second task-2 run enables compare; URL contains the two exact run IDs. Add guest and teacher assertions that `#historyCompareBar` and `[data-compare-run]` are absent/hidden.

- [ ] **Step 8: Run focused unit and E2E tests**

Run: `node --test tests-js/unit/history-view.test.js tests-js/unit/attempt-comparison.test.js`

Run: `npx playwright test tests-e2e/history.spec.js`

Expected: all focused tests PASS.

- [ ] **Step 9: Commit history selection UI**

```bash
git add frontend/js/history/history-view.js frontend/js/history/history-page.js frontend/pages/history.html frontend/styles/pages/history.css tests-js/unit/history-view.test.js tests-e2e/history.spec.js
git commit -m "feat: select comparable attempts from history"
```

### Task 4: Dedicated comparison page and safe view

**Files:**
- Create: `frontend/js/history/attempt-comparison-view.js`
- Create: `tests-js/unit/attempt-comparison-view.test.js`
- Create: `frontend/js/history/attempt-comparison-page.js`
- Create: `frontend/pages/compare.html`
- Create: `frontend/styles/pages/attempt-comparison.css`
- Modify: `frontend/js/history/history-controller.js`
- Modify: `tests-js/unit/history-page.test.js`
- Modify: `src/trainer/main.py:199-207`
- Modify: `tests/integration/test_asgi.py:36-55`

**Interfaces:**
- Consumes: `createHistoryPageController`, `buildHistoryTimeline`, and `buildAttemptComparison`.
- Produces: `attemptComparisonMarkup(comparison): string`, `comparisonPageStateMarkup(state): string`, and a static `compare.html` route.
- Audio allowlists: personal IDs use `personalRecordingStreamUrl`; review URLs must match `/api/review-recordings/<positive integer>`.
- `createHistoryPageController` additionally publishes `sourceLoading: { progress, recordings, reviews }`; existing consumers may ignore it.

- [ ] **Step 1: Write failing safe-view tests**

```js
test("comparison view aligns scores and audio without trusting network strings", () => {
  const html = attemptComparisonMarkup(comparisonFixture({ variantLabel: "<script>bad</script>" }));
  assert.match(html, /Задание 2/);
  assert.match(html, /\+2 балла/);
  assert.match(html, /\/api\/personal-recordings\/7/);
  assert.match(html, /\/api\/review-recordings\/8/);
  assert.doesNotMatch(html, /<script>|javascript:/);
});
```

- [ ] **Step 2: Run view tests and verify RED**

Run: `node --test tests-js/unit/attempt-comparison-view.test.js`

Expected: FAIL because the view module does not exist.

- [ ] **Step 3: Implement score, criteria, delta and paired-audio markup**

Map criteria keys to existing Russian labels (`content`, `organization`, `language`, and task-1 question keys), fall back to an escaped key for unknown future criteria, show exact empty states, and ensure color-independent delta text. Render `<audio preload="none" controls>` only for valid personal IDs or valid review URLs.

- [ ] **Step 4: Create the comparison HTML/CSS shell**

The page contains shared navigation, a back link to `history.html`, focusable `#comparisonTitle`, `#comparisonStatus`, `#comparisonSourceErrors`, and `#comparisonContent`. CSS uses two aligned columns on desktop and a stacked but labeled left/right sequence on mobile; no content depends on color alone.

- [ ] **Step 5: Add static route coverage before implementing the allowlist**

Extend `test_health_static_and_private_data_boundary` with `/compare.html`, `/js/history/attempt-comparison-page.js`, and `/styles/pages/attempt-comparison.css`. Run:

`.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary -v`

Expected: FAIL with 404 for `/compare.html`.

- [ ] **Step 6: Add `compare.html` to the FastAPI page allowlist**

Modify `src/trainer/main.py` `pages` set, rerun the integration test, and expect PASS with `Cache-Control: no-cache` and `X-Content-Type-Options: nosniff`.

- [ ] **Step 7: Expose and test source-loading lifecycle**

Add `sourceLoading` to the history controller's public state. Set all student sources pending before synchronization, clear each source on success/failure, set just one source pending before `retry(source)`, and reset all flags for guest/teacher/auth-expired states. Extend `tests-js/unit/history-page.test.js` to assert initial, partial-completion, failure, retry and stale-account transitions.

- [ ] **Step 8: Wire the comparison page controller**

Parse exact `left` and `right` query values once. Instantiate `createHistoryPageController({ render })`; on each render build entries, enforce `state.mode === "student"`, and wait until `sourceLoading.progress === false` before treating a missing run as terminal. Once the pair exists, call `buildAttemptComparison` while independently showing pending/error states for recordings and reviews. Render partial source errors with `data-retry-source`, and delegate retries to `controller.retry(source)`. Clear content for guest/teacher/auth-expired state before rendering their access message. Focus `#comparisonTitle` after the first terminal success or error state.

- [ ] **Step 9: Run focused tests and lint**

Run: `node --test tests-js/unit/attempt-comparison.test.js tests-js/unit/attempt-comparison-view.test.js tests-js/unit/history-page.test.js`

Run: `npm run lint:js`

Expected: PASS.

- [ ] **Step 10: Commit the comparison page**

```bash
git add frontend/js/history/attempt-comparison-view.js frontend/js/history/attempt-comparison-page.js frontend/js/history/history-controller.js frontend/pages/compare.html frontend/styles/pages/attempt-comparison.css tests-js/unit/attempt-comparison-view.test.js tests-js/unit/history-page.test.js src/trainer/main.py tests/integration/test_asgi.py
git commit -m "feat: show side-by-side attempt comparison"
```

### Task 5: End-to-end comparison, partial retry, accessibility and docs

**Files:**
- Create: `tests-e2e/attempt-comparison.spec.js`
- Modify: `tests-e2e/history.spec.js`
- Modify: `README.md:5-60`

**Interfaces:**
- Consumes: completed comparison flow from Tasks 1-4.
- Produces: regression coverage and user-facing instructions; no new runtime API.

- [ ] **Step 1: Add the complete student comparison E2E scenario**

Route auth/progress/personal-recordings/review-requests with two task-2 runs. Give both reviewed scores with the same maximum, personal audio for the first run, review fallback audio for the second, select both from history, and assert comparison headers, `+2 балла`, criterion values and two valid audio sources.

- [ ] **Step 2: Add partial-error retry and missing-data scenarios**

Make the first recordings request return 503 while reviews succeed. Assert scores and recording error coexist; retry only `[data-retry-source="recordings"]`; fulfill the second request and assert audio appears without reloading progress/reviews. In a separate case omit a score and one audio slot and assert exact empty-state copy.

- [ ] **Step 3: Add access, URL and stale-account scenarios**

Assert guest and teacher pages never render comparison data. Assert missing/unknown/incompatible URL run IDs render their stable error state. Delay one student source, expire auth to guest, release the delayed response, and assert the previous student's comparison never reappears.

- [ ] **Step 4: Add mobile and keyboard checks**

At 360×800 assert no horizontal overflow, every retry/back/audio/select action is reachable, and short-side touch targets for custom buttons are at least 44 px. Verify focus reaches the comparison title after load and remains visibly outlined on actions.

- [ ] **Step 5: Update README**

Add comparison to «Что доступно» and document: sign in, open History, select two compatible completed attempts, compare latest teacher score and paired recordings; explain missing-score/expired-audio states.

- [ ] **Step 6: Run all focused tests**

Run: `node --test tests-js/unit/attempt-comparison.test.js tests-js/unit/attempt-comparison-view.test.js tests-js/unit/history-view.test.js`

Run: `npx playwright test tests-e2e/history.spec.js tests-e2e/attempt-comparison.spec.js`

Expected: PASS.

- [ ] **Step 7: Run mandatory verification**

Run: `make check`

Run: `make test-e2e`

Expected: both exit 0 with no skipped comparison tests.

- [ ] **Step 8: Commit documentation and final coverage**

```bash
git add README.md tests-e2e/history.spec.js tests-e2e/attempt-comparison.spec.js
git commit -m "test: cover student attempt comparison"
```

- [ ] **Step 9: Request code review before integration**

Review the complete branch against the spec, with particular attention to cross-account stale responses, reviewed-request ordering, duplicate audio fallback, escaping, and 360 px layout. Resolve all Critical/Important findings and rerun mandatory verification before offering merge/PR/keep options.
