import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const baseURL = "http://127.0.0.1:8091";

async function post(context, url, data) {
  const response = await context.request.post(url, { headers: originHeaders, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function register(context, email, role = "student") {
  return post(context, "/api/auth/register", {
    email,
    password: "original123",
    displayName: role === "teacher" ? "E2E Teacher" : "E2E Student",
    role,
  });
}

async function tokenFromOutbox(email, parameter) {
  const outbox = path.join(process.env.E2E_DATA_DIR, "outbox.log");
  let token = null;
  await expect.poll(() => {
    if (!fs.existsSync(outbox)) return null;
    const messages = fs.readFileSync(outbox, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
    const message = messages.findLast(item => item.to === email && item.body.includes(`?${parameter}=`));
    if (!message) return null;
    const url = message.body.trim().split("\n").at(-1);
    token = new URL(url).searchParams.get(parameter);
    return token;
  }).not.toBeNull();
  return token;
}

test("student resets a password through the emailed token", async ({ browser }) => {
  const email = `reset-${Date.now()}@example.test`;
  const account = await browser.newContext({ baseURL });
  await register(account, email);
  await post(account, "/api/auth/password/request", { email });
  const token = await tokenFromOutbox(email, "reset");
  await post(account, "/api/auth/password/reset", { token, password: "replacement123" });

  const login = await browser.newContext({ baseURL });
  const oldPassword = await login.request.post("/api/auth/login", {
    headers: originHeaders,
    data: { email, password: "original123" },
  });
  expect(oldPassword.status()).toBe(401);
  expect((await oldPassword.json()).code).toBe("invalid_credentials");
  await post(login, "/api/auth/login", { email, password: "replacement123" });
  await account.close();
  await login.close();
});

test("student deletes the account and can no longer sign in", async ({ browser }) => {
  const email = `delete-${Date.now()}@example.test`;
  const account = await browser.newContext({ baseURL });
  await register(account, email);
  const deletion = await account.request.delete("/api/account", {
    headers: originHeaders,
    data: { password: "original123" },
  });
  expect(deletion.ok(), await deletion.text()).toBeTruthy();

  const login = await browser.newContext({ baseURL });
  const response = await login.request.post("/api/auth/login", {
    headers: originHeaders,
    data: { email, password: "original123" },
  });
  expect(response.status()).toBe(401);
  expect((await response.json()).code).toBe("invalid_credentials");
  await account.close();
  await login.close();
});

test("teacher resends an assignment as a separate work item", async ({ browser }) => {
  const stamp = Date.now();
  const teacher = await browser.newContext({ baseURL });
  const student = await browser.newContext({ baseURL });
  await register(teacher, `resend-teacher-${stamp}@example.test`, "teacher");
  await register(student, `resend-student-${stamp}@example.test`);
  const group = await post(teacher, "/api/teacher/groups", { name: "Resend E2E Group" });
  await post(student, "/api/groups/join", { code: group.group.code });
  const original = await post(teacher, "/api/teacher/assignments", {
    groupId: group.group.id,
    title: "Original assignment",
    variantId: "demo-2026",
    tasks: [1, 2, 3],
    dueAt: null,
  });
  const repeated = await post(teacher, `/api/teacher/assignments/${original.assignment.id}/resend`, {});

  const teacherItems = await (await teacher.request.get("/api/teacher/assignments")).json();
  const studentItems = await (await student.request.get("/api/student/assignments")).json();
  expect(repeated.assignment.id).not.toBe(original.assignment.id);
  expect(teacherItems.assignments).toHaveLength(2);
  expect(teacherItems.assignments.find(item => item.id === repeated.assignment.id).sourceAssignmentId)
    .toBe(original.assignment.id);
  expect(studentItems.assignments).toHaveLength(2);
  await teacher.close();
  await student.close();
});
