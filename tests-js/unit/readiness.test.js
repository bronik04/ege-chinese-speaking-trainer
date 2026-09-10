import test from "node:test";
import assert from "node:assert/strict";
import { buildReadinessSummary } from "../../frontend/js/runner/readiness.js";

const variant = {
  id: "open-2026",
  label: "Официальный вариант 2026",
  totalMinutes: 14,
  tasks: {
    1: { prepSeconds: 90, answerSeconds: 20 },
    2: { prepSeconds: 120, answerSeconds: 120 },
    3: { prepSeconds: 180, answerSeconds: 180 },
  },
};

const interrupted = {
  id: "interrupted",
  variantId: variant.id,
  variantLabel: variant.label,
  mode: "exam",
  tasks: [1, 2, 3],
  completedTasks: [1],
  currentTask: 1,
  phase: "answer",
  fastMode: false,
  startedAt: "2026-09-10T08:00:00.000Z",
};

test("exam readiness summarizes the complete attempt", () => {
  assert.deepEqual(buildReadinessSummary({
    variant,
    pending: { kind: "new", startMode: "exam" },
    activeRun: null,
  }), {
    material: variant.label,
    mode: "Экзамен",
    tasks: "Задания 1–3",
    duration: "14 минут",
    action: "Начать экзамен",
  });
});

test("single-task readiness includes every short answer part", () => {
  assert.equal(buildReadinessSummary({
    variant,
    pending: { kind: "new", startMode: "1" },
    activeRun: null,
  }).duration, "4 минуты");
});

test("resume readiness includes only unfinished exam tasks", () => {
  assert.deepEqual(buildReadinessSummary({
    variant,
    pending: { kind: "resume", startMode: "exam" },
    activeRun: interrupted,
  }), {
    material: variant.label,
    mode: "Продолжение экзамена",
    tasks: "Задания 2–3",
    duration: "10 минут",
    action: "Продолжить",
  });
});

test("restart readiness restores the complete exam", () => {
  const summary = buildReadinessSummary({
    variant,
    pending: { kind: "restart", startMode: "exam" },
    activeRun: interrupted,
  });
  assert.equal(summary.tasks, "Задания 1–3");
  assert.equal(summary.duration, "14 минут");
  assert.equal(summary.action, "Начать заново");
});

test("stored-run readiness does not use the currently selected material timings", () => {
  const currentTaskOnlyVariant = {
    id: "task-2-only",
    label: "Только задание 2",
    totalMinutes: 4,
    tasks: {
      2: { prepSeconds: 120, answerSeconds: 120 },
    },
  };

  const resumed = buildReadinessSummary({
    variant: currentTaskOnlyVariant,
    pending: { kind: "resume", startMode: "exam" },
    activeRun: interrupted,
  });
  const restarted = buildReadinessSummary({
    variant: currentTaskOnlyVariant,
    pending: { kind: "restart", startMode: "exam" },
    activeRun: interrupted,
  });

  assert.equal(resumed.material, variant.label);
  assert.equal(resumed.tasks, "Задания 2–3");
  assert.equal(resumed.duration, "10 минут");
  assert.equal(restarted.material, variant.label);
  assert.equal(restarted.tasks, "Задания 1–3");
  assert.equal(restarted.duration, "14 минут");
});
