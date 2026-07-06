import { expect, test } from "@playwright/test";
import fs from "node:fs";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const baseURL = "http://127.0.0.1:8091";

test("guest catalog exposes only the open 2026 variant", async ({ page }) => {
  await page.goto("/variants.html");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await expect(page.locator("#createMaterialLink")).toHaveCount(0);
  await page.locator("#variantSearch").fill("открытый");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(/variant=open-2026/);
  await expect(page.locator("#variantSelect")).toHaveValue("open-2026");
});

test("registered user publishes a standalone task and opens it from catalog", async ({ browser }) => {
  const context = await browser.newContext({ baseURL });
  const stamp = Date.now();
  const slug = `e2e-photo-${stamp}`;
  const registration = await context.request.post("/api/auth/register", {
    headers: originHeaders,
    data: { email: `${slug}@example.test`, password: "password123", displayName: "Автор", role: "student" },
  });
  expect(registration.ok(), await registration.text()).toBeTruthy();

  const draft = {
    slug, kind: "task", taskNumber: 2, title: "Авторское описание фотографии", year: 2027,
    source: "E2E автор", content: { "2": { images: ["", "", ""] } },
  };
  const created = await context.request.post("/api/materials", { headers: originHeaders, data: draft });
  expect(created.ok(), await created.text()).toBeTruthy();
  const photo = fs.readFileSync("assets/variants/2026/candidate-03.webp");
  const uploaded = await context.request.post(`/api/materials/${slug}/assets`, {
    headers: { ...originHeaders, "Content-Type": "image/webp" }, data: photo,
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  const assetUrl = (await uploaded.json()).asset.url;
  draft.content["2"].images = [assetUrl, assetUrl, assetUrl];
  const updated = await context.request.put(`/api/materials/${slug}`, { headers: originHeaders, data: draft });
  expect(updated.ok(), await updated.text()).toBeTruthy();
  const published = await context.request.post(`/api/materials/${slug}/publish`, { headers: originHeaders, data: {} });
  expect(published.ok(), await published.text()).toBeTruthy();

  const page = await context.newPage();
  await page.goto("/variants.html");
  await expect(page.locator("#createMaterialLink")).toHaveCount(0);
  await page.locator("#variantSearch").fill("Авторское описание");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await expect(page.locator(".variant-kind")).toHaveText("Отдельное задание 2");
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(new RegExp(`variant=${slug}`));
  await expect(page.locator("#variantSelect")).toHaveValue(slug);
  await expect(page.locator("#variantSelect + .project-select-trigger .project-select-value")).toHaveCSS("white-space", "nowrap");

  await page.goto("/variant-editor.html");
  await expect(page.locator("#editorTitle")).toHaveText("Новый материал");
  await expect(page.locator("select:not([data-project-select='ready'])")).toHaveCount(0);
  await page.locator(".project-select-trigger").first().click();
  const materialMenu = page.locator(".project-select-menu").first();
  await expect(materialMenu).toBeVisible();
  const selectedOption = materialMenu.locator('[aria-selected="true"]');
  await materialMenu.locator('[data-value="task"]').hover();
  await expect(selectedOption).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await page.locator('.project-select-option[data-value="task"]').click();
  await expect(page.locator("#materialKind")).toHaveValue("task");
  await expect(page.locator("#taskNumberField")).toBeVisible();
  await expect(page.locator("#materialTitle")).toHaveCSS("font-family", /Georgia/);
  await context.close();
});
