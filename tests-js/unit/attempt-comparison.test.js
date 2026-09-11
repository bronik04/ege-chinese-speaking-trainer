import assert from "node:assert/strict";
import test from "node:test";

import {
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
