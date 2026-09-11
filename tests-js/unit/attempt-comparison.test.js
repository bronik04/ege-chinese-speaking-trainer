import assert from "node:assert/strict";
import test from "node:test";

import {
  AttemptComparisonError,
  buildAttemptComparison,
  buildComparisonSelection,
  isSelectableAttempt,
  sameTaskSet,
} from "../../frontend/js/history/attempt-comparison.js";

function entry(id, tasks, status = "completed", overrides = {}) {
  return {
    key: `run:${id}`,
    runId: id,
    run: {
      id,
      mode: tasks.length === 1 ? "task" : "exam",
      variantId: overrides.variantId || "open-2026",
      variantLabel: overrides.variantLabel || "Официальный вариант 2026",
      tasks,
      completedTasks: status === "completed" ? [...tasks] : [],
      startedAt: "2026-09-09T10:00:00.000Z",
      status,
      completedAt: "2026-09-09T10:05:00.000Z",
      recordingsCount: 0,
    },
    variantId: overrides.variantId || "open-2026",
    variantLabel: overrides.variantLabel || "Официальный вариант 2026",
    tasks: [...tasks],
    recordings: [],
    reviewRequests: [],
    latestReview: null,
    recovered: false,
    sortAt: Date.parse("2026-09-09T10:05:00.000Z"),
    ...overrides,
  };
}

function reviewedRequest({ id, task = 2, total, maximum = 7, reviewedAt, submittedAt = reviewedAt - 10, scores }) {
  return {
    id,
    runId: null,
    variantId: "open-2026",
    kind: "task",
    status: "reviewed",
    tasks: [task],
    submittedAt,
    reviewedAt,
    total,
    maximum,
    items: [{ task, total, maximum, scores, recordings: [] }],
    assets: [],
  };
}

test("only completed concrete runs can be selected", () => {
  assert.equal(isSelectableAttempt(entry("done", [2])), true);
  assert.equal(isSelectableAttempt(entry("stopped", [2], "interrupted")), false);
  assert.equal(isSelectableAttempt({ ...entry("recovered", [2]), recovered: true }), false);
  assert.equal(isSelectableAttempt({ ...entry("missing", [2]), run: null }), false);
});

test("task compatibility uses run tasks while ignoring variant and task order", () => {
  assert.equal(
    sameTaskSet(
      entry("a", [3, 1, 2], "completed", { variantId: "open-2026" }),
      entry("b", [1, 2, 3], "completed", { variantId: "demo-2025" }),
    ),
    true,
  );
  assert.equal(sameTaskSet(entry("a", [2]), entry("b", [3])), false);

  const contaminated = entry("c", [2]);
  contaminated.tasks = [1, 2, 3];
  assert.equal(sameTaskSet(contaminated, entry("d", [2])), true);
});

test("selection normalizes IDs and disables completed attempts with different tasks", () => {
  const entries = [
    entry("task-2-a", [2]),
    entry("task-2-b", [2], "completed", { variantId: "demo-2025" }),
    entry("task-3", [3]),
    entry("interrupted", [2], "interrupted"),
  ];

  const result = buildComparisonSelection(
    entries,
    ["unknown", "task-2-a", "task-2-a", "task-2-b", "task-3"],
  );

  assert.deepEqual(result.selectedIds, ["task-2-a", "task-2-b"]);
  assert.equal(result.canCompare, true);
  assert.deepEqual(result.choices, [
    { runId: "task-2-a", selected: true, selectable: true, reason: null },
    { runId: "task-2-b", selected: true, selectable: true, reason: null },
    { runId: "task-3", selected: false, selectable: false, reason: "different_tasks" },
    { runId: "interrupted", selected: false, selectable: false, reason: "incomplete" },
  ]);
});

test("removing the anchor makes every completed task set selectable again", () => {
  const entries = [entry("task-2", [2]), entry("task-3", [3])];

  const result = buildComparisonSelection(entries, []);

  assert.deepEqual(result.selectedIds, []);
  assert.equal(result.canCompare, false);
  assert.deepEqual(result.choices.map(choice => choice.selectable), [true, true]);
});

test("two selected attempts disable every other compatible choice", () => {
  const entries = [
    entry("first", [2]),
    entry("second", [2]),
    entry("third", [2]),
  ];

  const result = buildComparisonSelection(entries, ["first", "second"]);

  assert.deepEqual(result.selectedIds, ["first", "second"]);
  assert.deepEqual(result.choices, [
    { runId: "first", selected: true, selectable: true, reason: null },
    { runId: "second", selected: true, selectable: true, reason: null },
    { runId: "third", selected: false, selectable: false, reason: "selection_full" },
  ]);
});

test("comparison uses the latest reviewed score for each task", () => {
  const left = entry("left", [2], "completed", {
    reviewRequests: [reviewedRequest({
      id: 1,
      total: 4,
      reviewedAt: 100,
      scores: { content: 2, organization: 1, language: 1 },
    })],
  });
  const right = entry("right", [2], "completed", {
    variantId: "demo-2025",
    variantLabel: "Демонстрационный вариант 2025",
    reviewRequests: [
      reviewedRequest({
        id: 2,
        total: 5,
        reviewedAt: 150,
        scores: { content: 2, organization: 2, language: 1 },
      }),
      reviewedRequest({
        id: 3,
        total: 6,
        reviewedAt: 200,
        scores: { content: 3, organization: 2, language: 1 },
      }),
    ],
  });

  const comparison = buildAttemptComparison([right, left], "left", "right");

  assert.deepEqual(comparison.left, {
    runId: "left",
    variantId: "open-2026",
    variantLabel: "Официальный вариант 2026",
    completedAt: "2026-09-09T10:05:00.000Z",
    tasks: [2],
  });
  assert.equal(comparison.right.variantLabel, "Демонстрационный вариант 2025");
  assert.deepEqual(comparison.tasks[0].right.score, {
    total: 6,
    maximum: 7,
    criteria: { content: 3, organization: 2, language: 1 },
  });
  assert.equal(comparison.tasks[0].delta, 2);
});

test("personal audio wins and missing task-one slots stay aligned", () => {
  const left = entry("left", [1], "completed", {
    recordings: [{
      id: 7,
      runId: "left",
      variantId: "open-2026",
      taskNumber: 1,
      questionNumber: 1,
      label: "Личный вопрос 1",
      createdAt: 100,
      expiresAt: 200,
    }],
    reviewRequests: [{
      ...reviewedRequest({ id: 8, task: 1, total: 4, maximum: 5, reviewedAt: 120, scores: { question1: 1 } }),
      items: [{
        task: 1,
        total: 4,
        maximum: 5,
        scores: { question1: 1 },
        recordings: [
          { id: 80, question_number: 1, label: "Копия вопроса 1", url: "/api/review-recordings/80" },
          { id: 81, questionNumber: 2, label: "Вопрос 2", url: "/api/review-recordings/81" },
        ],
      }],
    }],
  });
  const right = entry("right", [1]);

  const task = buildAttemptComparison([left, right], "left", "right").tasks[0];

  assert.deepEqual(task.left.recordings.map(slot => slot.key), ["1:1", "1:2", "1:3", "1:4", "1:5"]);
  assert.deepEqual(task.left.recordings.map(slot => slot.label), [
    "Вопрос 1",
    "Вопрос 2",
    "Вопрос 3",
    "Вопрос 4",
    "Вопрос 5",
  ]);
  assert.equal(task.left.recordings[0].source, "personal");
  assert.equal(task.left.recordings[0].recording.id, 7);
  assert.equal(task.left.recordings[1].source, "review");
  assert.equal(task.left.recordings[1].recording.id, 81);
  assert.equal(task.left.recordings[4].recording, null);
  assert.equal(task.left.recordings[4].source, null);
  assert.equal(task.right.recordings[4].recording, null);
});

test("comparison reports stable errors for invalid attempt pairs", () => {
  const completed = entry("completed", [2]);
  const interrupted = entry("interrupted", [2], "interrupted");
  const recovered = { ...entry("recovered", [2]), recovered: true };
  const otherTask = entry("other-task", [3]);

  const expectedCode = (leftId, rightId, code, entries) => {
    assert.throws(
      () => buildAttemptComparison(entries, leftId, rightId),
      error => error instanceof AttemptComparisonError && error.code === code,
    );
  };

  expectedCode("missing", "completed", "attempt_missing", [completed]);
  expectedCode("completed", "interrupted", "attempt_ineligible", [completed, interrupted]);
  expectedCode("completed", "recovered", "attempt_ineligible", [completed, recovered]);
  expectedCode("completed", "other-task", "attempt_incompatible", [completed, otherTask]);
  expectedCode("completed", "completed", "attempt_incompatible", [completed]);
});

test("queued requests do not hide the newest reviewed score", () => {
  const left = entry("left", [2]);
  const right = entry("right", [2], "completed", {
    reviewRequests: [
      {
        ...reviewedRequest({
          id: 9,
          total: 7,
          reviewedAt: 300,
          scores: { content: 3, organization: 2, language: 2 },
        }),
        status: "queued",
        reviewedAt: null,
        submittedAt: 500,
      },
      reviewedRequest({
        id: 7,
        total: 4,
        reviewedAt: 200,
        submittedAt: 190,
        scores: { content: 2, organization: 1, language: 1 },
      }),
      reviewedRequest({
        id: 8,
        total: 5,
        reviewedAt: 200,
        submittedAt: 190,
        scores: { content: 2, organization: 2, language: 1 },
      }),
    ],
  });

  const score = buildAttemptComparison([left, right], "left", "right").tasks[0].right.score;

  assert.equal(score.total, 5);
});

test("delta is absent when scores are missing or use different maxima", () => {
  const left = entry("left", [2], "completed", {
    reviewRequests: [reviewedRequest({
      id: 1,
      total: 4,
      maximum: 7,
      reviewedAt: 100,
      scores: { content: 2 },
    })],
  });
  const differentMaximum = entry("different-maximum", [2], "completed", {
    reviewRequests: [reviewedRequest({
      id: 2,
      total: 4,
      maximum: 6,
      reviewedAt: 100,
      scores: { content: 2 },
    })],
  });
  const missingScore = entry("missing-score", [2]);

  assert.equal(buildAttemptComparison([left, differentMaximum], "left", "different-maximum").tasks[0].delta, null);
  assert.equal(buildAttemptComparison([left, missingScore], "left", "missing-score").tasks[0].delta, null);
});

test("task two review audio without a question number uses its single answer slot", () => {
  const left = entry("left", [2], "completed", {
    reviewRequests: [{
      ...reviewedRequest({ id: 1, total: 4, reviewedAt: 100, scores: { content: 2 } }),
      items: [{
        task: 2,
        total: 4,
        maximum: 7,
        scores: { content: 2 },
        recordings: [{ id: 90, question_number: null, label: "Ответ", url: "/api/review-recordings/90" }],
      }],
    }],
  });
  const right = entry("right", [2]);

  const slot = buildAttemptComparison([left, right], "left", "right").tasks[0].left.recordings[0];

  assert.equal(slot.key, "2:1");
  assert.equal(slot.recording.id, 90);
  assert.equal(slot.source, "review");
});
