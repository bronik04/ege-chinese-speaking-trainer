import { expect, test } from "@playwright/test";

test("reference library filters phrases and switches exam tasks", async ({ page }) => {
  await page.goto("/reference.html");
  await expect(page.locator(".reference-tab")).toHaveCount(3);
  await expect(page.locator(".reference-tab").nth(0)).toHaveClass(/active/);
  await page.locator(".reference-tab").nth(1).hover();
  await expect(page.locator(".reference-tab").nth(1)).not.toHaveCSS("background-color", "rgb(92, 14, 14)");
  await expect(page.locator(".reference-task-head h2")).toHaveText("Пять вопросов");
  await expect(page.locator(".reference-group summary small")).toHaveCount(0);
  await page.locator('[data-reference-task="task-2"]').click();
  await expect(page).toHaveURL(/#task-2$/);
  await expect(page.locator(".reference-task-head h2")).toHaveText("Описание фотографии");
  await expect(page.locator(".example-card")).toHaveCount(1);
  await expect(page.locator(".examples-heading h3")).toHaveText("Примеры ответов");

  await page.locator("#referenceSearch").fill("скидка");
  await expect(page.locator(".phrase-card")).toHaveCount(2);
  await expect(page.locator(".phrase-card").first()).toContainText("优惠");
  await page.locator("#referenceSearch").fill("");
  await page.locator('[data-reference-task="task-3"]').click();
  const introGroup = page.locator(".reference-group").first();
  await expect(introGroup.locator(".phrase-card")).toHaveCount(1);
  const listBox = await introGroup.locator(".phrase-list").boundingBox();
  const cardBox = await introGroup.locator(".phrase-card").boundingBox();
  expect(Math.abs(listBox.width - cardBox.width)).toBeLessThan(2);
});

test("shared account, logo and footer are available across public pages", async ({ page }) => {
  for (const path of ["/variants.html", "/reference.html", "/variant-editor.html"]) {
    await page.goto(path);
    await expect(page.locator(".brand-logo")).toBeVisible();
    await expect(page.locator(".account-btn")).toBeVisible();
    await expect(page.locator(".site-footer")).toBeVisible();
  }
  await page.goto("/reference.html");
  await page.locator("[data-account-link]").click();
  await expect(page.locator("#authModal")).toBeVisible();
});

test("reference link is hidden only during an active task", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#referenceLink")).toBeVisible();
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#referenceLink")).toBeHidden();
});
