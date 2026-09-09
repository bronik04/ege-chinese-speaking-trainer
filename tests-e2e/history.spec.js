import { expect, test } from "@playwright/test";

const guestProgress = {
  version: 2,
  updatedAt: "2026-09-09T10:05:00.000Z",
  settings: { lastVariant: "open-2026", fastMode: false },
  runs: [{
    id: "guest-run",
    variantId: "open-2026",
    variantLabel: "Открытый вариант 2026",
    mode: "practice",
    tasks: [2],
    completedTasks: [2],
    currentTask: 2,
    phase: "answer",
    fastMode: false,
    startedAt: "2026-09-09T10:00:00.000Z",
    status: "completed",
    completedAt: "2026-09-09T10:05:00.000Z",
    recordingsCount: 1,
  }],
  activeRun: null,
};

test("guest history shows only browser-local attempts and invites sign-in", async ({ page }) => {
  const protectedRequests = [];
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (["/api/progress", "/api/personal-recordings", "/api/student/review-requests"].includes(path)) {
      protectedRequests.push(`${request.method()} ${path}`);
    }
  });
  await page.addInitScript(progress => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(progress));
  }, guestProgress);

  const response = await page.goto("/history.html");

  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Моя история" })).toBeVisible();
  await expect(page.locator(".history-entry")).toHaveCount(1);
  await expect(page.locator(".history-entry")).toContainText("Открытый вариант 2026");
  await expect(page.locator("#historyNotice").getByRole("link", { name: /войти/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /очистить историю/i })).toHaveCount(0);
  expect(protectedRequests).toEqual([]);
});

test("every public page links to the dedicated history page", async ({ page }) => {
  for (const path of ["/", "/variants.html", "/reference.html", "/variant-editor.html", "/history.html"]) {
    await page.goto(path);
    const link = page.locator('.site-nav a[href="history.html"]');
    await expect(link).toHaveText("История");
    if (path === "/history.html") await expect(link).toHaveAttribute("aria-current", "page");
  }
});

test("network auth failure keeps guest history visible and reports uncertainty", async ({ page }) => {
  await page.addInitScript(progress => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(progress));
  }, guestProgress);
  await page.route("**/api/auth/me", route => route.abort());

  await page.goto("/history.html");

  await expect(page.locator(".history-entry")).toHaveCount(1);
  await expect(page.locator("#historyNotice")).toContainText("Не удалось проверить вход");
});
