# Unified Student History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three separate student-facing history surfaces with one dedicated page that groups attempts, personal recordings, expiry dates, and teacher reviews by run.

**Architecture:** Keep progress, personal recordings, and review requests as independent backend sources. Publish only `runId` from the stored review-request run snapshot, then merge the three sources in a pure browser model. A page controller owns authentication, progress synchronization, partial-source errors, retry actions, and stale-response protection; a separate view module owns escaped HTML.

**Tech Stack:** FastAPI, SQLite, vanilla ES modules, Node test runner, Playwright, HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-09-09-unified-student-history-design.md`

## Global Constraints

- Work sequentially in the current isolated worktree; the user explicitly chose no subagent executors.
- Do not add a history endpoint, table, or migration.
- Do not change teacher review-request payloads or teacher-cabinet behavior.
- Preserve background personal-recording uploads and review-request submission from the result screen.
- Never stage `.superpowers/`; it contains local design-session artifacts.
- Follow test-first order for every behavior change.
- Run `make check` and `make test-e2e` from a clean working tree before claiming completion.

---

## Task 1: Expose a safe `runId` in the student review-request response

**Files:**

- Modify: `src/trainer/infrastructure/database/queries/review_requests.py`
- Modify: `tests/integration/test_api_flows.py`

- [x] **Step 1: Add failing integration assertions for canonical and legacy rows**

Extend `test_review_request_persists_canonical_run_and_legacy_rows_remain_listable` so it first lists the canonical row and expects its run identifier, then corrupts the stored snapshot and expects `null` without losing the row:

```python
status, canonical_list, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
self.assertEqual(status, 200, canonical_list)
canonical_item = next(item for item in canonical_list["requests"] if item["id"] == request_id)
self.assertEqual(canonical_item["runId"], "canonical-storage")

with runtime.connect() as database:
    database.execute("UPDATE review_requests SET run_json=? WHERE id=?", ('{"legacy":true}', request_id))

status, legacy_list, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
self.assertEqual(status, 200, legacy_list)
legacy_item = next(item for item in legacy_list["requests"] if item["id"] == request_id)
self.assertIsNone(legacy_item["runId"])
```

Also assert in `test_student_queues_single_task_for_owner_review` that the student item contains `runId == "review-task-2"` while the corresponding teacher item does not contain `runId`.

- [x] **Step 2: Run the focused test and confirm the red result**

Run:

```bash
.venv/bin/python -m unittest tests.integration.test_api_flows.ApiFlowTest.test_review_request_persists_canonical_run_and_legacy_rows_remain_listable
```

Expected: failure because `runId` is absent.

- [x] **Step 3: Implement tolerant snapshot extraction only for the student list**

Add a private helper:

```python
def _run_id(run_json: str) -> str | None:
    try:
        run = json.loads(run_json)
    except (TypeError, ValueError):
        return None
    value = run.get("id") if isinstance(run, dict) else None
    return value if isinstance(value, str) and 1 <= len(value) <= 120 else None
```

Change only `student_review_requests` to select `run_json`, build the existing payload, and then set `payload["runId"] = _run_id(row["run_json"])`. Do not add `run_json` to either teacher query.

- [x] **Step 4: Run focused review-request tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.integration.test_api_flows.ApiFlowTest.test_review_request_persists_canonical_run_and_legacy_rows_remain_listable \
  tests.integration.test_api_flows.ApiFlowTest.test_student_queues_single_task_for_owner_review
```

Expected: both pass; queued score-hiding assertions remain green.

- [x] **Step 5: Commit the API contract change**

```bash
git add src/trainer/infrastructure/database/queries/review_requests.py tests/integration/test_api_flows.py
git commit -m "feat: link student reviews to training runs"
```

---

## Task 2: Build the pure history aggregation model

**Files:**

- Create: `frontend/js/history/history-model.js`
- Create: `tests-js/unit/history-model.test.js`

- [x] **Step 1: Write failing model tests for all grouping rules**

Create fixtures containing:

- one completed run with two personal recordings and two review requests;
- an orphan personal recording;
- an orphan review request with a valid `runId`;
- two legacy review requests with `runId: null`;
- identical timestamps requiring deterministic key ordering.

Test the public interface:

```javascript
const entries = buildHistoryTimeline({ runs, recordings, reviewRequests });

assert.equal(entries[0].runId, "run-new");
assert.equal(entries.find(entry => entry.runId === "run-1").recordings.length, 2);
assert.equal(entries.find(entry => entry.runId === "run-1").reviewRequests.length, 2);
assert.equal(entries.find(entry => entry.runId === "run-1").latestReview.id, 12);
assert.equal(entries.filter(entry => entry.key.startsWith("review:")).length, 2);
assert.equal(entries.find(entry => entry.key === "run:orphan-audio").recovered, true);
```

Assert that caller-owned arrays and objects are not mutated.

- [x] **Step 2: Run the new unit test and confirm the red result**

Run:

```bash
node --test tests-js/unit/history-model.test.js
```

Expected: module-not-found failure.

- [x] **Step 3: Implement `buildHistoryTimeline`**

Use one `Map` and these stable keys:

```javascript
const runKey = runId => `run:${runId}`;
const recordingKey = recording => `recording:${recording.id}`;
const reviewKey = request => `review:${request.id}`;
```

Each returned entry has exactly:

```javascript
{
  key,
  runId,
  run,
  variantId,
  variantLabel,
  tasks,
  recordings,
  reviewRequests,
  latestReview,
  recovered,
  sortAt,
}
```

Rules:

- seed entries from progress runs;
- attach recordings by non-empty `runId`, otherwise use `recording:<id>`;
- attach reviews by non-empty `runId`, otherwise always use `review:<id>`;
- synthesize missing entries from the orphan object's variant/tasks/date;
- sort recordings by `taskNumber`, then `questionNumber`, then numeric `id`;
- sort reviews newest-first by `submittedAt`, falling back to numeric `id`;
- set `latestReview` to the first sorted review;
- sort entries by `sortAt` descending, then `key` ascending.

Normalize seconds from recording/review APIs and ISO strings from progress into comparable milliseconds. Invalid dates contribute `0`.

- [x] **Step 4: Run model tests and lint**

Run:

```bash
node --test tests-js/unit/history-model.test.js
npx eslint frontend/js/history/history-model.js tests-js/unit/history-model.test.js
```

Expected: both commands pass.

- [x] **Step 5: Commit the model**

```bash
git add frontend/js/history/history-model.js tests-js/unit/history-model.test.js
git commit -m "feat: aggregate student history by run"
```

---

## Task 3: Render accessible, escaped history cards

**Files:**

- Create: `frontend/js/history/history-view.js`
- Create: `tests-js/unit/history-view.test.js`

- [x] **Step 1: Write failing view tests**

Test these exports:

```javascript
historyTimelineMarkup(entries)
historyPageStateMarkup({ kind, message })
```

Assertions must cover:

- `<details>` and `<summary>` for every entry;
- full exam versus one-task labels;
- completed, interrupted, and recovered labels;
- recording count and latest review status in the summary;
- all recordings and all review requests in expanded content;
- score shown only for `reviewed` requests;
- upload-discard button only for `uploading` requests;
- expiry date and safe personal/review audio URLs;
- escaping hostile variant names and recording labels;
- no literal `<script>` or attribute injection.

- [x] **Step 2: Run the new view test and confirm the red result**

Run:

```bash
node --test tests-js/unit/history-view.test.js
```

Expected: module-not-found failure.

- [x] **Step 3: Implement view helpers with existing shared utilities**

Import `escapeHtml` and `formatHistoryDate` from `shared/progress.js`, and `personalRecordingStreamUrl` from `shared/api.js`. Permit review audio URLs only when they match `^/api/review-recordings/\\d+$`; otherwise omit the audio control.

Render each entry with this complete outer structure; the named helpers return the
escaped summary, recordings, and reviews fragments:

```html
<details class="history-entry" data-history-key="${escapeHtml(entry.key)}">
  <summary class="history-entry-summary">${historySummaryMarkup(entry)}</summary>
  <div class="history-entry-details">
    <section class="history-recordings">${recordingsMarkup(entry.recordings)}</section>
    <section class="history-reviews">${reviewRequestsMarkup(entry.reviewRequests)}</section>
  </div>
</details>
```

Use `data-discard-review-request="<numeric id>"` for the existing deletion action. Empty arrays produce calm explanatory text, not empty containers.

- [x] **Step 4: Run focused tests and lint**

Run:

```bash
node --test tests-js/unit/history-view.test.js
npx eslint frontend/js/history/history-view.js tests-js/unit/history-view.test.js
```

Expected: both pass.

- [x] **Step 5: Commit the view layer**

```bash
git add frontend/js/history/history-view.js tests-js/unit/history-view.test.js
git commit -m "feat: render unified history cards"
```

---

## Task 4: Add the dedicated page and guest flow

**Files:**

- Create: `frontend/pages/history.html`
- Create: `frontend/styles/pages/history.css`
- Create: `frontend/js/history/history-page.js`
- Modify: `src/trainer/main.py`
- Modify: `frontend/pages/index.html`
- Modify: `frontend/pages/variants.html`
- Modify: `frontend/pages/reference.html`
- Modify: `frontend/pages/variant-editor.html`
- Create: `tests-e2e/history.spec.js`

- [x] **Step 1: Write a failing guest browser test**

Seed `egeChineseProgressV2` with one completed local run, intercept protected history endpoints, and navigate to `/history.html`. Assert:

```javascript
await expect(page.getByRole("heading", { name: "Моя история" })).toBeVisible();
await expect(page.locator(".history-entry")).toHaveCount(1);
await expect(page.getByText("Открытый вариант 2026")).toBeVisible();
await expect(page.getByRole("link", { name: /войти/i })).toBeVisible();
await expect(page.getByRole("button", { name: /очистить историю/i })).toHaveCount(0);
expect(protectedRequests).toEqual([]);
```

Also assert that each public page has an `История` navigation link and that the history page marks it with `aria-current="page"`.

- [x] **Step 2: Run the guest test and confirm the red result**

Run:

```bash
npx playwright test tests-e2e/history.spec.js --grep "guest"
```

Expected: `/history.html` returns 404.

- [x] **Step 3: Add the page shell and static route**

Add `"history.html"` to the `pages` set in `src/trainer/main.py`.

Build `history.html` with existing fonts/base styles, `history.css`, the common header/footer, and these stable nodes:

```html
<main class="app-shell history-shell">
  <section class="history-hero">
    <div><p class="eyebrow">Личный прогресс</p><h1>Моя история</h1></div>
    <div><b id="historyCount">0 попыток</b><p id="historyStatus" aria-live="polite">Загружаем историю…</p></div>
  </section>
  <section class="history-notice hidden" id="historyNotice"></section>
  <section class="history-source-errors hidden" id="historySourceErrors" aria-live="polite"></section>
  <section class="history-timeline" id="historyTimeline"></section>
</main>
```

Every public header receives `<a class="header-link" href="history.html">История</a>` in the same position between `Варианты` and `Справочник`.

- [x] **Step 4: Implement the guest-only first slice of `history-page.js`**

On initialization:

1. request `/api/auth/me`;
2. if the response is 401, load `progressStorageKeys()` via `loadLocalProgress`;
3. never call `/api/progress`, `/api/personal-recordings`, or `/api/student/review-requests` for a guest;
4. render `buildHistoryTimeline({ runs: progress.runs, recordings: [], reviewRequests: [] })`;
5. show a sign-in link to `index.html?account=1` and explain that an account synchronizes progress and preserves audio for its configured retention period;
6. if auth itself fails from the network, use the same guest-safe data but show that sign-in status could not be checked.

Import `../shared/site-shell.js` for the common account label/year behavior.

- [x] **Step 5: Style the page and accessible controls**

Use a single-column timeline; cards must not overflow at 360px. Ensure:

```css
.history-entry>summary{min-height:44px;cursor:pointer;list-style:none}
.history-entry>summary:focus-visible,
.history-retry:focus-visible{outline:3px solid rgba(201,162,39,.45);outline-offset:3px}
.history-entry audio{width:100%;max-width:560px}
```

Use the existing paper, hairline, crimson, gold, radius, and shadow variables. Do not copy modal-specific styles.

- [x] **Step 6: Run guest tests and static-route integration tests**

Run:

```bash
npx playwright test tests-e2e/history.spec.js --grep "guest"
.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary
```

Expected: guest history and registered static-page behavior pass.

- [x] **Step 7: Commit the guest page**

```bash
git add src/trainer/main.py frontend/pages frontend/styles/pages/history.css frontend/js/history/history-page.js tests-e2e/history.spec.js
git commit -m "feat: add guest training history page"
```

---

## Task 5: Load and synchronize a student's full history

**Files:**

- Create: `frontend/js/history/history-controller.js`
- Modify: `frontend/js/history/history-page.js`
- Create: `tests-js/unit/history-page.test.js`
- Modify: `tests-e2e/history.spec.js`

- [x] **Step 1: Extract a testable page controller and write failing stale-response tests**

Export:

```javascript
export function createHistoryPageController({ request = api, discard = discardReviewRequest, storage = localStorage, render })
```

Its `load()` method increments a generation number. Tests supply delayed promises for two users and assert that resolving user A after user B never calls `render` with A's account-scoped data. A 401 during any protected request must trigger a new guest load and remove account data from the rendered state.

- [x] **Step 2: Write failing tests for synchronization and partial-source errors**

For a student, assert the controller:

- loads `progressStorageKeys(user.id)`;
- calls GET `/api/progress`;
- combines local and remote via `mergeProgress`;
- writes the merged document to the account-scoped current key;
- calls PUT `/api/progress` with `{ progress: merged }`;
- loads `/api/personal-recordings` and `/api/student/review-requests` in parallel;
- still renders attempts and reviews when recordings fail;
- still renders attempts and recordings when reviews fail;
- exposes source-specific retry callbacks.

For a teacher, assert that no student data endpoint is called and the render state contains the teacher-cabinet explanation.

- [x] **Step 3: Run controller tests and confirm the red result**

Run:

```bash
node --test tests-js/unit/history-page.test.js
```

Expected: missing controller behavior.

- [x] **Step 4: Implement the controller state machine**

Use this state shape between controller and DOM rendering:

```javascript
{
  mode: "guest" | "student" | "teacher",
  user,
  progress,
  recordings,
  reviewRequests,
  sourceErrors: { auth: null, progress: null, recordings: null, reviews: null },
}
```

For student progress, a failed GET keeps validated local progress and records a progress error. A failed PUT does not discard the merged local copy. Protected 401 responses call `loadGuest()` after invalidating the generation. All async continuations verify both generation and `user.id` before rendering.

- [x] **Step 5: Wire DOM rendering, retries, and uploading-request deletion**

The page-level renderer uses the model and view modules, updates count/status/notice, and creates one retry button per failed source with `data-retry-source="progress|recordings|reviews"`.

Use event delegation:

```javascript
historySourceErrors.addEventListener("click", event => {
  const button = event.target.closest("[data-retry-source]");
  if (button) controller.retry(button.dataset.retrySource);
});

historyTimeline.addEventListener("click", async event => {
  const button = event.target.closest("[data-discard-review-request]");
  if (button) await controller.discardReviewRequest(Number(button.dataset.discardReviewRequest));
});
```

`discardReviewRequest` calls the existing DELETE helper, reloads only reviews on success, preserves the card and shows an error on failure, and rejects non-integer IDs.

- [x] **Step 6: Add student and partial-failure browser coverage**

Use the existing register/recorder helpers to complete one task, wait for personal archival, send it for review, then open `/history.html`. Assert one expanded card contains the attempt, audio, expiry text, and review status. Add a routed failure for `/api/personal-recordings`, assert the run/review remain visible, release the route, click `Повторить`, and assert the audio appears.

Add an uploading review fixture through the API, click `Удалить незавершённую загрузку`, and assert the same card refreshes without that request.

- [x] **Step 7: Run focused controller and browser tests**

Run:

```bash
node --test tests-js/unit/history-page.test.js
npx playwright test tests-e2e/history.spec.js
```

Expected: all history tests pass.

- [x] **Step 8: Commit authenticated history**

```bash
git add frontend/js/history/history-page.js tests-js/unit/history-page.test.js tests-e2e/history.spec.js
git commit -m "feat: combine account history sources"
```

---

## Task 6: Remove the fragmented home-page history surfaces

**Files:**

- Modify: `frontend/pages/index.html`
- Modify: `frontend/js/runner/app.js`
- Modify: `frontend/js/account/account-auth-controller.js`
- Modify: `frontend/js/account/account-controller.js`
- Modify: `frontend/js/account/account-review-requests-controller.js`
- Modify: `frontend/js/account/account-personal-recordings-controller.js`
- Modify: `frontend/js/account/account-view.js`
- Modify: `frontend/styles/base.css`
- Modify: `tests-js/unit/views.test.js`
- Modify: `tests-e2e/student-teacher.spec.js`

- [x] **Step 1: Change existing browser assertions to the new user journey**

Update the personal archive test to follow the `История` link and inspect the corresponding expanded `.history-entry`. Move student review-list assertions from the home panel to `/history.html`. Add regression assertions on `/`:

```javascript
await expect(page.locator("#studentReviewRequestsPanel")).toHaveCount(0);
await expect(page.locator("#progressModal")).toHaveCount(0);
await expect(page.getByRole("button", { name: /очистить историю/i })).toHaveCount(0);
```

- [x] **Step 2: Run the changed browser tests and confirm the red result**

Run:

```bash
npx playwright test tests-e2e/student-teacher.spec.js --grep "personal archive|review request"
```

Expected: old home-only selectors and navigation fail.

- [x] **Step 3: Remove old HTML and replace the account action with a link**

Delete `studentReviewRequestsPanel` and the full `progressModal`. Replace `openProgressBtn` with:

```html
<a class="text-btn account-history-link" href="history.html">История →</a>
```

Do not add any history deletion control.

- [x] **Step 4: Remove old runner rendering and event handling**

Delete `renderHistory`, `clearHistory`, progress-modal close/open/backdrop/Escape branches, student review-list click delegation, and unused `escapeHtml`/`formatHistoryDate` imports. `renderProgress` continues to update the account summary but no longer builds history markup.

- [x] **Step 5: Narrow the account controllers to their remaining responsibilities**

- `account-controller.js`: for a student, `refreshAccountData` becomes a no-op; teacher refresh remains unchanged.
- `account-review-requests-controller.js`: remove `studentReviewRequestsMarkup`, DOM reset/list loading, and uploading-discard export; after successful submission keep the result-screen message and toast without refreshing a removed list.
- `account-personal-recordings-controller.js`: remove `personalRecordingsMarkup` and list-loading DOM work. When an archive completes, remove it from the in-memory pending map without loading a list.
- `account-view.js`: delete only `studentReviewRequestsMarkup`; retain all teacher functions.
- `account-auth-controller.js`: `anyModalOpen` contains only auth and teacher modals.

Keep archive generation/owner guards and the result-screen retry status unchanged.

- [x] **Step 6: Replace obsolete unit tests with responsibility tests**

Remove direct tests of the deleted student/list markup. Update personal archive tests so their fake document provides only nodes still used by the archive path, and verify:

- reset invalidates an in-flight upload;
- delayed upload from a former user cannot trigger a success status for the new user;
- a successful upload removes the pending archive without issuing a list GET.

- [x] **Step 7: Delete only obsolete modal/list CSS**

Remove selectors dedicated to `#progressModal`, `.history-sections`, `.history-list`, `.history-item`, `.personal-recordings-history`, `.personal-recording-item`, and `.student-review-requests`. Do not remove shared teacher or account styles with mixed selectors until the selector is rewritten for the remaining elements.

- [x] **Step 8: Run focused unit and browser regressions**

Run:

```bash
node --test tests-js/unit/views.test.js tests-js/unit/history-*.test.js
npx playwright test tests-e2e/student-teacher.spec.js tests-e2e/history.spec.js
```

Expected: archive/submission behavior remains green and old surfaces are absent.

- [x] **Step 9: Commit the removal**

```bash
git add frontend/pages/index.html frontend/js/runner/app.js frontend/js/account frontend/styles/base.css tests-js/unit/views.test.js tests-e2e/student-teacher.spec.js
git commit -m "refactor: remove fragmented student history views"
```

---

## Task 7: Finish accessibility, responsive, and contract coverage

**Files:**

- Modify: `tests-e2e/history.spec.js`
- Modify: `tests-e2e/reference.spec.js`
- Modify: `frontend/styles/pages/history.css`
- Modify: `tests/integration/test_asgi.py`

- [x] **Step 1: Add failing mobile and keyboard assertions**

At a 360px viewport, assert `document.documentElement.scrollWidth <= document.documentElement.clientWidth`. Focus the first summary with the keyboard, press Enter, and assert the details opens. Check the computed short side of retry and discard buttons is at least 44px.

- [x] **Step 2: Add navigation and cache-contract assertions**

Extend shared-header coverage to include `История` on all public pages. Extend
`FastApiSmokeTest.test_health_static_and_private_data_boundary` to request
`/history.html`, `/js/history/history-page.js`, and `/styles/pages/history.css`.
For each response, assert status 200, `Cache-Control == "no-cache"`, and
`X-Content-Type-Options == "nosniff"`.

- [x] **Step 3: Run focused tests and make minimal fixes**

Run:

```bash
npx playwright test tests-e2e/history.spec.js tests-e2e/reference.spec.js
.venv/bin/python -m unittest tests.integration.test_asgi.FastApiSmokeTest.test_health_static_and_private_data_boundary
```

If a test fails, adjust only `history.css` or the page semantics needed by that assertion; do not add JavaScript accordion behavior.

- [x] **Step 4: Commit quality coverage**

```bash
git add frontend/styles/pages/history.css tests-e2e/history.spec.js tests-e2e/reference.spec.js tests/integration/test_asgi.py
git commit -m "test: cover accessible student history"
```

---

## Task 8: Documentation, stale-reference audit, and full verification

**Files:**

- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-09-unified-student-history.md`

- [x] **Step 1: Update the user-facing documentation**

Describe `История` as the single page for attempts, personal audio with expiry, and teacher reviews. State that guests see browser-local attempts, signed-in students receive synchronized history, and recordings are still deleted automatically according to the existing retention rule. Remove instructions that point to the old modal, separate archive, or `Мои разборы` block.

- [x] **Step 2: Audit for stale implementation references**

Run:

```bash
rg -n "progressModal|openProgressBtn|clearHistoryBtn|studentReviewRequestsPanel|studentReviewRequestsList|personalRecordingsList|studentReviewRequestsMarkup|personalRecordingsMarkup|loadStudentReviewRequests|loadPersonalRecordings" frontend tests-js tests-e2e README.md
```

Expected: no stale production references; any test occurrence is an intentional absence assertion.

- [x] **Step 3: Run JavaScript and Python focused checks**

Run:

```bash
npm test
.venv/bin/python -m unittest tests.integration.test_api_flows tests.integration.test_asgi
```

Expected: all pass.

- [x] **Step 4: Run mandatory project verification**

Run:

```bash
make check
make test-e2e
```

Expected: both exit 0 with no skipped history coverage.

- [x] **Step 5: Review the final diff against the approved spec**

Run:

```bash
git diff --check
git status --short
git diff --stat main...HEAD
git diff main...HEAD -- src/trainer frontend tests tests-js tests-e2e README.md
```

Confirm every approved behavior is represented, teacher behavior is untouched, no secrets/runtime data are staged, and `.superpowers/` remains untracked.

- [x] **Step 6: Mark the plan complete and commit documentation**

Check every completed box in this plan, then commit:

```bash
git add README.md docs/superpowers/plans/2026-09-09-unified-student-history.md
git commit -m "docs: describe unified student history"
```

- [x] **Step 7: Prepare the branch for local integration**

Use `superpowers:requesting-code-review` for a self-review, then `superpowers:verification-before-completion`. Once the fresh checks are recorded, use `superpowers:finishing-a-development-branch` and present the local-merge option first, matching the established workflow.
