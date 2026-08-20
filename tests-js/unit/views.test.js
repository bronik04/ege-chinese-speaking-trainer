import assert from "node:assert/strict";
import test from "node:test";

import {
  studentReviewRequestsMarkup,
  teacherReviewRequestDetailMarkup,
  teacherReviewRequestsMarkup,
} from "../../frontend/js/account/account-view.js";
import { escapeHtml, mergeProgress } from "../../frontend/js/shared/progress.js";
import { formatTime, stepsMarkup, taskMarkup } from "../../frontend/js/runner/task-view.js";
import { auditMarkup } from "../../frontend/js/account/account-security.js";
import { api } from "../../frontend/js/shared/api.js";
import { catalogMarkup, filterVariants, variantKind } from "../../frontend/js/catalog/variant-catalog.js";
import { plural, pluralize } from "../../frontend/js/shared/plural.js";
import { fullyRecordedTasks } from "../../frontend/js/account/account-review-requests-controller.js";

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

test("mergeProgress lets the newer side clear activeRun", () => {
  const finished = {
    version: 1,
    updatedAt: "2026-07-04T12:00:00Z",
    settings: { fastMode: false },
    runs: [],
    activeRun: null,
  };
  const staleRemote = {
    version: 1,
    updatedAt: "2026-07-04T11:00:00Z",
    settings: { fastMode: false },
    runs: [],
    activeRun: { id: "stale-run", startedAt: "2026-07-04T10:00:00Z" },
  };
  assert.equal(mergeProgress(finished, staleRemote).activeRun, null);

  const staleLocal = { ...staleRemote, updatedAt: "2026-07-04T10:00:00Z" };
  const clearedRemote = { ...finished, updatedAt: "2026-07-04T13:00:00Z" };
  assert.equal(mergeProgress(staleLocal, clearedRemote).activeRun, null);

  const liveLocal = { ...staleRemote, updatedAt: "2026-07-04T14:00:00Z" };
  assert.equal(mergeProgress(liveLocal, clearedRemote).activeRun.id, "stale-run");
});

test("student review request markup hides queued scores and escapes the variant title", () => {
  const queued = studentReviewRequestsMarkup([{
    kind: "task",
    status: "queued",
    variantId: "<script>alert(1)</script>",
    tasks: [2],
    submittedAt: 1_789_000_000,
    total: 7,
    maximum: 7,
  }]);
  assert.match(queued, /Одно задание/);
  assert.match(queued, /На разборе/);
  assert.doesNotMatch(queued, /7\/7/);
  assert.doesNotMatch(queued, /<script>/);
  assert.match(queued, /&lt;script&gt;/);

  const reviewed = studentReviewRequestsMarkup([{
    kind: "attempt",
    status: "reviewed",
    variantId: "demo-2026",
    tasks: [1, 2, 3],
    submittedAt: 1_789_000_000,
    total: 7,
    maximum: 7,
  }]);
  assert.match(reviewed, /Вся попытка/);
  assert.match(reviewed, /Разобрано: 7\/7/);

  const uploading = studentReviewRequestsMarkup([{
    id: 42,
    kind: "task",
    status: "uploading",
    variantId: "demo-2026",
    tasks: [1],
    submittedAt: null,
  }]);
  assert.match(uploading, /Загрузка не завершена/);
  assert.match(uploading, /data-discard-review-request="42"/);
  assert.doesNotMatch(uploading, /На разборе/);
});

test("fully recorded tasks require every task-specific recording position", () => {
  const recordings = [
    ...[1, 2, 3, 4].map(question => ({ task: 1, question })),
    { task: 2, question: null },
    { task: 3, question: null },
  ];

  assert.deepEqual(fullyRecordedTasks([1, 2, 3], recordings), [2, 3]);
  assert.deepEqual(fullyRecordedTasks([1], [...recordings, { task: 1, question: 5 }]), [1]);
  assert.deepEqual(fullyRecordedTasks([2], [{ task: 2, question: 1 }]), []);
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

test("review queue markup keeps private audio and score-only request details", () => {
  const markup = teacherReviewRequestsMarkup([{
    id: 1,
    studentName: "<script>Student</script>",
    studentEmail: "student@example.test",
    kind: "task",
    status: "reviewed",
    submittedAt: 1_789_000_000,
    tasks: [1],
    total: 4,
    maximum: 5,
    items: [{
      task: 1,
      scores: { question1: 1, question2: 1, question3: 1, question4: 1, question5: 0 },
      recordings: [{
      id: 7,
      label: "Задание 1",
      url: "/api/review-recordings/7",
      }],
    }],
  }]);
  assert.match(markup, /&lt;script&gt;Student&lt;\/script&gt;/);
  assert.match(markup, /\/api\/review-recordings\/7/);
  assert.match(markup, /4\/5/);
  assert.doesNotMatch(markup, /Группа|Срок|Назначение|textarea|Комментарий/);
});

test("teacher review detail renders escaped immutable material with private snapshot images", () => {
  const markup = teacherReviewRequestDetailMarkup({
    material: {
      "2": {
        title: "<script>Фото</script>",
        lead: "Опишите снимок & план",
        prompts: ["<img src=x onerror=alert(1)>", "Почему выбрали"],
        starter: "我选择第 {n} 号照片……",
        images: ["/api/review-assets/17", "assets/variants/source.webp"],
      },
    },
  }, []);

  assert.match(markup, /Материал задания 2/);
  assert.match(markup, /&lt;script&gt;Фото&lt;\/script&gt;/);
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(markup, /План ответа/);
  assert.match(markup, /src="\/api\/review-assets\/17"/);
  assert.doesNotMatch(markup, /<script>|<img src=x|assets\/variants\/source\.webp/);
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
  assert.equal(variantKind("bank-01"), "Вариант из банка ФИПИ");
  assert.equal(variantKind("demo-2026"), "Демонстрационный вариант");
  const html = catalogMarkup([variants[0]]);
  assert.doesNotMatch(html, /<script>|<Demo>/);
  assert.match(html, /&lt;script&gt;|&lt;Demo&gt;/);
});

test("plural picks the Russian numeral form, including the 11-14 exception", () => {
  const forms = ["вариант", "варианта", "вариантов"];
  assert.equal(plural(1, ...forms), "вариант");
  assert.equal(plural(2, ...forms), "варианта");
  assert.equal(plural(5, ...forms), "вариантов");
  assert.equal(plural(0, ...forms), "вариантов");
  assert.equal(plural(11, ...forms), "вариантов");
  assert.equal(plural(12, ...forms), "вариантов");
  assert.equal(plural(14, ...forms), "вариантов");
  assert.equal(plural(21, ...forms), "вариант");
  assert.equal(plural(22, ...forms), "варианта");
  assert.equal(plural(111, ...forms), "вариантов");
  assert.equal(plural(121, ...forms), "вариант");
  assert.equal(pluralize(3, ...forms), "3 варианта");
});

test("catalog card shows a correctly declined duration", () => {
  const card = (totalMinutes) => catalogMarkup([{ id: "open-2026", year: 2026, label: "Open", source: "ФИПИ", totalMinutes, tasks: {} }]);
  assert.match(card(1), /≈ 1 минута/);
  assert.match(card(3), /≈ 3 минуты/);
  assert.match(card(14), /≈ 14 минут/);
});
