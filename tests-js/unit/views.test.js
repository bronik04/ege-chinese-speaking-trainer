import assert from "node:assert/strict";
import test from "node:test";

import { assignmentTasksMarkup, studentAssignmentsMarkup, teacherGroupsMarkup } from "../../frontend/js/account/account-view.js";
import { escapeHtml, mergeProgress } from "../../frontend/js/shared/progress.js";
import { formatTime, stepsMarkup, taskMarkup } from "../../frontend/js/runner/task-view.js";
import { auditMarkup } from "../../frontend/js/account/account-security.js";
import { api } from "../../frontend/js/shared/api.js";
import { catalogMarkup, filterVariants, variantKind } from "../../frontend/js/catalog/variant-catalog.js";

test("escapeHtml protects every HTML-sensitive character", () => {
  assert.equal(escapeHtml(`<script data-x="'">&`), "&lt;script data-x=&quot;&#39;&quot;&gt;&amp;");
});

test("mergeProgress deduplicates runs and keeps the newest settings", () => {
  const local = {
    version: 1,
    updatedAt: "2026-07-04T12:00:00Z",
    settings: { fastMode: true },
    runs: [{ id: "same", startedAt: "2026-07-04T10:00:00Z" }],
    activeRun: null,
  };
  const remote = {
    version: 1,
    updatedAt: "2026-07-04T11:00:00Z",
    settings: { fastMode: false },
    runs: [
      { id: "same", startedAt: "2026-07-04T09:00:00Z" },
      { id: "remote", startedAt: "2026-07-04T08:00:00Z" },
    ],
  };
  const merged = mergeProgress(local, remote);
  assert.equal(merged.runs.length, 2);
  assert.equal(merged.runs.find(run => run.id === "same").startedAt, local.runs[0].startedAt);
  assert.equal(merged.settings.fastMode, true);
});

test("account markup escapes teacher-controlled text", () => {
  const assignments = studentAssignmentsMarkup([{
    id: 1,
    groupName: "<img src=x>",
    title: "<script>alert(1)</script>",
    tasks: [1],
    dueAt: null,
    latest: null,
  }]);
  assert.doesNotMatch(assignments, /<script>|<img src=x>/);
  assert.match(assignments, /&lt;script&gt;/);

  const groups = teacherGroupsMarkup([{
    name: "<b>group</b>",
    code: "ABC123",
    students: [],
  }]);
  assert.doesNotMatch(groups, /<b>group<\/b>/);
});

test("assignment UI marks late work and limits standalone task choices", () => {
  const assignments = studentAssignmentsMarkup([{
    id: 2,
    groupName: "Group",
    title: "Late work",
    tasks: [2],
    dueAt: 1,
    latest: { status: "submitted", late: true },
  }]);
  assert.match(assignments, /Сдано после срока/);
  const choices = assignmentTasksMarkup({ kind: "task", taskNumber: 2 });
  assert.match(choices, /value="2"/);
  assert.doesNotMatch(choices, /value="exam"|value="1"|value="3"/);
});

test("task markup escapes JSON content and keeps runner state", () => {
  const html = taskMarkup(1, {
    title: "<script>bad</script>",
    situation: "Ситуация",
    questions: ["Цена", "Адрес", "Время", "Скидки", "Доставка"],
    banner: "广告",
    image: "image.webp",
    imageAlt: "Фото",
  }, { phase: "answer", questionIndex: 1, selectedPhoto: 1, photoChoiceMade: false });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /Вопрос 2 из 5/);
  assert.equal(formatTime(125), "02:05");
  assert.match(stepsMarkup([1, 2, 3], 1), /done/);
});

test("audit markup translates actions and escapes network data", () => {
  const html = auditMarkup([{
    action: "login_succeeded",
    ipAddress: "<script>bad</script>",
    createdAt: 1783166400,
  }]);
  assert.match(html, /Выполнен вход/);
  assert.doesNotMatch(html, /<script>/);
});

test("api exposes structured server error metadata", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 409,
    json: async () => ({
      code: "submission_already_graded",
      message: "Работа уже проверена",
      requestId: "request-123",
    }),
  });
  try {
    await assert.rejects(api("/api/test"), error => {
      assert.equal(error.message, "Работа уже проверена");
      assert.equal(error.code, "submission_already_graded");
      assert.equal(error.requestId, "request-123");
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("variant catalog filters and escapes exam metadata", () => {
  const variants = [
    { id: "demo-2026", year: 2026, label: "<Demo>", source: "ФИПИ", totalMinutes: 14, tasks: { "1": { title: "<script>" } } },
    { id: "open-2026", year: 2026, label: "Open", source: "Открытый вариант", totalMinutes: 14, tasks: {} },
    { id: "demo-2025", year: 2025, label: "Demo 2025", source: "ФИПИ", totalMinutes: 14, tasks: {} },
  ];
  assert.equal(filterVariants(variants, "2026").length, 2);
  assert.equal(filterVariants(variants, "all", "открытый").length, 1);
  assert.equal(variantKind("open-2026"), "Официальный вариант");
  const html = catalogMarkup([variants[0]]);
  assert.doesNotMatch(html, /<script>|<Demo>/);
  assert.match(html, /&lt;script&gt;|&lt;Demo&gt;/);
});
