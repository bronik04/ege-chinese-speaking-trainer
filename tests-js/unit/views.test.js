import assert from "node:assert/strict";
import test from "node:test";

import {
  teacherReviewRequestDetailMarkup,
  teacherReviewRequestsMarkup,
} from "../../frontend/js/account/account-view.js";
import { escapeHtml } from "../../frontend/js/shared/progress.js";
import { formatTime, stepsMarkup, taskMarkup } from "../../frontend/js/runner/task-view.js";
import { auditMarkup } from "../../frontend/js/account/account-security.js";
import { api } from "../../frontend/js/shared/api.js";
import { catalogMarkup, filterVariants, variantKind } from "../../frontend/js/catalog/variant-catalog.js";
import { plural, pluralize } from "../../frontend/js/shared/plural.js";
import { fullyRecordedTasks } from "../../frontend/js/account/account-review-requests-controller.js";
import { createAccountPersonalRecordingsController } from "../../frontend/js/account/account-personal-recordings-controller.js";

test("escapeHtml protects every HTML-sensitive character", () => {
  assert.equal(escapeHtml(`<script data-x="'">&`), "&lt;script data-x=&quot;&#39;&quot;&gt;&amp;");
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

function apiResponse(payload, status = 200) {
  return { ok: status < 400, status, json: async () => payload };
}

test("account reset invalidates an in-flight archive before another user can receive it", async () => {
  const originalFetch = globalThis.fetch;
  let user = { id: 1, role: "student" };
  let releaseFirstUpload;
  const firstUpload = new Promise(resolve => { releaseFirstUpload = resolve; });
  const postOwners = [];
  globalThis.fetch = async (path, options = {}) => {
    if (options.method === "POST") {
      postOwners.push(user?.id);
      if (postOwners.length === 1) await firstUpload;
      return apiResponse({ recording: { id: postOwners.length } }, 201);
    }
    return apiResponse({ recordings: [{ id: 99, label: "student-a", taskNumber: 2, questionNumber: 1 }] });
  };
  try {
    const controller = createAccountPersonalRecordingsController({
      getUser: () => user,
      setArchiveStatus() {},
    });
    const archive = controller.archiveCompletedRun(
      { id: "run-a", variantId: "demo-2026" },
      [1, 2].map(question => ({ task: 1, question, label: `Q${question}`, type: "audio/webm", blob: new Blob(["x"]) })),
    );
    await Promise.resolve();
    user = null;
    controller.reset();
    user = { id: 2, role: "student" };
    releaseFirstUpload();
    await archive;

    assert.deepEqual(postOwners, [1]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("successful archive upload does not fetch a separate recording list", async () => {
  const originalFetch = globalThis.fetch;
  const methods = [];
  const statuses = [];
  globalThis.fetch = async (_path, options = {}) => {
    methods.push(options.method || "GET");
    return apiResponse({ recording: { id: 99 } }, 201);
  };
  try {
    const controller = createAccountPersonalRecordingsController({
      getUser: () => ({ id: 1, role: "student" }),
      setArchiveStatus: (message, canRetry) => statuses.push({ message, canRetry }),
    });
    await controller.archiveCompletedRun(
      { id: "run-a", variantId: "demo-2026" },
      [{ task: 2, question: null, label: "Answer", type: "audio/webm", blob: new Blob(["x"]) }],
    );

    assert.deepEqual(methods, ["POST"]);
    assert.deepEqual(statuses.at(-1), { message: "Аудиозаписи сохранены в личном архиве.", canRetry: false });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("starting another archive retries every older pending run", async () => {
  const originalFetch = globalThis.fetch;
  let attempts = 0;
  const requestedRuns = [];
  globalThis.fetch = async (path, options = {}) => {
    if (options.method === "POST") {
      attempts += 1;
      requestedRuns.push(new URL(path, "http://local").searchParams.get("runId"));
      if (attempts === 1) throw new Error("temporary network failure");
      return apiResponse({ recording: { id: 1 } }, 201);
    }
    throw new Error(`Unexpected request: ${path}`);
  };
  try {
    const controller = createAccountPersonalRecordingsController({
      getUser: () => ({ id: 1, role: "student" }),
      setArchiveStatus() {},
    });
    await controller.archiveCompletedRun(
      { id: "old-run", variantId: "demo-2026" },
      [{ task: 2, question: null, label: "Answer", type: "audio/webm", blob: new Blob(["x"]) }],
    );
    await controller.archiveCompletedRun(
      { id: "new-run", variantId: "demo-2026" },
      [{ task: 3, question: null, label: "New answer", type: "audio/webm", blob: new Blob(["y"]) }],
    );
    assert.deepEqual(requestedRuns, ["old-run", "old-run", "new-run"]);
  } finally {
    globalThis.fetch = originalFetch;
  }
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
  assert.match(markup, /class="teacher-request-heading"/);
  assert.match(markup, /class="teacher-request-status"/);
  assert.match(markup, /class="review-form"/);
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
  assert.match(html, /href="variant-preview\.html\?variant=demo-2026"/);
  assert.match(html, />Предпросмотр →<\/a>/);
  assert.doesNotMatch(html, /href="index\.html\?variant=/);
});

test("restricted variant catalog offers registration without blocking the open material", () => {
  const markup = catalogMarkup([{
    id: "open-2026", year: 2026, label: "Открытый вариант", source: "ФИПИ", totalMinutes: 14, tasks: {},
  }], { restricted: true });

  assert.match(markup, /id="catalogAccessNotice"/);
  assert.match(markup, /После регистрации доступны остальные варианты и личный архив записей/);
  assert.match(markup, /href="index\.html\?account=1"/);
  assert.match(markup, /href="variant-preview\.html\?variant=open-2026"/);
  assert.doesNotMatch(catalogMarkup([], { restricted: true }), /catalogAccessNotice/);
  assert.doesNotMatch(catalogMarkup([{ id: "open-2026", year: 2026, label: "Open", source: "ФИПИ", totalMinutes: 14, tasks: {} }]), /catalogAccessNotice/);
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
