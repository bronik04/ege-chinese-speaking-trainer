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

test("owner scores queued review without groups, assignments, or comments", async ({ browser }) => {
  const stamp = Date.now();
  const teacher = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const studentPage = await student.newPage();
  const teacherPage = await teacher.newPage();
  try {
    await signInAsOwner(teacher);
    await installRecorder(studentPage);
    await studentPage.goto("/");
    await registerStudent(studentPage, stamp);
    await studentPage.locator("#fastMode").check({ force: true });
    await finishTask(studentPage, 2);
    await studentPage.getByRole("button", { name: "Отправить одно задание" }).click();
    await expect(studentPage.locator("#reviewRequestMessage")).toContainText("отправлена");

    await teacherPage.goto("/");
    await teacherPage.locator("#authButton").click();
    await expect(teacherPage.locator("#authModal")).not.toHaveClass(/hidden/);
    await teacherPage.getByRole("button", { name: "Открыть кабинет преподавателя" }).click();
    await expect(teacherPage.getByRole("dialog", { name: "Очередь разбора" })).toBeVisible();
    await teacherPage.locator("#reviewStudentFilter").fill(`student-${stamp}@example.test`);
    await teacherPage.getByRole("button", { name: "Применить" }).click();
    await expect(teacherPage.locator("#teacherReviewRequests")).toContainText("E2E Student");
    await expect(teacherPage.locator("#teacherReviewRequests audio")).toHaveCount(1);
    await teacherPage.locator('[name="task-2-content"]').fill("3");
    await teacherPage.locator('[name="task-2-organization"]').fill("2");
    await teacherPage.locator('[name="task-2-language"]').fill("2");
    await teacherPage.getByRole("button", { name: "Сохранить оценку" }).click();
    await expect(teacherPage.locator("#teacherReviewRequests")).toContainText("7/7");

    await studentPage.reload();
    await studentPage.locator("#authButton").click();
    await expect(studentPage.locator("#studentReviewRequestsList")).toContainText("Разобрано: 7/7");
    await expect(teacherPage.getByRole("button", { name: "Создать группу" })).toHaveCount(0);
    await expect(teacherPage.getByRole("button", { name: "Назначить" })).toHaveCount(0);
    await expect(teacherPage.getByLabel("Комментарий")).toHaveCount(0);
  } finally {
    await teacher.close();
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

test("student starts a new run after a failed upload without reusing its review request", async ({ browser }) => {
  const stamp = Date.now();
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const page = await student.newPage();
  const createdRequests = [];
  const recordingUrls = [];
  let rejectUpload = true;
  await page.route("**/api/review-requests", route => {
    if (route.request().method() === "POST") createdRequests.push(route.request().postDataJSON());
    return route.continue();
  });
  await page.route("**/api/review-requests/*/recordings?*", route => {
    recordingUrls.push(route.request().url());
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

    await page.locator("#restartBtn").click();
    await finishTask(page, 3);
    await page.getByRole("button", { name: "Отправить одно задание" }).click();
    await expect(page.locator("#reviewRequestMessage")).toContainText("отправлена");

    expect(createdRequests).toHaveLength(2);
    expect(createdRequests.map(request => request.tasks)).toEqual([[2], [3]]);
    expect(recordingUrls).toHaveLength(2);
    expect(recordingUrls[0]).toContain("task=2");
    expect(recordingUrls[1]).toContain("task=3");
    expect(new URL(recordingUrls[0]).pathname).not.toBe(new URL(recordingUrls[1]).pathname);
  } finally {
    await student.close();
  }
});

test("concurrent runs keep delayed uploads and completion on their own review requests", async ({ browser }) => {
  const stamp = Date.now();
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const page = await student.newPage();
  const recordingUrls = [];
  let signalFirstUpload;
  let releaseFirstUpload;
  const firstUploadStarted = new Promise(resolve => { signalFirstUpload = resolve; });
  const firstUploadRelease = new Promise(resolve => { releaseFirstUpload = resolve; });
  let holdFirstUpload = true;
  await page.route("**/api/review-requests/*/recordings?*", async route => {
    const url = route.request().url();
    recordingUrls.push(url);
    if (holdFirstUpload && url.includes("task=2")) {
      holdFirstUpload = false;
      signalFirstUpload();
      await firstUploadRelease;
    }
    await route.continue();
  });
  try {
    await installRecorder(page);
    await page.goto("/");
    await registerStudent(page, stamp);
    await page.locator("#fastMode").check({ force: true });
    await finishTask(page, 2);
    await page.getByRole("button", { name: "Отправить одно задание" }).click();
    await firstUploadStarted;

    await page.locator("#restartBtn").click();
    await finishTask(page, 3);
    await page.getByRole("button", { name: "Отправить одно задание" }).click();
    await expect(page.locator("#reviewRequestMessage")).toContainText("отправлена");

    releaseFirstUpload();
    await expect.poll(async () => {
      const payload = await (await student.request.get("/api/student/review-requests")).json();
      return payload.requests.filter(request => request.status === "queued").length;
    }).toBe(2);

    expect(recordingUrls).toHaveLength(2);
    expect(recordingUrls[0]).toContain("task=2");
    expect(recordingUrls[1]).toContain("task=3");
    expect(new URL(recordingUrls[0]).pathname).not.toBe(new URL(recordingUrls[1]).pathname);
  } finally {
    releaseFirstUpload?.();
    await student.close();
  }
});
