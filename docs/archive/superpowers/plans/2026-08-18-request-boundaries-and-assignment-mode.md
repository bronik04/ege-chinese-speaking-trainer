# Request Boundaries and Assignment Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject oversized streamed request bodies before application parsing and prevent fast mode from changing assigned work.

**Architecture:** A pure ASGI wrapper owns byte accounting so the rule applies before FastAPI reads a body. Assignment mode is enforced at the runner boundary and normalized again in the submission controller, keeping timing and stored run data consistent.

**Tech Stack:** Python 3.12+, FastAPI/Starlette, httpx/TestClient, vanilla JavaScript, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-core-reliability-design.md`

## Global Constraints

- Keep standard API error shape and use `request_too_large` with HTTP 413.
- Apply the limit to POST, PUT, PATCH and DELETE; never require `Content-Length`.
- Use `MAX_BODY` for ordinary routes, `MAX_AUDIO_BODY` for recordings, and 5,000,000 bytes for material assets.
- Preserve fast mode for self-directed practice; an assignment always stores `fastMode: false`.
- Add regression tests before production code, then run `make check` and `make test-e2e`.

---

### Task 1: Streaming request-size guard

**Files:**
- Create: `src/trainer/api/body_limit.py`
- Modify: `src/trainer/main.py:45-101`
- Test: `tests/integration/test_asgi.py:98-130`

**Interfaces:**
- Produces: `BodyLimitMiddleware(app, limit_for_path: Callable[[str], int])`, an ASGI callable that returns the standard 413 JSON response when the accumulated `http.request.body` bytes exceed the selected limit.
- Consumes: `MAX_BODY`, `MAX_AUDIO_BODY`, `error_payload()` and the FastAPI application.

- [ ] **Step 1: Write failing chunked-body tests**

  Add an async `httpx.AsyncClient(transport=ASGITransport(app=asgi.app))` test using an async generator that yields eleven 100,001-byte chunks without `Content-Length`; assert `413` and `request_too_large`. Add one test whose declared `Content-Length` exceeds 1 MB and one short chunked login request that does not receive `411`.

  ```python
  async def oversized_chunks():
      for _ in range(11):
          yield b"x" * 100_001

  response = await client.post("/api/auth/login", content=oversized_chunks(), headers=origin_headers)
  assert response.status_code == 413
  assert response.json()["code"] == "request_too_large"
  ```

- [ ] **Step 2: Run the tests to verify the streamed case fails**

  Run: `python -m pytest tests/integration/test_asgi.py -k "oversized or chunked" -v`

  Expected: the `Content-Length` case passes but the no-header oversized stream returns validation error rather than 413.

- [ ] **Step 3: Add the ASGI middleware and register it outermost**

  Implement a `BodyLimitExceeded` exception inside `body_limit.py`; the wrapped `receive` increments a local byte counter and raises it once it crosses the selected limit. Catch it in `__call__` before a response starts and invoke `JSONResponse(error_payload(...), status_code=413)` directly. In `main.py`, retain the existing header fast path and add the class with `app.add_middleware(BodyLimitMiddleware, limit_for_path=_body_limit_for_path)` after router registration.

  ```python
  async def limited_receive() -> Message:
      nonlocal received
      message = await receive()
      if message["type"] == "http.request":
          received += len(message.get("body", b""))
          if received > limit:
              raise BodyLimitExceeded
      return message
  ```

- [ ] **Step 4: Align the three route limits and pass the focused tests**

  Define `MATERIAL_ASSET_BODY = 5_000_000`; return it only for `/api/materials/{id}/assets`, `MAX_AUDIO_BODY` only for `/api/submissions/{id}/recordings`, and `MAX_BODY` otherwise. Run: `python -m pytest tests/integration/test_asgi.py -v`.

  Expected: PASS, including existing request-id and validation-contract tests.

- [ ] **Step 5: Commit the request guard**

  ```bash
  git add src/trainer/api/body_limit.py src/trainer/main.py tests/integration/test_asgi.py
  git commit -m "fix: limit streamed request bodies"
  ```

### Task 2: Enforce assignment timing and persisted run mode

**Files:**
- Modify: `frontend/js/runner/runner-controller.js:24-122`
- Modify: `frontend/js/runner/app.js:244-247`
- Modify: `src/trainer/api/controllers/work.py:229-279`
- Test: `tests-js/unit/runner-controller.test.js`
- Test: `tests/integration/test_api_flows.py`
- Test: `tests-e2e/student-teacher.spec.js`

**Interfaces:**
- Consumes: `startRun(startMode, assignment)` and `SubmissionRequest.run`.
- Produces: assigned runs whose `activeRun.fastMode` is `false`, and `submission_create()` that serializes an assignment run with `fastMode: false`.

- [ ] **Step 1: Add failing runner and API regression tests**

  Add a JS test that starts a run with `{ id: 7, tasks: [2] }` while `#fastMode.checked` is true; assert the timer uses the material’s normal seconds and `activeRun.fastMode === false`. Add a Python integration request with `run: {"fastMode": true}` for an assignment and assert the saved `run_json` has false.

  ```javascript
  startRun("2", { id: 7, tasks: [2] });
  assert.equal(progress.activeRun.fastMode, false);
  assert.equal(timerValue.textContent, "02:00");
  ```

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `npm test -- --test-name-pattern="assignment"` and `python -m pytest tests/integration/test_api_flows.py -k fast_mode -v`.

  Expected: both show the stored/current mode is true before the fix.

- [ ] **Step 3: Make assignment mode authoritative in the runner and controller**

  In `startRun`, compute `const assignmentRun = Boolean(assignment)`, set `fastMode: assignmentRun ? false : $("fastMode").checked`, and make `durationFor()` return normal timing when `activeAssignment` exists. Disable the fast-mode checkbox while an assigned run is active and restore it in `resetAssignment`/`exitRun`. In `submission_create`, copy `payload.run`, set `run["fastMode"] = False`, then serialize only for an assignment.

  ```javascript
  const isFast = !activeAssignment && $("fastMode").checked;
  if (!isFast) return taskData(task)[kind + "Seconds"];
  ```

- [ ] **Step 4: Verify browser behavior**

  Extend the Playwright assignment scenario to set the saved fast-mode checkbox before opening an assignment and assert the assignment timer uses normal duration. Run: `npm test && make test-e2e`.

  Expected: JS and browser suites PASS; standalone fast-mode test continues to use shortened timing.

- [ ] **Step 5: Commit assignment-mode enforcement**

  ```bash
  git add frontend/js/runner/runner-controller.js frontend/js/runner/app.js src/trainer/api/controllers/work.py tests-js tests/integration/test_api_flows.py tests-e2e/student-teacher.spec.js
  git commit -m "fix: enforce normal timing for assignments"
  ```
