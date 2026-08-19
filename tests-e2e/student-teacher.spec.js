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

test("student submits audio and teacher reviews it", async ({ browser }) => {
  const stamp = Date.now();
  const teacher = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  const student = await browser.newContext({ baseURL: "http://127.0.0.1:8091" });
  await signInAsOwner(teacher);
  await post(student, "/api/auth/register", {
    email: `student-${stamp}@example.test`, password: "password123", displayName: "E2E Student",
  });
  const group = await post(teacher, "/api/teacher/groups", { name: "E2E Group" });
  await post(student, "/api/groups/join", { code: group.group.code });
  const assignment = await post(teacher, "/api/teacher/assignments", {
    groupId: group.group.id, title: "E2E speaking task", variantId: "demo-2026", tasks: [2], dueAt: null,
  });
  const submission = await post(student, `/api/assignments/${assignment.assignment.id}/submissions`, {
    run: { id: `e2e-${stamp}`, status: "completed", completedTasks: [2] },
  });

  const audioPath = path.join(os.tmpdir(), `ege-e2e-${stamp}.webm`);
  execFileSync("ffmpeg", ["-loglevel", "error", "-f", "lavfi", "-i", "anullsrc", "-t", "1", "-c:a", "libopus", "-y", audioPath]);
  try {
    const upload = await student.request.post(
      `/api/submissions/${submission.submission.id}/recordings?task=2&label=E2E%20answer`,
      { headers: { ...originHeaders, "Content-Type": "audio/webm" }, data: fs.readFileSync(audioPath) },
    );
    expect(upload.ok(), await upload.text()).toBeTruthy();
  } finally {
    fs.rmSync(audioPath, { force: true });
  }
  const beforeComplete = await teacher.request.get("/api/teacher/submissions");
  expect((await beforeComplete.json()).submissions).toEqual([]);
  await post(student, `/api/submissions/${submission.submission.id}/complete`, {});

  const page = await teacher.newPage();
  await page.goto("/");
  await page.locator("#authButton").click();
  await page.locator("#teacherCabinetBtn").click();
  await expect(page.locator("#teacherSubmissions")).toContainText("E2E Student");
  const audio = page.locator("#teacherSubmissions audio");
  await expect(audio).toHaveCount(1);
  const audioResponse = await teacher.request.get(await audio.getAttribute("src"));
  expect(audioResponse.headers()["content-type"]).toContain("audio/webm");
  await page.locator('[name="task-2-content"]').fill("3");
  await page.locator('[name="task-2-organization"]').fill("2");
  await page.locator('[name="task-2-language"]').fill("2");
  await page.locator('[name="comment"]').fill("E2E review completed");
  await page.locator("[data-review-submission] button[type=submit]").click();
  await expect(page.locator("#toast")).toContainText("7/7");
  await teacher.close();
  await student.close();
});
