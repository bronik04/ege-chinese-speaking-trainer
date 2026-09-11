import { expect, test } from "@playwright/test";

const student = {
  id: 29,
  email: "compare-student@example.test",
  displayName: "Compare Student",
  role: "student",
  emailVerified: true,
};

function completedRun(id, variantId, variantLabel, completedAt) {
  return {
    id,
    variantId,
    variantLabel,
    mode: "practice",
    tasks: [2],
    completedTasks: [2],
    currentTask: 2,
    phase: "answer",
    fastMode: false,
    startedAt: completedAt.replace("10:05", "10:00"),
    status: "completed",
    completedAt,
    recordingsCount: 1,
  };
}

const comparisonProgress = {
  version: 2,
  updatedAt: "2026-09-09T10:06:00.000Z",
  settings: { lastVariant: "demo-2025", fastMode: false },
  runs: [
    completedRun("right-run", "demo-2025", "Вторая тренировка", "2026-09-09T10:05:00.000Z"),
    completedRun("left-run", "open-2026", "Первая тренировка", "2026-09-08T10:05:00.000Z"),
  ],
  activeRun: null,
};

function reviewedRequest(id, runId, total, reviewedAt, recordings = []) {
  return {
    id,
    runId,
    variantId: runId === "left-run" ? "open-2026" : "demo-2025",
    kind: "task",
    status: "reviewed",
    tasks: [2],
    submittedAt: reviewedAt - 100,
    reviewedAt,
    total,
    maximum: 7,
    items: [{
      task: 2,
      total,
      maximum: 7,
      scores: total === 4
        ? { content: 2, organization: 1, language: 1 }
        : { content: 3, organization: 2, language: 1 },
      recordings,
    }],
    assets: [],
  };
}

async function installComparisonApi(page, {
  recordings = [],
  reviews = [],
  progress = comparisonProgress,
} = {}) {
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: student } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => route.fulfill({ json: { recordings } }));
  await page.route("**/api/student/review-requests", route => route.fulfill({ json: { requests: reviews } }));
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${student.id}`,
    progress,
  });
}

test("student compares scores and aligned personal and review audio", async ({ page }) => {
  await installComparisonApi(page, {
    recordings: [{
      id: 7,
      runId: "left-run",
      variantId: "open-2026",
      taskNumber: 2,
      questionNumber: 1,
      label: "Мой первый ответ",
      createdAt: 1_788_950_000,
      expiresAt: 1_804_700_000,
    }],
    reviews: [
      reviewedRequest(101, "left-run", 4, 1_788_950_100),
      reviewedRequest(102, "right-run", 6, 1_788_960_100, [{
        id: 8,
        question_number: null,
        label: "Второй ответ для разбора",
        url: "/api/review-recordings/8",
      }]),
    ],
  });

  await page.goto("/history.html");
  await page.locator('[data-compare-run="left-run"]').click();
  await page.locator('[data-compare-run="right-run"]').click();
  await page.locator("#historyCompareBtn").click();

  await expect(page).toHaveURL(/\/compare\.html\?left=left-run&right=right-run$/);
  await expect(page.locator("#comparisonTitle")).toBeFocused();
  await expect(page.locator(".comparison-attempt")).toHaveCount(2);
  await expect(page.locator(".comparison-attempt").nth(0)).toContainText("Первая тренировка");
  await expect(page.locator(".comparison-attempt").nth(1)).toContainText("Вторая тренировка");
  await expect(page.locator(".comparison-task")).toContainText("+2 балла");
  await expect(page.locator(".comparison-task")).toContainText("Решение коммуникативной задачи");
  await expect(page.locator('.comparison-task audio[src="/api/personal-recordings/7"]')).toHaveCount(1);
  await expect(page.locator('.comparison-task audio[src="/api/review-recordings/8"]')).toHaveCount(1);
  await expect(page.locator("#comparisonStatus")).toHaveText("Сравнение загружено");
});

test("a failed recording source retries independently and keeps reviewed scores visible", async ({ page }) => {
  let progressGets = 0;
  let progressPuts = 0;
  let recordingCalls = 0;
  let reviewCalls = 0;
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: student } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") {
      progressPuts += 1;
      return route.fulfill({ json: { ok: true } });
    }
    progressGets += 1;
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => {
    recordingCalls += 1;
    if (recordingCalls === 1) {
      return route.fulfill({ status: 503, json: { message: "Архив временно недоступен" } });
    }
    return route.fulfill({ json: { recordings: [{
      id: 9,
      runId: "left-run",
      variantId: "open-2026",
      taskNumber: 2,
      questionNumber: 1,
      label: "Ответ после повтора",
      createdAt: 1_788_950_000,
      expiresAt: 1_804_700_000,
    }] } });
  });
  await page.route("**/api/student/review-requests", route => {
    reviewCalls += 1;
    return route.fulfill({ json: { requests: [
      reviewedRequest(101, "left-run", 4, 1_788_950_100),
      reviewedRequest(102, "right-run", 6, 1_788_960_100),
    ] } });
  });
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${student.id}`,
    progress: comparisonProgress,
  });

  await page.goto("/compare.html?left=left-run&right=right-run");

  await expect(page.locator(".comparison-task")).toContainText("+2 балла");
  await expect(page.locator("#comparisonSourceErrors")).toContainText("Архив временно недоступен");
  await expect(page.locator("#comparisonStatus")).toHaveText("Сравнение загружено частично");
  const retry = page.locator('[data-retry-source="recordings"]');
  await expect(retry).toBeVisible();
  await retry.click();

  await expect(page.locator('.comparison-task audio[src="/api/personal-recordings/9"]')).toBeVisible();
  await expect(page.locator('[data-retry-source="recordings"]')).toHaveCount(0);
  await expect(page.locator("#comparisonStatus")).toHaveText("Сравнение загружено");
  expect({ progressGets, progressPuts, recordingCalls, reviewCalls }).toEqual({
    progressGets: 1,
    progressPuts: 1,
    recordingCalls: 2,
    reviewCalls: 1,
  });
});

test("missing scores and recordings use explicit aligned empty states", async ({ page }) => {
  await installComparisonApi(page);

  await page.goto("/compare.html?left=left-run&right=right-run");

  await expect(page.locator(".comparison-score-grid .comparison-empty")).toHaveText([
    "Оценки пока нет",
    "Оценки пока нет",
  ]);
  await expect(page.locator(".comparison-recording-row .comparison-empty")).toHaveText([
    "Запись недоступна",
    "Запись недоступна",
  ]);
  await expect(page.locator(".comparison-delta")).toHaveText("Изменение недоступно");
});

test("guest and teacher never receive or render student comparison data", async ({ page }) => {
  for (const role of ["guest", "teacher"]) {
    const protectedRequests = [];
    const authRoute = async route => {
      if (role === "guest") {
        await route.fulfill({ status: 401, json: { message: "Требуется вход" } });
      } else {
        await route.fulfill({ json: { user: { ...student, role: "teacher" } } });
      }
    };
    await page.route("**/api/auth/me", authRoute);
    const trackProtected = request => {
      const path = new URL(request.url()).pathname;
      if (["/api/progress", "/api/personal-recordings", "/api/student/review-requests"].includes(path)) {
        protectedRequests.push(path);
      }
    };
    page.on("request", trackProtected);

    await page.goto("/compare.html?left=left-run&right=right-run");

    await expect(page.locator(`[data-comparison-state="${role}"]`)).toBeVisible();
    await expect(page.locator(".comparison-attempt")).toHaveCount(0);
    expect(protectedRequests).toEqual([]);
    page.off("request", trackProtected);
    await page.unroute("**/api/auth/me", authRoute);
  }
});

test("a selection with a missing URL parameter shows a stable state", async ({ page }) => {
  await page.goto("/compare.html?left=left-run");
  await expect(page.locator('[data-comparison-state="invalid_url"]')).toContainText("Выберите две попытки");
});

test("an unknown run ID shows a stable state", async ({ page }) => {
  await installComparisonApi(page);
  await page.goto("/compare.html?left=left-run&right=unknown-run");
  await expect(page.locator('[data-comparison-state="attempt_missing"]')).toContainText("не найдена");
});

test("an interrupted attempt shows a stable state", async ({ page }) => {
  const ineligible = {
    ...comparisonProgress,
    runs: comparisonProgress.runs.map(run => run.id === "right-run"
      ? { ...run, status: "interrupted", completedTasks: [] }
      : run),
  };
  await installComparisonApi(page, { progress: ineligible });
  await page.goto("/compare.html?left=left-run&right=right-run");
  await expect(page.locator('[data-comparison-state="attempt_ineligible"]')).toContainText("только завершённые попытки");
});

test("attempts with different task sets show a stable state", async ({ page }) => {
  const incompatible = {
    ...comparisonProgress,
    runs: comparisonProgress.runs.map(run => run.id === "right-run"
      ? { ...run, tasks: [3], completedTasks: [3], currentTask: 3 }
      : run),
  };
  await installComparisonApi(page, { progress: incompatible });
  await page.goto("/compare.html?left=left-run&right=right-run");
  await expect(page.locator('[data-comparison-state="attempt_incompatible"]')).toContainText("разные наборы заданий");
});

test("late student data cannot restore comparison after session expiry", async ({ page }) => {
  let reviewCalls = 0;
  let releaseRecording;
  let finishRecording;
  const recordingReleased = new Promise(resolve => { releaseRecording = resolve; });
  const recordingFinished = new Promise(resolve => { finishRecording = resolve; });
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: student } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", async route => {
    await recordingReleased;
    await route.fulfill({ json: { recordings: [{
      id: 77,
      runId: "left-run",
      variantId: "open-2026",
      taskNumber: 2,
      questionNumber: 1,
      label: "Поздний ответ",
    }] } });
    finishRecording();
  });
  await page.route("**/api/student/review-requests", route => {
    reviewCalls += 1;
    if (reviewCalls === 1) {
      return route.fulfill({ status: 503, json: { message: "Разборы временно недоступны" } });
    }
    return route.fulfill({ status: 401, json: { message: "Сессия истекла" } });
  });
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${student.id}`,
    progress: comparisonProgress,
  });

  await page.goto("/compare.html?left=left-run&right=right-run");
  await page.locator('[data-retry-source="reviews"]').click();
  await expect(page.locator('[data-comparison-state="guest"]')).toContainText("Войдите как ученик");

  releaseRecording();
  await recordingFinished;
  await expect(page.locator('[data-comparison-state="guest"]')).toBeVisible();
  await expect(page.locator('.comparison-task audio[src="/api/personal-recordings/77"]')).toHaveCount(0);
  await expect(page.locator(".comparison-attempt")).toHaveCount(0);
});

test("comparison fits 360px and keeps actions keyboard-visible and touch-friendly", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  let recordingCalls = 0;
  await page.route("**/api/auth/me", route => route.fulfill({ json: { user: student } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.route("**/api/personal-recordings", route => {
    recordingCalls += 1;
    if (recordingCalls === 1) {
      return route.fulfill({ status: 503, json: { message: "Архив временно недоступен" } });
    }
    return route.fulfill({ json: { recordings: [] } });
  });
  await page.route("**/api/student/review-requests", route => route.fulfill({ json: { requests: [
    reviewedRequest(102, "right-run", 6, 1_788_960_100, [{
      id: 8,
      question_number: null,
      label: "Ответ для разбора",
      url: "/api/review-recordings/8",
    }]),
  ] } }));
  await page.addInitScript(({ key, progress }) => localStorage.setItem(key, JSON.stringify(progress)), {
    key: `egeChineseProgressV2:user:${student.id}`,
    progress: comparisonProgress,
  });

  await page.goto("/compare.html?left=left-run&right=right-run");

  await expect(page.locator("#comparisonTitle")).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBeTruthy();
  await expect(page.locator(".comparison-side-label")).toHaveCount(2);
  await expect(page.locator('.comparison-task audio[src="/api/review-recordings/8"]')).toBeVisible();
  for (const selector of [".comparison-back", '[data-retry-source="recordings"]']) {
    const box = await page.locator(selector).boundingBox();
    expect(Math.min(box?.width || 0, box?.height || 0), `${selector} should be at least 44px`).toBeGreaterThanOrEqual(44);
  }
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator(".comparison-back")).toBeFocused();
  expect(await page.locator(".comparison-back").evaluate(element => getComputedStyle(element).outlineWidth)).not.toBe("0px");
});
