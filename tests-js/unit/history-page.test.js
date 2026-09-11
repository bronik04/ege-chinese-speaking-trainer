import assert from "node:assert/strict";
import test from "node:test";

import { createHistoryPageController } from "../../frontend/js/history/history-controller.js";
import { defaultProgress, progressStorageKeys } from "../../frontend/js/shared/progress.js";

function completedRun(id, completedAt) {
  return {
    id,
    variantId: "open-2026",
    variantLabel: `Материал ${id}`,
    mode: "practice",
    tasks: [2],
    completedTasks: [2],
    currentTask: 2,
    phase: "answer",
    fastMode: false,
    startedAt: completedAt.replace("T11:00", "T09:00"),
    status: "completed",
    completedAt,
    recordingsCount: 1,
  };
}

function progressWith(...runs) {
  return {
    ...defaultProgress(),
    updatedAt: "2026-09-09T12:00:00.000Z",
    runs,
  };
}

function memoryStorage(seed = {}) {
  const values = new Map(Object.entries(seed));
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
}

function apiError(status, message) {
  return Object.assign(new Error(message), { status });
}

const nextTurn = () => new Promise(resolve => setTimeout(resolve, 0));

test("student history exposes independent loading and retry lifecycle", async () => {
  const user = { id: 17, email: "student@example.test", role: "student", displayName: "Student", emailVerified: true };
  let releaseProgress;
  let releaseRecordings;
  let releaseReviews;
  let recordingCalls = 0;
  const progressResponse = new Promise(resolve => { releaseProgress = resolve; });
  const firstRecordings = new Promise(resolve => { releaseRecordings = resolve; });
  const reviewsResponse = new Promise(resolve => { releaseReviews = resolve; });
  let retryRecordings;
  const request = async (path, options = {}) => {
    if (path === "/api/auth/me") return { user };
    if (path === "/api/progress" && options.method === "PUT") return { ok: true };
    if (path === "/api/progress") return progressResponse;
    if (path === "/api/personal-recordings") {
      recordingCalls += 1;
      return recordingCalls === 1 ? firstRecordings : retryRecordings;
    }
    if (path === "/api/student/review-requests") return reviewsResponse;
    throw new Error(`Unexpected request: ${path}`);
  };
  const rendered = [];
  const controller = createHistoryPageController({
    request,
    storage: memoryStorage(),
    render: state => rendered.push(state),
  });

  const load = controller.load();
  await nextTurn();
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: true, recordings: true, reviews: true });

  releaseReviews({ requests: [] });
  await nextTurn();
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: true, recordings: true, reviews: false });

  releaseRecordings({ recordings: [] });
  await nextTurn();
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: true, recordings: false, reviews: false });

  releaseProgress({ progress: null });
  await load;
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: false, recordings: false, reviews: false });

  let releaseRetry;
  retryRecordings = new Promise(resolve => { releaseRetry = resolve; });
  const retry = controller.retry("recordings");
  await nextTurn();
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: false, recordings: true, reviews: false });
  releaseRetry({ recordings: [] });
  await retry;
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: false, recordings: false, reviews: false });
});

test("student history merges progress, preserves a failed source and retries only that source", async () => {
  const user = { id: 17, email: "student@example.test", role: "student", displayName: "Student", emailVerified: true };
  const local = progressWith(completedRun("local-run", "2026-09-09T11:00:00.000Z"));
  const remote = progressWith(completedRun("remote-run", "2026-09-08T11:00:00.000Z"));
  const scope = progressStorageKeys(user.id);
  const storage = memoryStorage({ [scope.current]: JSON.stringify(local) });
  const calls = [];
  let recordingsAvailable = false;
  const request = async (path, options = {}) => {
    calls.push({ path, options });
    if (path === "/api/auth/me") return { user };
    if (path === "/api/progress" && options.method === "PUT") return { ok: true };
    if (path === "/api/progress") return { progress: remote };
    if (path === "/api/personal-recordings") {
      if (!recordingsAvailable) throw new Error("recordings unavailable");
      return { recordings: [{ id: 7, runId: "local-run", variantId: "open-2026", taskNumber: 2, questionNumber: 1, label: "Ответ", createdAt: 1_788_950_000, expiresAt: 1_804_700_000 }] };
    }
    if (path === "/api/student/review-requests") {
      return { requests: [{ id: 8, runId: "local-run", variantId: "open-2026", kind: "task", status: "queued", tasks: [2], submittedAt: 1_788_950_100, reviewedAt: null, items: [], assets: [] }] };
    }
    throw new Error(`Unexpected request: ${path}`);
  };
  const rendered = [];
  const controller = createHistoryPageController({ request, storage, render: state => rendered.push(state) });

  await controller.load();

  const first = rendered.at(-1);
  assert.equal(first.mode, "student");
  assert.deepEqual(first.progress.runs.map(run => run.id), ["local-run", "remote-run"]);
  assert.equal(first.recordings.length, 0);
  assert.equal(first.reviewRequests.length, 1);
  assert.match(first.sourceErrors.recordings, /recordings unavailable/);
  assert.equal(first.sourceErrors.reviews, null);
  assert.deepEqual(first.sourceLoading, { progress: false, recordings: false, reviews: false });
  assert.deepEqual(JSON.parse(storage.getItem(scope.current)).runs.map(run => run.id), ["local-run", "remote-run"]);
  const progressWrite = calls.find(call => call.path === "/api/progress" && call.options.method === "PUT");
  assert.deepEqual(JSON.parse(progressWrite.options.body).progress.runs.map(run => run.id), ["local-run", "remote-run"]);

  recordingsAvailable = true;
  const callsBeforeRetry = calls.length;
  await controller.retry("recordings");

  const retried = rendered.at(-1);
  assert.equal(retried.recordings.length, 1);
  assert.equal(retried.sourceErrors.recordings, null);
  assert.deepEqual(calls.slice(callsBeforeRetry).map(call => call.path), ["/api/personal-recordings"]);
});

test("teacher history never loads student-owned sources", async () => {
  const calls = [];
  const rendered = [];
  const request = async path => {
    calls.push(path);
    return { user: { id: 1, email: "teacher@example.test", role: "teacher", displayName: "Teacher", emailVerified: true } };
  };
  const controller = createHistoryPageController({ request, storage: memoryStorage(), render: state => rendered.push(state) });

  await controller.load();

  assert.deepEqual(calls, ["/api/auth/me"]);
  assert.equal(rendered.at(-1).mode, "teacher");
  assert.deepEqual(rendered.at(-1).progress.runs, []);
  assert.deepEqual(rendered.at(-1).sourceLoading, { progress: false, recordings: false, reviews: false });
});

test("a delayed response from the previous load cannot replace the current account", async () => {
  let releaseFirstAuth;
  const firstAuth = new Promise(resolve => { releaseFirstAuth = resolve; });
  let authCalls = 0;
  const rendered = [];
  const request = async (path, options = {}) => {
    if (path === "/api/auth/me") {
      authCalls += 1;
      if (authCalls === 1) return firstAuth;
      return { user: { id: 2, email: "b@example.test", role: "student", displayName: "B", emailVerified: true } };
    }
    if (path === "/api/progress" && options.method === "PUT") return { ok: true };
    if (path === "/api/progress") return { progress: null };
    if (path === "/api/personal-recordings") return { recordings: [] };
    if (path === "/api/student/review-requests") return { requests: [] };
    throw new Error(`Unexpected request: ${path}`);
  };
  const controller = createHistoryPageController({ request, storage: memoryStorage(), render: state => rendered.push(state) });

  const oldLoad = controller.load();
  await Promise.resolve();
  await controller.load();
  releaseFirstAuth({ user: { id: 1, email: "a@example.test", role: "student", displayName: "A", emailVerified: true } });
  await oldLoad;

  assert.equal(rendered.at(-1).user.id, 2);
  assert.equal(rendered.some(state => state.user?.id === 1), false);
});

test("a delayed protected response from student A cannot replace student B data", async () => {
  const studentA = { id: 1, email: "a@example.test", role: "student", displayName: "A", emailVerified: true };
  const studentB = { id: 2, email: "b@example.test", role: "student", displayName: "B", emailVerified: true };
  let authCalls = 0;
  let recordingCalls = 0;
  let releaseStudentARecordings;
  const studentARecordings = new Promise(resolve => { releaseStudentARecordings = resolve; });
  const rendered = [];
  const request = async (path, options = {}) => {
    if (path === "/api/auth/me") {
      authCalls += 1;
      return { user: authCalls === 1 ? studentA : studentB };
    }
    if (path === "/api/progress" && options.method === "PUT") return { ok: true };
    if (path === "/api/progress") return { progress: null };
    if (path === "/api/personal-recordings") {
      recordingCalls += 1;
      if (recordingCalls === 1) return studentARecordings;
      return { recordings: [{ id: 22, runId: "b-run", label: "Запись B" }] };
    }
    if (path === "/api/student/review-requests") return { requests: [] };
    throw new Error(`Unexpected request: ${path}`);
  };
  const controller = createHistoryPageController({
    request,
    storage: memoryStorage(),
    render: state => rendered.push(state),
  });

  const oldLoad = controller.load();
  await nextTurn();
  await controller.load();
  releaseStudentARecordings({ recordings: [{ id: 11, runId: "a-run", label: "Запись A" }] });
  await oldLoad;

  const state = rendered.at(-1);
  assert.equal(state.user.id, studentB.id);
  assert.deepEqual(state.recordings.map(recording => recording.id), [22]);
  assert.equal(rendered.some(item => item.user?.id === studentB.id && item.recordings.some(recording => recording.id === 11)), false);
});

test("a protected 401 clears account data and falls back to guest-local history", async () => {
  const user = { id: 9, email: "student@example.test", role: "student", displayName: "Student", emailVerified: true };
  const guest = progressWith(completedRun("guest-run", "2026-09-09T11:00:00.000Z"));
  const account = progressWith(completedRun("account-run", "2026-09-09T10:00:00.000Z"));
  const storage = memoryStorage({
    [progressStorageKeys().current]: JSON.stringify(guest),
    [progressStorageKeys(user.id).current]: JSON.stringify(account),
  });
  const rendered = [];
  const request = async path => {
    if (path === "/api/auth/me") return { user };
    if (path === "/api/progress") throw apiError(401, "session expired");
    throw new Error(`Unexpected request: ${path}`);
  };
  const controller = createHistoryPageController({ request, storage, render: state => rendered.push(state) });

  await controller.load();

  const state = rendered.at(-1);
  assert.equal(state.mode, "guest");
  assert.equal(state.user, null);
  assert.deepEqual(state.progress.runs.map(run => run.id), ["guest-run"]);
  assert.equal(state.progress.runs.some(run => run.id === "account-run"), false);
  assert.deepEqual(state.sourceLoading, { progress: false, recordings: false, reviews: false });
});

test("discarding an uploading review reloads reviews and keeps a failed deletion visible", async () => {
  const user = { id: 5, email: "student@example.test", role: "student", displayName: "Student", emailVerified: true };
  let reviews = [{ id: 42, runId: "run-42", variantId: "open-2026", kind: "task", status: "uploading", tasks: [2], submittedAt: null, reviewedAt: null, items: [], assets: [] }];
  const rendered = [];
  const request = async (path, options = {}) => {
    if (path === "/api/auth/me") return { user };
    if (path === "/api/progress" && options.method === "PUT") return { ok: true };
    if (path === "/api/progress") return { progress: null };
    if (path === "/api/personal-recordings") return { recordings: [] };
    if (path === "/api/student/review-requests") return { requests: reviews };
    throw new Error(`Unexpected request: ${path}`);
  };
  let deletionFails = false;
  const discard = async id => {
    assert.equal(id, 42);
    if (deletionFails) throw new Error("delete unavailable");
    reviews = [];
  };
  const controller = createHistoryPageController({ request, discard, storage: memoryStorage(), render: state => rendered.push(state) });
  await controller.load();

  assert.equal(await controller.discardReviewRequest(42), true);
  assert.deepEqual(rendered.at(-1).reviewRequests, []);

  reviews = [{ id: 42, runId: "run-42", variantId: "open-2026", kind: "task", status: "uploading", tasks: [2], submittedAt: null, reviewedAt: null, items: [], assets: [] }];
  await controller.retry("reviews");
  deletionFails = true;
  assert.equal(await controller.discardReviewRequest(42), false);
  assert.equal(rendered.at(-1).reviewRequests.length, 1);
  assert.match(rendered.at(-1).sourceErrors.reviews, /delete unavailable/);
  assert.equal(await controller.discardReviewRequest(0), false);
});
