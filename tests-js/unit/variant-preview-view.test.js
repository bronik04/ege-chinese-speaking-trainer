import assert from "node:assert/strict";
import test from "node:test";

import {
  variantPreviewMarkup,
  variantPreviewStateMarkup,
} from "../../frontend/js/catalog/variant-preview-view.js";

function previewFixture(overrides = {}) {
  return {
    id: "open-2026",
    label: "Официальный вариант 2026",
    source: "ФИПИ",
    year: 2026,
    kind: "full",
    taskNumber: null,
    totalMinutes: 14,
    tasks: [
      {
        number: 1,
        title: "Задание 1 · Вопросы к объявлению",
        images: [{ src: "assets/variants/a.webp", alt: "Объявление", label: null }],
      },
      {
        number: 2,
        title: "Задание 2 · Описание фотографии",
        images: [1, 2, 3].map(number => ({
          src: `/assets/variants/photo-${number}.webp`,
          alt: `Фотография ${number}`,
          label: null,
        })),
      },
      {
        number: 3,
        title: "Задание 3 · Проектная работа",
        images: [
          { src: "/api/material-assets/17", alt: "Осень", label: "Осень" },
          { src: "assets/variants/winter.webp", alt: "Зима", label: "Зима" },
        ],
      },
    ],
    ...overrides,
  };
}

test("preview markup renders galleries and escapes all network text", () => {
  const preview = previewFixture({
    label: "<script>bad</script>",
    source: "Источник & автор",
  });
  preview.tasks[0].images[0].alt = 'Фото" onerror="alert(1)';
  preview.tasks[2].images[0].label = "Осень <img src=x>";

  const html = variantPreviewMarkup(preview);

  assert.equal((html.match(/<img /gu) || []).length, 6);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/u);
  assert.match(html, /Источник &amp; автор/u);
  assert.match(html, /alt="Фото&quot; onerror=&quot;alert\(1\)"/u);
  assert.match(html, /Осень &lt;img src=x&gt;/u);
  assert.match(html, /Перейти к тренировке/u);
  assert.match(html, /href="index\.html\?variant=open-2026"/u);
  assert.deepEqual((html.match(/class="variant-preview-task"/gu) || []).length, 3);
  assert.doesNotMatch(html, /<script>|javascript:|минимальный возраст/u);
});

test("view repeats URL validation and renders unavailable image slots", () => {
  const preview = previewFixture();
  preview.tasks[1].images[0].src = "javascript:alert(1)";
  preview.tasks[1].images[1].src = null;

  const html = variantPreviewMarkup(preview);

  assert.equal((html.match(/<img /gu) || []).length, 4);
  assert.equal((html.match(/class="variant-preview-image-missing"/gu) || []).length, 2);
  assert.doesNotMatch(html, /javascript:/u);
});

test("CTA and metadata cannot inject attributes", () => {
  const html = variantPreviewMarkup(previewFixture({
    id: 'demo" onclick="alert(1)',
    label: 'Вариант" autofocus',
    source: "<img src=x onerror=alert(1)>",
    year: "<2026>",
  }));

  assert.doesNotMatch(html, /onclick="alert|autofocus=|<img src=x/u);
  assert.match(html, /variant=demo%22\+onclick%3D%22alert%281%29/u);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/u);
  assert.match(html, /&lt;2026&gt;/u);
});

test("task-only preview has one task section", () => {
  const task = previewFixture().tasks[1];
  const html = variantPreviewMarkup(previewFixture({
    kind: "task",
    taskNumber: 2,
    tasks: [task],
  }));

  assert.equal((html.match(/class="variant-preview-task"/gu) || []).length, 1);
  assert.match(html, /Отдельное задание 2/u);
  assert.doesNotMatch(html, /Задание 1|Задание 3/u);
});

test("page states use stable copy and escape optional messages", () => {
  assert.match(variantPreviewStateMarkup({ kind: "loading" }), /Загружаем предпросмотр/u);
  assert.match(variantPreviewStateMarkup({ kind: "not_found" }), /Вариант не найден/u);
  assert.match(variantPreviewStateMarkup({ kind: "forbidden" }), /нужно войти/u);
  assert.match(variantPreviewStateMarkup({ kind: "network" }), /data-preview-retry/u);
  assert.match(variantPreviewStateMarkup({ kind: "invalid_material" }), /не удалось подготовить/u);

  const escaped = variantPreviewStateMarkup({ kind: "network", message: "<script>server</script>" });
  assert.match(escaped, /&lt;script&gt;server&lt;\/script&gt;/u);
  assert.doesNotMatch(escaped, /<script>/u);
});
