import { expect, test } from "@playwright/test";

test("reference library filters phrases and switches exam tasks", async ({ page }) => {
  await page.goto("/reference.html");
  await expect(page.locator(".reference-tab")).toHaveCount(3);
  await expect(page.locator(".reference-task-head h2")).toHaveText("Пять вопросов");
  await page.locator('[data-reference-task="task-2"]').click();
  await expect(page).toHaveURL(/#task-2$/);
  await expect(page.locator(".reference-task-head h2")).toHaveText("Описание фотографии");
  await expect(page.locator(".example-card")).toHaveCount(1);

  await page.locator("#referenceSearch").fill("скидка");
  await expect(page.locator(".phrase-card")).toHaveCount(2);
  await expect(page.locator(".phrase-card").first()).toContainText("优惠");
});

test("reference link is hidden only during an active task", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#referenceLink")).toBeVisible();
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#referenceLink")).toBeHidden();
});
