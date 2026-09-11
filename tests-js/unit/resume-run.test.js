import assert from "node:assert/strict";
import test from "node:test";

import { prepareRunResume } from "../../frontend/js/runner/resume-run.js";

test("resume restarts the first unfinished task from its locked idle phase", () => {
  const stored = {
    id: "run-1",
    variantId: "open-2026",
    variantLabel: "Официальный вариант 2026",
    mode: "exam",
    tasks: [1, 2, 3],
    completedTasks: [1],
    currentTask: 1,
    phase: "answer",
    fastMode: false,
    startedAt: "2026-09-10T08:00:00.000Z",
  };

  const resumed = prepareRunResume(stored);

  assert.deepEqual(resumed, {
    ...stored,
    completedTasks: [1],
    currentTask: 2,
    phase: "idle",
  });
  assert.notEqual(resumed, stored);
  assert.notEqual(resumed.completedTasks, stored.completedTasks);
  assert.equal(stored.currentTask, 1);
  assert.equal(stored.phase, "answer");
});
