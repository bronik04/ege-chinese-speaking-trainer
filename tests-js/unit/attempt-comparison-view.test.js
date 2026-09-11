import assert from "node:assert/strict";
import test from "node:test";

import {
  attemptComparisonMarkup,
  comparisonPageStateMarkup,
} from "../../frontend/js/history/attempt-comparison-view.js";

function comparisonFixture(overrides = {}) {
  return {
    left: {
      runId: "left",
      variantId: "open-2026",
      variantLabel: overrides.variantLabel || "Официальный вариант 2026",
      completedAt: "2026-09-08T10:05:00.000Z",
      tasks: [2],
    },
    right: {
      runId: "right",
      variantId: "demo-2025",
      variantLabel: "Демонстрационный вариант 2025",
      completedAt: "2026-09-09T10:05:00.000Z",
      tasks: [2],
    },
    tasks: [{
      number: 2,
      left: {
        score: {
          total: 4,
          maximum: 7,
          criteria: { content: 2, organization: 1, language: 1 },
        },
        recordings: [{
          key: "2:1",
          label: "Ответ",
          source: "personal",
          recording: { id: 7, label: "Мой ответ" },
        }],
      },
      right: {
        score: {
          total: 6,
          maximum: 7,
          criteria: { content: 3, organization: 2, language: 1 },
        },
        recordings: [{
          key: "2:1",
          label: "Ответ",
          source: "review",
          recording: { id: 8, label: "Ответ для разбора", url: "/api/review-recordings/8" },
        }],
      },
      delta: 2,
    }],
  };
}

test("comparison view renders aligned scores and audio without trusting network strings", () => {
  const html = attemptComparisonMarkup(comparisonFixture({
    variantLabel: '<script>bad</script><img src=x onerror="alert(1)">',
  }));

  assert.match(html, /Задание 2/);
  assert.match(html, /\+2 балла/);
  assert.match(html, /Решение коммуникативной задачи/);
  assert.match(html, /Организация высказывания/);
  assert.match(html, /Языковое оформление/);
  assert.match(html, /src="\/api\/personal-recordings\/7"/);
  assert.match(html, /src="\/api\/review-recordings\/8"/);
  assert.match(html, /Оценки: 1 из 1 · Записи: 1 из 1/);
  assert.match(html, /aria-label="Первая попытка, Ответ: Мой ответ"/);
  assert.match(html, /aria-label="Вторая попытка, Ответ: Ответ для разбора"/);
  assert.doesNotMatch(html, /<label class="comparison-audio"/);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|<img|onerror="|javascript:/);
});

test("comparison view keeps missing score and audio slots explicit", () => {
  const comparison = comparisonFixture();
  comparison.tasks[0].left.score = null;
  comparison.tasks[0].right.recordings[0] = {
    key: "2:1",
    label: "Ответ",
    source: "review",
    recording: { id: 0, label: "Bad", url: "javascript:alert(1)" },
  };
  comparison.tasks[0].delta = null;

  const html = attemptComparisonMarkup(comparison);

  assert.match(html, /Оценки пока нет/);
  assert.match(html, /Запись недоступна/);
  assert.doesNotMatch(html, /javascript:|review-recordings\/0/);
  assert.equal((html.match(/<audio /g) || []).length, 1);
  assert.match(html, /Оценки: 0 из 1 · Записи: 1 из 1/);
  assert.match(html, /Оценки: 1 из 1 · Записи: 0 из 1/);
});

test("comparison page state uses stable copy and escapes optional details", () => {
  assert.match(comparisonPageStateMarkup({ kind: "loading" }), /Загружаем сравнение/);
  assert.match(comparisonPageStateMarkup({ kind: "attempt_missing" }), /не найдена в вашей истории/);
  assert.match(comparisonPageStateMarkup({ kind: "teacher" }), /доступно только ученику/);
  assert.match(
    comparisonPageStateMarkup({ kind: "network", message: '<img src=x onerror="bad">' }),
    /&lt;img src=x onerror=&quot;bad&quot;&gt;/,
  );
  assert.doesNotMatch(
    comparisonPageStateMarkup({ kind: "network", message: '<img src=x onerror="bad">' }),
    /<img|onerror="/,
  );
});
