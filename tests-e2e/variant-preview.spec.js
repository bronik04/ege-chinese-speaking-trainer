import { expect, test } from "@playwright/test";

function fullMaterial(overrides = {}) {
  return {
    id: "preview-test",
    label: "Тестовый вариант",
    source: "Источник теста",
    year: 2026,
    kind: "full",
    taskNumber: null,
    totalMinutes: 14,
    tasks: {
      "1": {
        situation: "Скрытая ситуация",
        banner: "Скрытое объявление",
        questions: ["Скрытый вопрос"],
        image: "assets/variants/open-2026/candidate-01.webp",
        imageAlt: "Первая фотография",
      },
      "2": {
        lead: "Скрытая инструкция",
        prompts: ["Скрытая подсказка"],
        starter: "Скрытое начало",
        images: [
          "assets/variants/open-2026/candidate-02.webp",
          "assets/variants/open-2026/candidate-03.webp",
          "assets/variants/open-2026/candidate-04.webp",
        ],
      },
      "3": {
        title: "Скрытая тема проекта",
        lead: "Скрытая инструкция",
        prompts: ["Скрытая подсказка"],
        images: [
          "assets/variants/open-2026/candidate-05.webp",
          "assets/variants/open-2026/candidate-06.webp",
        ],
        imageLabels: ["Осень", "Зима"],
      },
    },
    ...overrides,
  };
}

test("full variant preview shows all image groups without questions or prompts", async ({ page }) => {
  await page.goto("/variant-preview.html?variant=open-2026");

  await expect(page.locator("#variantPreviewTitle")).toHaveText("Официальный вариант 2026");
  await expect(page.locator("#variantPreviewTitle")).toBeFocused();
  await expect(page.locator(".variant-preview-task")).toHaveCount(3);
  await expect(page.locator(".variant-preview-task").nth(0).locator("img")).toHaveCount(1);
  await expect(page.locator(".variant-preview-task").nth(1).locator("img")).toHaveCount(3);
  await expect(page.locator(".variant-preview-task").nth(2).locator("img")).toHaveCount(2);
  await expect(page.locator(".variant-preview-source")).toContainText("ФИПИ · официальный материал 2026");
  await expect(page.locator(".variant-preview-facts")).toContainText("2026");
  await expect(page.locator(".variant-preview-facts")).toContainText("14 минут");
  await expect(page.getByRole("link", { name: "Перейти к тренировке" })).toHaveAttribute(
    "href", "index.html?variant=open-2026",
  );
  await expect(page.getByRole("link", { name: "Вернуться к вариантам" })).toHaveAttribute("href", "variants.html");

  const html = await page.content();
  for (const secret of ["минимальный возраст", "欢迎你们加入轮滑鞋俱乐部", "我选择第"]) {
    expect(html).not.toContain(secret);
  }
});

test("not-found preview can be retried without exposing the server response", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/materials/retry-preview", route => {
    requests += 1;
    if (requests === 1) {
      return route.fulfill({ status: 404, json: { message: "<script>server secret</script>" } });
    }
    return route.fulfill({ json: { material: fullMaterial({ id: "retry-preview", label: "Повтор загружен" }) } });
  });

  await page.goto("/variant-preview.html?variant=retry-preview");

  await expect(page.locator(".variant-preview-state-not_found")).toContainText("Вариант не найден");
  await expect(page.locator("#variantPreviewTitle")).toBeFocused();
  expect(await page.content()).not.toContain("server secret");
  await page.getByRole("button", { name: "Попробовать снова" }).click();
  await expect(page.locator("#variantPreviewTitle")).toHaveText("Повтор загружен");
  await expect(page.locator(".variant-preview-task")).toHaveCount(3);
  expect(requests).toBe(2);
});

test("malicious text is escaped and an invalid image becomes a placeholder", async ({ page }) => {
  const material = fullMaterial({
    id: "malicious",
    label: "<script>bad</script>",
    source: '<img src=x onerror="alert(1)">',
  });
  material.tasks["2"].images[0] = "javascript:alert(1)";
  await page.route("**/api/materials/malicious", route => route.fulfill({ json: { material } }));

  await page.goto("/variant-preview.html?variant=malicious");

  await expect(page.locator("#variantPreviewTitle")).toHaveText("<script>bad</script>");
  await expect(page.locator(".variant-preview-image-missing")).toHaveCount(1);
  await expect(page.locator(".variant-preview-gallery img")).toHaveCount(5);
  await expect(page.locator(".variant-preview-source")).toHaveText('<img src=x onerror="alert(1)">');
  expect(await page.locator("script").count()).toBe(1);
  expect(await page.locator("img[onerror]").count()).toBe(0);
});

test("task-only preview is usable at 360px and keeps keyboard focus order", async ({ page }) => {
  const source = fullMaterial({ id: "single-task", kind: "task", taskNumber: 2, totalMinutes: 4 });
  source.tasks = { "2": source.tasks["2"] };
  await page.route("**/api/materials/single-task", route => route.fulfill({ json: { material: source } }));
  await page.setViewportSize({ width: 360, height: 800 });

  await page.goto("/variant-preview.html?variant=single-task");

  await expect(page.locator(".variant-preview-task")).toHaveCount(1);
  await expect(page.locator(".variant-preview-gallery img")).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  for (const locator of [
    page.getByRole("link", { name: "Вернуться к вариантам" }),
    page.getByRole("link", { name: "Перейти к тренировке" }),
  ]) {
    expect((await locator.boundingBox()).height).toBeGreaterThanOrEqual(44);
  }
  await expect(page.locator("#variantPreviewTitle")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Перейти к тренировке" })).toBeFocused();
});

test("invalid preview URL is rejected before a material request", async ({ page }) => {
  const materialRequests = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/materials/")) materialRequests.push(request.url());
  });

  await page.goto("/variant-preview.html");

  await expect(page.locator(".variant-preview-state-invalid_request")).toContainText("не указан вариант");
  await expect(page.locator("#variantPreviewTitle")).toBeFocused();
  expect(materialRequests).toEqual([]);
});
