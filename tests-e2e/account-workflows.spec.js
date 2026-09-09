import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const originHeaders = { Origin: "http://127.0.0.1:8091", "Sec-Fetch-Site": "same-origin" };
const baseURL = "http://127.0.0.1:8091";
const ownerEmail = "owner@example.test";

async function post(context, url, data) {
  const response = await context.request.post(url, { headers: originHeaders, data });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function register(context, email, displayName = "E2E Student") {
  return post(context, "/api/auth/register", {
    email,
    password: "original123",
    displayName,
  });
}

async function registerOwner(context, { confirm = true } = {}) {
  const result = await register(context, ownerEmail, "E2E Teacher");
  expect(result.user.role).toBe("teacher");
  if (confirm) {
    const token = await tokenFromOutbox(ownerEmail, "verify");
    await post(context, "/api/auth/email/confirm", { token });
  }
  return result;
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

test("student registers, signs out and signs back in through the account form", async ({ page }) => {
  const email = `ui-login-${Date.now()}@example.test`;
  await page.goto("/");
  await page.locator("#authButton").click();
  await expect(page.locator("#registrationArchiveDisclosure")).toBeHidden();
  await page.locator("#registerTab").click();
  await expect(page.locator("#registrationArchiveDisclosure")).toBeVisible();
  await expect(page.locator("#registrationArchiveDisclosure")).toHaveText("Ответы сохраняются в личном архиве на 6 месяцев, затем удаляются автоматически.");
  await page.locator("#authName").fill("UI Student");
  await page.locator("#authEmail").fill(email);
  await page.locator("#authPassword").fill("original123");
  await expect(page.locator("#authRole")).toHaveCount(0);
  await page.locator("#authSubmitBtn").click();
  await expect(page.locator("#authButtonText")).toHaveText(email);

  await page.locator("#authButton").click();
  await page.locator("#logoutBtn").click();
  await expect(page.locator("#authButtonText")).toHaveText("Войти");

  await page.locator("#authButton").click();
  await page.locator("#loginTab").click();
  await expect(page.locator("#registrationArchiveDisclosure")).toBeHidden();
  await page.locator("#authEmail").fill(email);
  await page.locator("#authPassword").fill("original123");
  await page.locator("#authSubmitBtn").click();
  await expect(page.locator("#authButtonText")).toHaveText(email);
});

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

test("student account links to a separate security page", async ({ page }) => {
  const email = `security-page-${Date.now()}@example.test`;
  await register(page.context(), email, "Security Student");

  await page.goto("/");
  await page.locator("#authButton").click();
  await expect(page.locator("#emailVerificationPanel")).toBeVisible();
  await expect(page.locator("#accountSecurityLink")).toHaveAttribute("href", "security.html");
  await expect(page.locator("#showAuditBtn, #showDeleteAccountBtn, #deleteAccountForm")).toHaveCount(0);

  await page.locator("#accountSecurityLink").click();
  await expect(page).toHaveURL(/\/security\.html$/);
  await expect(page.getByRole("heading", { name: "Безопасность аккаунта" })).toBeVisible();
  await expect(page.locator("#securityAccountEmail")).toHaveText(email);
  await expect(page.locator("#auditList")).toContainText("Аккаунт создан");
});

test("unverified student requests verification from the account notice", async ({ page }) => {
  const email = `verification-notice-${Date.now()}@example.test`;
  await register(page.context(), email);

  await page.goto("/");
  await page.locator("#authButton").click();
  await page.locator("#sendVerificationBtn").click();

  await expect(page.locator("#emailVerificationMessage")).toHaveText("Локальная ссылка сохранена в var/outbox.log");
});

test("student deletes the account from the security page", async ({ page }) => {
  const email = `security-delete-${Date.now()}@example.test`;
  await register(page.context(), email);

  await page.goto("/security.html");
  await expect(page.locator("#deleteAccountForm")).toBeHidden();
  await page.locator("#showDeleteAccountBtn").click();
  await expect(page.locator("#deleteAccountForm")).toBeVisible();
  await page.locator("#deleteAccountPassword").fill("original123");
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#deleteAccountForm").getByRole("button", { name: "Удалить аккаунт навсегда" }).click();

  await expect(page.getByRole("heading", { name: "Аккаунт удалён" })).toBeVisible();
  await expect(page.locator("#securityAccount")).toBeHidden();
  await expect(page.locator("#securityDeleted")).toBeFocused();
  await expect(page.locator("[data-account-label]")).toHaveText("Войти");
});

test("security page visually separates routine and destructive controls", async ({ page }) => {
  await register(page.context(), `security-layout-${Date.now()}@example.test`);
  await page.goto("/security.html");

  await expect(page.locator("#securityAccount")).toHaveCSS("display", "grid");
  await expect(page.locator("#showDeleteAccountBtn")).toHaveCSS("background-color", "rgb(255, 245, 242)");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("unverified owner cannot open privileged APIs", async ({ browser }) => {
  const teacher = await browser.newContext({ baseURL });
  await registerOwner(teacher, { confirm: false });
  const response = await teacher.request.get("/api/teacher/review-requests");
  expect(response.status()).toBe(403);
  expect((await response.json()).code).toBe("email_verification_required");
  const deletion = await teacher.request.delete("/api/account", {
    headers: originHeaders,
    data: { password: "original123" },
  });
  expect(deletion.ok(), await deletion.text()).toBeTruthy();
  await teacher.close();
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

test("student and owner cabinets have no assignment controls", async ({ browser }) => {
  const stamp = Date.now();
  const teacher = await browser.newContext({ baseURL });
  const student = await browser.newContext({ baseURL });
  await registerOwner(teacher);
  await register(student, `controls-student-${stamp}@example.test`);
  const teacherPage = await teacher.newPage();
  const studentPage = await student.newPage();
  await teacherPage.goto("/");
  await studentPage.goto("/");
  await teacherPage.locator("#authButton").click();
  await teacherPage.locator("#teacherCabinetBtn").click();
  await studentPage.locator("#authButton").click();
  await expect(studentPage.locator("#logoutBtn")).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(studentPage.locator("#logoutBtn")).toHaveCSS("box-shadow", "none");
  await expect(studentPage.locator("#accountSecurityLink")).toBeVisible();
  await expect(teacherPage.locator("#teacherMaterialEditorLink")).toBeVisible();
  await expect(teacherPage.locator("#teacherMaterialEditorLink")).toHaveAttribute("href", "variant-editor.html");
  await expect(teacherPage.locator("#teacherModal .teacher-dialog")).toHaveCSS("border-radius", "16px");
  await expect(teacherPage.locator("#teacherModal .teacher-materials-entry")).toHaveCSS("border-radius", "16px");
  await expect(teacherPage.locator("#reviewRequestFilters")).toHaveCSS("border-radius", "12px");
  await teacherPage.setViewportSize({ width: 390, height: 844 });
  expect(await teacherPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  for (const selector of ["#reviewTaskFilter", "#reviewStatusFilter"]) {
    await expect(teacherPage.locator(selector)).toBeVisible();
    await expect(teacherPage.locator(selector)).toHaveCSS("min-height", "44px");
  }
  await expect(teacherPage.locator(".project-select")).toHaveCount(0);
  for (const page of [teacherPage, studentPage]) {
    await expect(page.locator("#groupName, #joinGroupCode, #assignmentDue, #createAssignmentBtn, #exportCsvBtn, #exportPdfBtn")).toHaveCount(0);
    await expect(page.locator("[data-copy-code], [data-resend-assignment], [data-start-assignment]")).toHaveCount(0);
    await expect(page.locator("text=/Код группы|Назначить|Срок|Выдать повторно|CSV|PDF/")).toHaveCount(0);
  }
  await teacher.close();
  await student.close();
});
