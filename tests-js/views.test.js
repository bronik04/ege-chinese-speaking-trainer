import assert from "node:assert/strict";
import test from "node:test";

import { studentAssignmentsMarkup, teacherGroupsMarkup } from "../js/account-view.js";
import { escapeHtml, mergeProgress } from "../js/progress.js";
import { formatTime, stepsMarkup, taskMarkup } from "../js/task-view.js";
import { auditMarkup } from "../js/account-security.js";

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
