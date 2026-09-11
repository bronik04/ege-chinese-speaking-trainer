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

const studentUser = {
  id: 17,
  email: "history-student@example.test",
  displayName: "History Student",
  role: "student",
  emailVerified: true,
};

const studentProgress = {
  ...guestProgress,
  runs: [{ ...guestProgress.runs[0], id: "student-run" }],
};

async function installStudentHistoryApi(page, { recordings, getReviews, progress = studentProgress }) {
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: studentUser } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true, updatedAt: 1_788_950_000 } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => route.fulfill({ json: { recordings } }));
  await page.route("**/api/student/review-requests", route => route.fulfill({ json: { requests: getReviews() } }));
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${studentUser.id}`,
    progress,
  });
}

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
  await expect(page.locator("#historyCompareBar")).toBeHidden();
  await expect(page.locator("[data-compare-run]")).toHaveCount(0);
  expect(protectedRequests).toEqual([]);
});

test("student selects exactly two compatible completed attempts", async ({ page }) => {
  const baseRun = guestProgress.runs[0];
  const comparisonProgress = {
    ...studentProgress,
    runs: [{
      ...baseRun,
      id: "task-2-a",
      variantLabel: "Попытка 2A",
      completedAt: "2026-09-09T10:05:00.000Z",
    }, {
      ...baseRun,
      id: "task-2-b",
      variantId: "demo-2025",
      variantLabel: "Попытка 2B",
      startedAt: "2026-09-08T10:00:00.000Z",
      completedAt: "2026-09-08T10:05:00.000Z",
    }, {
      ...baseRun,
      id: "task-3",
      variantLabel: "Попытка 3",
      tasks: [3],
      completedTasks: [3],
      currentTask: 3,
      startedAt: "2026-09-07T10:00:00.000Z",
      completedAt: "2026-09-07T10:05:00.000Z",
    }, {
      ...baseRun,
      id: "task-2-c",
      variantLabel: "Попытка 2C",
      startedAt: "2026-09-06T12:00:00.000Z",
      completedAt: "2026-09-06T12:05:00.000Z",
    }, {
      ...baseRun,
      id: "interrupted-2",
      variantLabel: "Прерванная попытка 2",
      completedTasks: [],
      status: "interrupted",
      startedAt: "2026-09-06T10:00:00.000Z",
      completedAt: "2026-09-06T10:05:00.000Z",
    }],
  };
  await installStudentHistoryApi(page, {
    recordings: [],
    getReviews: () => [],
    progress: comparisonProgress,
  });

  await page.goto("/history.html");

  const compareBar = page.locator("#historyCompareBar");
  await expect(compareBar).toBeVisible();
  await expect(page.locator("[data-compare-run]")).toHaveCount(4);
  await expect(page.locator('[data-history-key="run:interrupted-2"]')).toContainText("Прервано");

  await page.locator('[data-compare-run="task-2-a"]').click();

  await expect(page.locator('[data-compare-run="task-2-a"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-compare-run="task-3"]')).toBeDisabled();
  await expect(page.locator('[data-compare-run="task-3"] + .history-compare-reason')).toContainText("одинаковыми заданиями");
  await expect(page.locator("#historyCompareBtn")).toBeDisabled();

  await page.locator('[data-compare-run="task-2-b"]').click();

  await expect(page.locator("#historyCompareStatus")).toContainText("Выбрано 2 из 2");
  await expect(page.locator("#historyCompareBtn")).toBeEnabled();
  await expect(page.locator('[data-compare-run="task-2-c"]')).toBeDisabled();
  await expect(page.locator('[data-compare-run="task-2-c"] + .history-compare-reason')).toContainText("Сначала снимите выбор");
  await page.locator("#historyCompareBtn").click();
  await expect(page).toHaveURL(/\/compare\.html\?left=task-2-a&right=task-2-b$/);
});

test("teacher history does not offer attempt comparison", async ({ page }) => {
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: {
    id: 1,
    email: "owner@example.test",
    displayName: "Owner",
    role: "teacher",
    emailVerified: true,
  } } }));

  await page.goto("/history.html");

  await expect(page.locator("#historyCompareBar")).toBeHidden();
  await expect(page.locator("[data-compare-run]")).toHaveCount(0);
});

test("every public page links to the dedicated history page", async ({ page }) => {
  for (const path of ["/", "/variants.html", "/reference.html", "/variant-editor.html", "/history.html"]) {
    await page.goto(path);
    const link = page.locator('.site-nav a[href="history.html"]');
    await expect(link).toHaveText("История");
    if (path === "/history.html") await expect(link).toHaveAttribute("aria-current", "page");
  }
});

test("home no longer contains fragmented history surfaces", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#studentReviewRequestsPanel")).toHaveCount(0);
  await expect(page.locator("#progressModal")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /очистить историю/i })).toHaveCount(0);
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

test("student history combines an attempt, personal audio and every teacher review", async ({ page }) => {
  let reviewRequests = [{
    id: 43,
    runId: "student-run",
    variantId: "open-2026",
    kind: "attempt",
    status: "reviewed",
    tasks: [1, 2, 3],
    submittedAt: 1_788_950_000,
    reviewedAt: 1_788_950_100,
    total: 17,
    maximum: 20,
    items: [{ task: 2, total: 7, maximum: 7, scores: {}, recordings: [{ id: 71, label: "Запись для проверки", url: "/api/review-recordings/71" }] }],
    assets: [],
  }, {
    id: 42,
    runId: "student-run",
    variantId: "open-2026",
    kind: "task",
    status: "uploading",
    tasks: [2],
    submittedAt: null,
    reviewedAt: null,
    items: [],
    assets: [],
  }];
  await installStudentHistoryApi(page, {
    recordings: [{ id: 7, runId: "student-run", variantId: "open-2026", taskNumber: 2, questionNumber: 1, label: "Мой ответ", createdAt: 1_788_949_900, expiresAt: 1_804_700_000 }],
    getReviews: () => reviewRequests,
  });
  let discarded = null;
  await page.route("**/api/review-requests/42", route => {
    discarded = route.request().method();
    reviewRequests = reviewRequests.filter(request => request.id !== 42);
    return route.fulfill({ json: { ok: true } });
  });

  await page.goto("/history.html");

  const entry = page.locator(".history-entry");
  await expect(entry).toHaveCount(1);
  await expect(entry.locator("summary")).toContainText("Открытый вариант 2026");
  await expect(entry.locator("summary")).toContainText("Разобрано: 17/20");
  await entry.locator("summary").click();
  await expect(entry.locator('.history-audio-item audio[src="/api/personal-recordings/7"]')).toBeVisible();
  await expect(entry.locator(".history-audio-item")).toContainText("Удалится");
  await expect(entry.locator('.history-review-audio audio[src="/api/review-recordings/71"]')).toBeVisible();
  await expect(entry.locator(".history-review-item")).toHaveCount(2);

  await entry.getByRole("button", { name: "Удалить незавершённую загрузку" }).click();

  expect(discarded).toBe("DELETE");
  await expect(page.locator("[data-discard-review-request]")) .toHaveCount(0);
  await expect(page.locator(".history-review-item")).toHaveCount(1);
});

test("a failed recording source leaves attempts and reviews visible until retry succeeds", async ({ page }) => {
  let recordingAttempts = 0;
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: studentUser } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => {
    recordingAttempts += 1;
    if (recordingAttempts === 1) return route.fulfill({ status: 503, json: { message: "Архив временно недоступен" } });
    return route.fulfill({ json: { recordings: [{ id: 9, runId: "student-run", variantId: "open-2026", taskNumber: 2, questionNumber: 1, label: "Ответ после повтора", createdAt: 1_788_949_900, expiresAt: 1_804_700_000 }] } });
  });
  await page.route("**/api/student/review-requests", route => route.fulfill({ json: { requests: [{ id: 8, runId: "student-run", variantId: "open-2026", kind: "task", status: "queued", tasks: [2], submittedAt: 1_788_950_000, reviewedAt: null, items: [], assets: [] }] } }));
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${studentUser.id}`,
    progress: studentProgress,
  });

  await page.goto("/history.html");

  await expect(page.locator(".history-entry")).toHaveCount(1);
  await expect(page.locator(".history-entry summary")).toContainText("На разборе");
  const retry = page.locator('[data-retry-source="recordings"]');
  await expect(retry).toBeVisible();
  await retry.click();
  await page.locator(".history-entry summary").click();
  await expect(page.locator('.history-audio-item audio[src="/api/personal-recordings/9"]')).toBeVisible();
  await expect(page.locator('[data-retry-source="recordings"]')).toHaveCount(0);
});

test("history fits a 360px viewport and supports keyboard and touch targets", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: studentUser } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => route.fulfill({
    status: 503,
    json: { message: "Архив временно недоступен" },
  }));
  await page.route("**/api/student/review-requests", route => route.fulfill({ json: { requests: [{
    id: 42,
    runId: "student-run",
    variantId: "open-2026",
    kind: "task",
    status: "uploading",
    tasks: [2],
    submittedAt: null,
    reviewedAt: null,
    items: [],
    assets: [],
  }] } }));
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${studentUser.id}`,
    progress: studentProgress,
  });

  await page.goto("/history.html");

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
  for (let index = 0; index < 12; index += 1) {
    if (await page.evaluate(() => document.activeElement?.matches(".history-entry-summary"))) break;
    await page.keyboard.press("Tab");
  }
  await expect(page.locator(".history-entry-summary")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".history-entry")).toHaveAttribute("open", "");

  for (const selector of [
    '[data-retry-source="recordings"]',
    "[data-discard-review-request]",
    '[data-compare-run="student-run"]',
    "#historyCompareBtn",
  ]) {
    const box = await page.locator(selector).boundingBox();
    expect(Math.min(box?.width || 0, box?.height || 0), `${selector} should be at least 44px on its short side`).toBeGreaterThanOrEqual(44);
  }
});
