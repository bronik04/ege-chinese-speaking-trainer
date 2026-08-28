import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const baseURL = "http://127.0.0.1:8091";
const ownerEmail = "owner@example.test";
let publishedSlug = null;

test.describe.configure({ mode: "serial" });

async function post(context, url, data) {
  const response = await context.request.post(url, { headers: originHeaders, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

function createSampleAudio() {
  const audioPath = path.join(os.tmpdir(), `ege-catalog-${Date.now()}.webm`);
  execFileSync("ffmpeg", ["-loglevel", "error", "-f", "lavfi", "-i", "anullsrc", "-t", "1", "-c:a", "libopus", "-y", audioPath]);
  try {
    return fs.readFileSync(audioPath);
  } finally {
    fs.rmSync(audioPath, { force: true });
  }
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

async function signInAsOwner(context) {
  const registration = await context.request.post("/api/auth/register", {
    headers: originHeaders,
    data: { email: ownerEmail, password: "original123", displayName: "Snapshot Teacher" },
  });
  if (registration.status() === 201) {
    expect((await registration.json()).user.role).toBe("teacher");
    await post(context, "/api/auth/email/confirm", { token: await verificationToken(ownerEmail) });
    return;
  }
  expect(registration.status(), await registration.text()).toBe(409);
  await post(context, "/api/auth/login", { email: ownerEmail, password: "original123" });
}

test("guest catalog exposes only the open 2026 variant", async ({ page }) => {
  await page.goto("/variants.html");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await expect(page.locator("#catalogAccessNotice")).toHaveText("После регистрации доступны остальные варианты и личный архив записей Зарегистрироваться →");
  await expect(page.locator(".catalog-panel")).toHaveCSS("border-radius", "16px");
  await expect(page.locator(".year-filter").first()).toHaveCSS("border-radius", "999px");
  await expect(page.locator("#createMaterialLink")).toHaveCount(0);
  await page.locator("#variantSearch").fill("официальный");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(/variant=open-2026/);
  await expect(page.locator("#variantSelect")).toHaveValue("open-2026");
  await expect(page.locator("#materialList [role='radio']")).toHaveCount(1);
  await expect(page.locator("#materialList [role='radio'][aria-checked='true']")).toContainText("Официальный вариант 2026");
  await expect(page.locator("#materialAccessNotice")).toHaveText("После регистрации доступны остальные варианты и личный архив записей Зарегистрироваться →");
});

test("registered user publishes a standalone task and opens it from catalog", async ({ browser }) => {
  const context = await browser.newContext({ baseURL });
  const stamp = Date.now();
  const slug = `e2e-photo-${stamp}`;
  publishedSlug = slug;
  const email = "catalog-author@example.test";
  const registration = await context.request.post("/api/auth/register", {
    headers: originHeaders,
    data: { email, password: "password123", displayName: "Автор" },
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
  const photo = fs.readFileSync("public/assets/variants/2026/candidate-03.webp");
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
  await expect(page.locator("#materialAccessNotice")).toBeHidden();
  await page.locator("#soundToggle").click();
  await expect(page.locator("#soundToggle")).toHaveAttribute("aria-pressed", "false");
  await page.locator("#authButton").click();
  await expect(page.locator(".account-progress-card")).toBeVisible();
  await expect(page.locator(".progress-row")).toHaveCount(0);
  await page.locator("#authCloseBtn").click();
  await page.goto("/variants.html");
  await expect(page.locator("#catalogAccessNotice")).toHaveCount(0);
  await expect(page.locator("#createMaterialLink")).toHaveCount(0);
  await page.locator("#variantSearch").fill("Авторское описание");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await expect(page.locator(".variant-kind")).toHaveText("Отдельное задание 2");
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(new RegExp(`variant=${slug}`));
  await expect(page.locator("#variantSelect")).toHaveValue(slug);
  await expect(page.locator(`#materialList [role='radio'][data-value='${slug}']`)).toHaveAttribute("aria-checked", "true");

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

test("direct review request preserves its material snapshot after the author deletes the source material", async ({ browser }) => {
  const teacher = await browser.newContext({ baseURL });
  const student = await browser.newContext({ baseURL });
  const author = await browser.newContext({ baseURL });
  const stamp = Date.now();
  const slug = `direct-review-${stamp}`;
  const authorEmail = "catalog-author@example.test";
  const authorRegistration = await author.request.post("/api/auth/register", { headers: originHeaders, data: {
    email: authorEmail, password: "password123", displayName: "Direct Review Author",
  }});
  if (authorRegistration.status() === 201) {
    await post(author, "/api/auth/email/confirm", { token: await verificationToken(authorEmail) });
  } else {
    expect(authorRegistration.status(), await authorRegistration.text()).toBe(409);
    await post(author, "/api/auth/login", { email: authorEmail, password: "password123" });
  }
  await post(author, "/api/materials", {
    slug, kind: "task", taskNumber: 2, title: "Direct review snapshot", year: 2027,
    source: "E2E author", content: { "2": { images: ["", "", ""] } },
  });
  const photo = fs.readFileSync("public/assets/variants/2026/candidate-03.webp");
  const uploaded = await author.request.post(`/api/materials/${slug}/assets`, {
    headers: { ...originHeaders, "Content-Type": "image/webp" }, data: photo,
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  const assetUrl = (await uploaded.json()).asset.url;
  await author.request.put(`/api/materials/${slug}`, {
    headers: originHeaders,
    data: {
      slug, kind: "task", taskNumber: 2, title: "Direct review snapshot", year: 2027,
      source: "E2E author", content: { "2": { images: [assetUrl, assetUrl, assetUrl] } },
    },
  });
  await post(author, `/api/materials/${slug}/publish`, {});
  await signInAsOwner(teacher);
  await post(student, "/api/auth/register", {
    email: `direct-review-student-${stamp}@example.test`, password: "password123", displayName: "Snapshot Student",
  });
  const review = await post(student, "/api/review-requests", {
    kind: "task",
    variantId: slug,
    tasks: [2],
    run: { id: `direct-review-${Date.now()}`, status: "completed", completedTasks: [2] },
  });
  const recording = await student.request.post(`/api/review-requests/${review.reviewRequest.id}/recordings?task=2&label=Answer`, {
    headers: { ...originHeaders, "Content-Type": "audio/webm" }, data: createSampleAudio(),
  });
  expect(recording.ok(), await recording.text()).toBeTruthy();
  await post(student, `/api/review-requests/${review.reviewRequest.id}/complete`, {});
  const deleted = await author.request.delete(`/api/materials/${slug}`, {
    headers: originHeaders,
    data: {},
  });
  expect(deleted.ok(), await deleted.text()).toBeTruthy();

  const teacherRequests = await (await teacher.request.get("/api/teacher/review-requests")).json();
  const request = teacherRequests.requests.find(item => item.id === review.reviewRequest.id);
  expect(request.items[0].task).toBe(2);
  expect(request.items[0].recordings).toHaveLength(1);
  expect((await teacher.request.get(request.items[0].recordings[0].url)).ok()).toBeTruthy();
  await Promise.all([teacher.close(), student.close(), author.close()]);
});
