import assert from "node:assert/strict";
import test from "node:test";

import { historyPageStateMarkup, historyTimelineMarkup } from "../../frontend/js/history/history-view.js";

test("history card summarizes a run and keeps every recording and review in its details", () => {
  const markup = historyTimelineMarkup([{
    key: "run:exam-1",
    runId: "exam-1",
    run: {
      mode: "exam",
      status: "completed",
      tasks: [1, 2, 3],
      completedAt: "2026-09-09T10:00:00.000Z",
    },
    variantId: "open-2026",
    variantLabel: "Открытый вариант 2026",
    tasks: [1, 2, 3],
    recordings: [{
      id: 7,
      label: "Ответ <первый>",
      taskNumber: 1,
      questionNumber: 2,
      expiresAt: 1_804_700_000,
    }],
    reviewRequests: [{
      id: 43,
      kind: "attempt",
      status: "reviewed",
      tasks: [1, 2, 3],
      submittedAt: 1_788_950_000,
      total: 17,
      maximum: 20,
      items: [{ recordings: [{ id: 71, label: "Копия для разбора", url: "/api/review-recordings/71" }] }],
    }, {
      id: 42,
      kind: "task",
      status: "uploading",
      tasks: [2],
      submittedAt: 1_788_940_000,
      items: [],
    }],
    latestReview: { id: 43, status: "reviewed", total: 17, maximum: 20 },
    recovered: false,
    sortAt: 1_788_944_400_000,
  }]);

  assert.match(markup, /<details class="history-entry"/);
  assert.match(markup, /<summary class="history-entry-summary">/);
  assert.match(markup, /Открытый вариант 2026/);
  assert.match(markup, /Полный экзамен/);
  assert.match(markup, /Завершено/);
  assert.match(markup, /1 аудиозапись/);
  assert.match(markup, /Разобрано: 17\/20/);
  assert.match(markup, /Задание 1, вопрос 2/);
  assert.match(markup, /\/api\/personal-recordings\/7/);
  assert.match(markup, /Удалится/);
  assert.match(markup, /Вся попытка/);
  assert.match(markup, /Копия для разбора/);
  assert.match(markup, /\/api\/review-recordings\/71/);
  assert.match(markup, /Загрузка не завершена/);
  assert.match(markup, /data-discard-review-request="42"/);
  assert.doesNotMatch(markup, /Ответ <первый>/);
  assert.match(markup, /Ответ &lt;первый&gt;/);
});

test("history view escapes network strings and omits unsafe audio sources", () => {
  const markup = historyTimelineMarkup([{
    key: 'run:"><script>alert(1)</script>',
    runId: "unsafe",
    run: {
      mode: "practice",
      status: "interrupted",
      tasks: [3],
      completedAt: "2026-09-08T10:00:00.000Z",
    },
    variantId: "unsafe",
    variantLabel: "<script>alert(1)</script>",
    tasks: [3],
    recordings: [{ id: "7-onerror", label: '" onerror="alert(1)', taskNumber: 3, expiresAt: 1_804_700_000 }],
    reviewRequests: [{
      id: 12,
      kind: "task",
      status: "queued",
      tasks: [3],
      submittedAt: 1_788_940_000,
      items: [{ recordings: [{ id: 1, label: "Bad", url: "javascript:alert(1)" }] }],
    }],
    latestReview: { id: 12, status: "queued" },
    recovered: false,
    sortAt: 1_788_858_000_000,
  }]);

  assert.match(markup, /Прервано/);
  assert.match(markup, /На разборе/);
  assert.doesNotMatch(markup, /<script>|javascript:|onerror="alert/);
  assert.doesNotMatch(markup, /\/api\/personal-recordings\/7-onerror/);
});

test("recovered cards and page states explain incomplete and guest data", () => {
  const recovered = historyTimelineMarkup([{
    key: "review:5",
    runId: null,
    run: null,
    variantId: "legacy-2025",
    variantLabel: "legacy-2025",
    tasks: [2],
    recordings: [],
    reviewRequests: [{ id: 5, kind: "task", status: "queued", tasks: [2], submittedAt: 1_788_940_000, items: [] }],
    latestReview: { id: 5, status: "queued" },
    recovered: true,
    sortAt: 1_788_940_000_000,
  }]);
  const guest = historyPageStateMarkup({ kind: "guest", message: "Данные <локальные>" });
  const teacher = historyPageStateMarkup({ kind: "teacher", message: "История учеников — в кабинете" });

  assert.match(recovered, /Восстановлено из архива/);
  assert.doesNotMatch(recovered, /Завершено|Прервано/);
  assert.match(recovered, /Аудиозаписей для этой попытки нет/);
  assert.match(guest, /Данные &lt;локальные&gt;/);
  assert.match(guest, /href="index\.html\?account=1"/);
  assert.match(teacher, /Открыть кабинет преподавателя/);
  assert.match(teacher, /href="teacher\.html"/);
});

test("empty history has a calm explanatory message", () => {
  assert.match(historyTimelineMarkup([]), /Здесь появятся завершённые и прерванные тренировки/);
});
