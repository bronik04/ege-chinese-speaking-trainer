import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const ownerEmail = "owner@example.test";

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

async function post(context, url, data) {
  const response = await context.request.post(url, { headers: originHeaders, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function signInAsOwner(context) {
  const registration = await context.request.post("/api/auth/register", {
    headers: originHeaders,
    data: { email: ownerEmail, password: "original123", displayName: "E2E Teacher" },
  });
  if (registration.status() === 201) {
    expect((await registration.json()).user.role).toBe("teacher");
    await post(context, "/api/auth/email/confirm", { token: await verificationToken(ownerEmail) });
    return;
  }
  expect(registration.status(), await registration.text()).toBe(409);
  await post(context, "/api/auth/login", { email: ownerEmail, password: "original123" });
}

function createSampleAudio() {
  const audioPath = path.join(os.tmpdir(), `ege-e2e-${Date.now()}.webm`);
  execFileSync("ffmpeg", ["-loglevel", "error", "-f", "lavfi", "-i", "anullsrc", "-t", "1", "-c:a", "libopus", "-y", audioPath]);
  try {
    return fs.readFileSync(audioPath).toString("base64");
  } finally {
    fs.rmSync(audioPath, { force: true });
  }
}

async function installRecorder(page) {
  await page.addInitScript(audio => {
    class TestMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "inactive"; this.mimeType = "audio/webm"; }
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        const bytes = Uint8Array.from(atob(audio), character => character.charCodeAt(0));
        this.ondataavailable?.({ data: new Blob([bytes], { type: this.mimeType }) });
        this.onstop?.();
      }
    }
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: async () => ({ active: true, getTracks: () => [] }) } });
    Object.defineProperty(window, "MediaRecorder", { value: TestMediaRecorder });
  }, createSampleAudio());
}

async function registerStudent(page, stamp) {
  await page.locator("#authButton").click();
  await page.locator("#registerTab").click();
  await page.locator("#authName").fill("E2E Student");
  await page.locator("#authEmail").fill(`student-${stamp}@example.test`);
  await page.locator("#authPassword").fill("password123");
  await page.locator("#authForm").evaluate(form => form.requestSubmit());
  await expect(page.locator("#authModal")).toHaveClass(/hidden/);
}

async function finishTask(page, task) {
  await page.locator(`[data-start="${task}"]`).click();
  await page.locator("#mainActionBtn").click();
  await page.locator("#skipBtn").click();
  await page.locator("#skipBtn").click();
  await expect(page.locator("#resultScreen")).not.toHaveClass(/hidden/);
}

async function finishCompleteAttempt(page) {
  await page.locator('[data-start="exam"]').click();
  await page.locator("#mainActionBtn").click();
  await page.locator("#skipBtn").click();
  for (let question = 0; question < 5; question += 1) await page.locator("#skipBtn").click();
  for (const task of [2, 3]) {
    await expect(page.locator("#taskBadge")).toHaveText(`Задание ${task}`);
    await page.locator("#mainActionBtn").click();
    await page.locator("#skipBtn").click();
    await page.locator("#skipBtn").click();
  }
  await expect(page.locator("#resultScreen")).not.toHaveClass(/hidden/);
}

test("student submits a single task only after an explicit review request", async ({ browser }) => {
  const stamp = Date.now();
  const teacher = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  await signInAsOwner(teacher);
  const page = await student.newPage();
  try {
    await installRecorder(page);
    await page.goto("/");
    await registerStudent(page, stamp);
    await page.locator("#fastMode").check({ force: true });
    await finishTask(page, 2);
    expect((await (await teacher.request.get("/api/teacher/review-requests")).json()).requests).toEqual([]);
    await page.getByLabel("Одно задание").check();
    await page.locator("#reviewTaskSelect").selectOption("2");
    await page.getByRole("button", { name: "Отправить одно задание" }).click();
    await expect(page.locator("#reviewRequestMessage")).toContainText("отправлена");
    await expect.poll(async () => (await (await teacher.request.get("/api/teacher/review-requests")).json()).requests.length).toBe(1);
  } finally {
    await teacher.close();
    await student.close();
  }
});

test("student submits a complete attempt with every completed task", async ({ browser }) => {
  const stamp = Date.now();
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const page = await student.newPage();
  try {
    await installRecorder(page);
    await page.goto("/");
    await registerStudent(page, stamp);
    await page.locator("#fastMode").check({ force: true });
    await finishCompleteAttempt(page);
    await page.getByLabel("Всю попытку").check();
    await page.getByRole("button", { name: "Отправить всю попытку" }).click();
    await expect(page.locator("#studentReviewRequestsList .review-request-card")).toHaveCount(1);
    await expect(page.locator("#studentReviewRequestsList")).toContainText("Задания 1, 2, 3");
  } finally {
    await student.close();
  }
});

test("student retries a failed upload without creating a duplicate review request", async ({ browser }) => {
  const stamp = Date.now();
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const page = await student.newPage();
  let createdRequests = 0;
  let rejectUpload = true;
  await page.route("**/api/review-requests", route => {
    if (route.request().method() === "POST") createdRequests += 1;
    return route.continue();
  });
  await page.route("**/api/review-requests/*/recordings?*", route => {
    if (rejectUpload) {
      rejectUpload = false;
      return route.abort();
    }
    return route.continue();
  });
  try {
    await installRecorder(page);
    await page.goto("/");
    await registerStudent(page, stamp);
    await page.locator("#fastMode").check({ force: true });
    await finishTask(page, 2);
    await page.getByRole("button", { name: "Отправить одно задание" }).click();
    await expect(page.getByRole("button", { name: "Повторить отправку" })).toBeVisible();
    await page.getByRole("button", { name: "Повторить отправку" }).click();
    await expect(page.locator("#reviewRequestMessage")).toContainText("отправлена");
    expect(createdRequests).toBe(1);
    await expect(page.getByRole("button", { name: "Отправить одно задание" })).toBeDisabled();
  } finally {
    await student.close();
  }
});
