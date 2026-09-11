import assert from "node:assert/strict";
import test from "node:test";

import { buildHistoryTimeline } from "../../frontend/js/history/history-model.js";

const run = (id, completedAt, overrides = {}) => ({
  id,
  variantId: `${id}-variant`,
  variantLabel: `${id} material`,
  mode: "practice",
  tasks: [2],
  completedTasks: [2],
  currentTask: 2,
  phase: "answer",
  fastMode: false,
  startedAt: "2026-09-08T09:00:00.000Z",
  status: "completed",
  completedAt,
  recordingsCount: 1,
  ...overrides,
});

test("history groups every recording and review under its training run without mutating sources", () => {
  const runs = [
    run("run-1", "2026-09-08T10:00:00.000Z"),
    run("run-new", "2026-09-09T10:00:00.000Z", { mode: "exam", tasks: [1, 2, 3] }),
  ];
  const recordings = [
    { id: 2, runId: "run-1", variantId: "run-1-variant", taskNumber: 2, questionNumber: 1, createdAt: 1_788_860_100 },
    { id: 1, runId: "run-1", variantId: "run-1-variant", taskNumber: 1, questionNumber: 2, createdAt: 1_788_860_000 },
    { id: 41, runId: "orphan-audio", variantId: "archive-variant", taskNumber: 3, questionNumber: 1, createdAt: 1_788_900_000 },
  ];
  const reviewRequests = [
    { id: 11, runId: "run-1", variantId: "run-1-variant", tasks: [2], status: "queued", submittedAt: 1_788_860_200 },
    { id: 12, runId: "run-1", variantId: "run-1-variant", tasks: [2], status: "reviewed", submittedAt: 1_788_860_300 },
    { id: 21, runId: "orphan-review", variantId: "review-variant", tasks: [1, 3], status: "queued", submittedAt: 1_788_940_000 },
    { id: 31, runId: null, variantId: "legacy-a", tasks: [1], status: "reviewed", submittedAt: 1_788_930_000 },
    { id: 32, runId: null, variantId: "legacy-b", tasks: [2], status: "queued", submittedAt: 1_788_920_000 },
  ];
  const sources = JSON.parse(JSON.stringify({ runs, recordings, reviewRequests }));

  const entries = buildHistoryTimeline({ runs, recordings, reviewRequests });

  assert.equal(entries[0].runId, "run-new");
  const grouped = entries.find(entry => entry.runId === "run-1");
  assert.deepEqual(grouped.recordings.map(item => item.id), [1, 2]);
  assert.deepEqual(grouped.reviewRequests.map(item => item.id), [12, 11]);
  assert.equal(grouped.latestReview.id, 12);
  assert.equal(entries.filter(entry => entry.key.startsWith("review:")).length, 2);
  assert.equal(entries.find(entry => entry.key === "run:orphan-audio").recovered, true);
  assert.equal(entries.find(entry => entry.key === "run:orphan-review").recovered, true);
  assert.deepEqual({ runs, recordings, reviewRequests }, sources);
});

test("history derives orphan dates and uses stable keys to break timestamp ties", () => {
  const tiedDate = 1_788_950_000;
  const entries = buildHistoryTimeline({
    runs: [],
    recordings: [
      { id: 9, runId: "z", variantId: "z", taskNumber: 3, questionNumber: 1, createdAt: tiedDate },
      { id: 8, runId: "a", variantId: "a", taskNumber: 2, questionNumber: 1, createdAt: tiedDate },
    ],
    reviewRequests: [],
  });

  assert.deepEqual(entries.map(entry => entry.key), ["run:a", "run:z"]);
  assert.deepEqual(entries.map(entry => entry.sortAt), [tiedDate * 1000, tiedDate * 1000]);
  assert.deepEqual(entries.map(entry => entry.tasks), [[2], [3]]);
});

test("history treats invalid dates as oldest instead of producing an unstable order", () => {
  const entries = buildHistoryTimeline({
    runs: [run("valid", "2026-09-09T12:00:00.000Z"), run("invalid", "not-a-date")],
    recordings: [],
    reviewRequests: [],
  });

  assert.deepEqual(entries.map(entry => entry.runId), ["valid", "invalid"]);
  assert.equal(entries[1].sortAt, 0);
});
