import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const baseURL = "http://127.0.0.1:8091";
let publishedSlug = null;

test.describe.configure({ mode: "serial" });

async function post(context, url, data) {
  const response = await context.request.post(url, { headers: originHeaders, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function verificationToken(email) {
  const outbox = path.join(process.env.E2E_DATA_DIR, "outbox.log");
  let token = null;
  await expect.poll(() => {
    if (!fs.existsSync(outbox)) return null;
    const messages = fs.readFileSync(outbox, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
    const message = messages.findLast(item => item.to === email && item.body.includes("?verify="));
    token = message ? new URL(message.body.trim().split("\n").at(-1)).searchParams.get("verify") : null;
    return token;
  }).not.toBeNull();
  return token;
}

test("guest catalog exposes only the open 2026 variant", async ({ page }) => {
  await page.goto("/variants.html");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await expect(page.locator("#createMaterialLink")).toHaveCount(0);
  await page.locator("#variantSearch").fill("официальный");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(/variant=open-2026/);
  await expect(page.locator("#variantSelect")).toHaveValue("open-2026");
});

test("registered user publishes a standalone task and opens it from catalog", async ({ browser }) => {
  const context = await browser.newContext({ baseURL });
  const stamp = Date.now();
  const slug = `e2e-photo-${stamp}`;
  publishedSlug = slug;
  const email = "catalog-author@example.test";
  const registration = await context.request.post("/api/auth/register", {
    headers: originHeaders,
    data: { email, password: "password123", displayName: "Автор", role: "student" },
  });
  expect(registration.ok(), await registration.text()).toBeTruthy();
  const confirmation = await context.request.post("/api/auth/email/confirm", {
    headers: originHeaders,
    data: { token: await verificationToken(email) },
  });
  expect(confirmation.ok(), await confirmation.text()).toBeTruthy();

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
  await page.goto("/");
  await expect(page.locator("#variantSelect option").first()).toHaveValue("open-2026");
  await page.locator("#soundToggle").click();
  await expect(page.locator("#soundToggle")).toHaveAttribute("aria-pressed", "false");
  await page.locator("#authButton").click();
  await expect(page.locator(".account-progress-card")).toBeVisible();
  await expect(page.locator(".progress-row")).toHaveCount(0);
  await page.locator("#authCloseBtn").click();
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
  await expect(page.locator("[data-account-link]")).toContainText(email);
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

test("assigned snapshot opens after the author deletes the source material", async ({ browser }) => {
  const teacher = await browser.newContext({ baseURL });
  const student = await browser.newContext({ baseURL });
  const author = await browser.newContext({ baseURL });
  const teacherEmail = "snapshot-teacher@example.test";
  await post(teacher, "/api/auth/register", {
    email: teacherEmail, password: "password123", displayName: "Snapshot Teacher", role: "teacher",
  });
  await post(teacher, "/api/auth/email/confirm", { token: await verificationToken(teacherEmail) });
  await post(student, "/api/auth/register", {
    email: "snapshot-student@example.test", password: "password123", displayName: "Snapshot Student", role: "student",
  });
  const group = await post(teacher, "/api/teacher/groups", { name: "Snapshot group" });
  await post(student, "/api/groups/join", { code: group.group.code });
  await post(teacher, "/api/teacher/assignments", {
    groupId: group.group.id, title: "Stable snapshot", variantId: publishedSlug, tasks: [2], dueAt: 1,
  });
  await post(author, "/api/auth/login", { email: "catalog-author@example.test", password: "password123" });
  const deleted = await author.request.delete(`/api/materials/${publishedSlug}`, {
    headers: originHeaders,
    data: {},
  });
  expect(deleted.ok(), await deleted.text()).toBeTruthy();

  const assignments = await (await student.request.get("/api/student/assignments")).json();
  expect(assignments.assignments[0].material.id).toBe(publishedSlug);
  expect(assignments.assignments[0].materialUnavailable).toBe(false);
  const snapshotImage = assignments.assignments[0].material.tasks["2"].images[0];
  expect((await student.request.get(snapshotImage)).ok()).toBeTruthy();
  const page = await student.newPage();
  await page.goto("/");
  await page.locator("[data-start-assignment]").click();
  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#modeLabel")).toContainText("задание преподавателя");
  await expect(page.locator("#taskBadge")).toHaveText("Задание 2");
  await Promise.all([teacher.close(), student.close(), author.close()]);
});
