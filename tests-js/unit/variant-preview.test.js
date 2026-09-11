import assert from "node:assert/strict";
import test from "node:test";

import {
  VariantPreviewError,
  isSafeMaterialImageUrl,
  projectVariantPreview,
} from "../../frontend/js/catalog/variant-preview.js";

function fullMaterialFixture(overrides = {}) {
  return {
    id: "open-2026",
    label: "Официальный вариант 2026",
    source: "ФИПИ",
    year: 2026,
    kind: "full",
    taskNumber: null,
    totalMinutes: 14,
    tasks: {
      "1": {
        title: "Скрытый заголовок",
        situation: "Вы увидели объявление",
        banner: "欢迎你们加入轮滑鞋俱乐部!",
        questions: ["минимальный возраст"],
        image: "assets/variants/open-2026/candidate-01.webp",
        imageAlt: "Роллерклуб",
      },
      "2": {
        lead: "Скрытая инструкция",
        prompts: ["когда сделана фотография"],
        starter: "我选择第 {n} 号照片……",
        images: [
          "/assets/variants/open-2026/candidate-02.webp",
          "assets/variants/open-2026/candidate-03.webp",
          "/api/material-assets/17",
        ],
      },
      "3": {
        title: "Скрытый проект",
        lead: "Скрытая инструкция",
        prompts: ["опишите фотографии"],
        images: [
          "assets/variants/open-2026/candidate-05.webp",
          "assets/variants/open-2026/candidate-06.webp",
        ],
        imageLabels: ["Осень", "Зима"],
        unknown: "никогда не копировать",
      },
    },
    unknown: "никогда не копировать",
    ...overrides,
  };
}

test("projection keeps all six images but no question content", () => {
  const preview = projectVariantPreview(fullMaterialFixture());

  assert.deepEqual(preview.tasks.map(task => task.images.length), [1, 3, 2]);
  assert.equal(preview.tasks[2].images[0].label, "Осень");
  assert.deepEqual(preview.tasks.map(task => task.title), [
    "Задание 1 · Вопросы к объявлению",
    "Задание 2 · Описание фотографии",
    "Задание 3 · Проектная работа",
  ]);
  assert.deepEqual(
    Object.keys(preview).sort(),
    ["id", "kind", "label", "source", "taskNumber", "tasks", "totalMinutes", "year"],
  );
  const serialized = JSON.stringify(preview);
  for (const secret of [
    "situation", "banner", "questions", "lead", "prompts", "starter",
    "минимальный возраст", "никогда не копировать", "Скрытый заголовок",
  ]) {
    assert.doesNotMatch(serialized, new RegExp(secret));
  }
});

test("safe image URL allowlist accepts only exact same-origin material paths", () => {
  for (const value of [
    "assets/variants/a.webp",
    "/assets/variants/a.webp",
    "/api/material-assets/17",
  ]) assert.equal(isSafeMaterialImageUrl(value), true, value);

  for (const value of [
    "", "javascript:alert(1)", "data:image/png;base64,abc", "//example.test/a.webp",
    "https://example.test/a.webp", "assets/a.webp?download=1", "assets/a.webp#fragment",
    "assets\\a.webp", "assets//a.webp", "assets/../secret", "assets/%2e%2e/secret",
    "assets/%252e%252e/secret", "assets/%252525252e%252525252e/secret.webp",
    "assets/a\u0000.webp", "/api/material-assets/0",
    "/api/material-assets/-1", "/api/material-assets/not-a-number", "/api/material-assets/17/extra",
  ]) assert.equal(isSafeMaterialImageUrl(value), false, String(value));
});

test("projection uses alt and labels as text with stable fallbacks", () => {
  const material = fullMaterialFixture();
  material.tasks[1].imageAlt = "Описание <не разметка>";
  material.tasks[3].imageLabels = ["Первая <подпись>", ""];
  const preview = projectVariantPreview(material);

  assert.deepEqual(preview.tasks[0].images[0], {
    src: "assets/variants/open-2026/candidate-01.webp",
    alt: "Описание <не разметка>",
    label: null,
  });
  assert.equal(preview.tasks[1].images[0].alt, "Изображение 1 задания 2");
  assert.deepEqual(preview.tasks[2].images.map(image => [image.alt, image.label]), [
    ["Первая <подпись>", "Первая <подпись>"],
    ["Изображение 2 задания 3", null],
  ]);
});

test("task-only projection returns only the requested task and preserves invalid slots", () => {
  const material = fullMaterialFixture({ kind: "task", taskNumber: 2 });
  material.tasks[2].images[1] = "javascript:alert(1)";
  const preview = projectVariantPreview(material);

  assert.equal(preview.taskNumber, 2);
  assert.deepEqual(preview.tasks.map(task => task.number), [2]);
  assert.equal(preview.tasks[0].images.length, 3);
  assert.deepEqual(preview.tasks[0].images[1], {
    src: null,
    alt: "Изображение 2 задания 2",
    label: null,
  });
});

test("invalid required material structure has one stable error contract", () => {
  const invalidMaterials = [
    fullMaterialFixture({ id: "" }),
    fullMaterialFixture({ kind: "unknown" }),
    fullMaterialFixture({ kind: "task", taskNumber: 4 }),
    fullMaterialFixture({ kind: "task", taskNumber: 2, tasks: { "1": {} } }),
    fullMaterialFixture({ tasks: null }),
  ];

  for (const material of invalidMaterials) {
    assert.throws(
      () => projectVariantPreview(material),
      error => error instanceof VariantPreviewError && error.code === "invalid_material" && error.message === "invalid_material",
    );
  }
});
