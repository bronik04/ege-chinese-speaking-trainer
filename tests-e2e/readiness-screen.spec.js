import { expect, test } from "@playwright/test";

async function installWorkingMicrophone(page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({ active: true, getTracks: () => [] }),
      },
    });
  });
}

async function installRetryingMicrophone(page) {
  await page.addInitScript(() => {
    let attempts = 0;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          attempts += 1;
          if (attempts === 1) throw new DOMException("Permission denied", "NotAllowedError");
          return { active: true, getTracks: () => [] };
        },
      },
    });
  });
}

async function installDelayedInterruptedMaterial(page, runId) {
  const materialId = `delayed-${runId}`;
  const interrupted = {
    version: 2,
    updatedAt: "2026-09-10T08:03:00.000Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [],
    activeRun: {
      id: runId,
      variantId: materialId,
      variantLabel: "Отложенный вариант",
      mode: "exam",
      tasks: [1, 2, 3],
      completedTasks: [1],
      currentTask: 2,
      phase: "prep",
      fastMode: false,
      startedAt: "2026-09-10T08:00:00.000Z",
    },
  };
  await page.addInitScript(value => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(value));
  }, interrupted);
  await page.route("**/api/materials", route => route.fulfill({ json: {
    materials: [
      { id: "open-2026", year: 2026, label: "Официальный вариант 2026" },
      { id: materialId, year: 2026, label: "Отложенный вариант" },
    ],
    canCreate: false,
  } }));
  let releaseMaterial;
  const materialGate = new Promise(resolve => { releaseMaterial = resolve; });
  let materialRequested = false;
  await page.route(`**/api/materials/${materialId}`, async route => {
    materialRequested = true;
    await materialGate;
    const response = await page.request.get("/api/materials/open-2026");
    const payload = await response.json();
    await route.fulfill({ json: { material: { ...payload.material, id: materialId, label: "Отложенный вариант" } } });
  });
  return {
    interrupted,
    materialId,
    releaseMaterial,
    wasRequested: () => materialRequested,
  };
}

test("exam starts only after the readiness screen is confirmed", async ({ page }) => {
  await installWorkingMicrophone(page);
  await page.goto("/");

  await page.locator('[data-start="exam"]').click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessMaterial")).toHaveText("Официальный вариант 2026");
  await expect(page.locator("#readinessMode")).toHaveText("Экзамен");
  await expect(page.locator("#readinessTasks")).toHaveText("Задания 1–3");
  await expect(page.locator("#readinessDuration")).toHaveText("14 минут");
  await expect(page.locator("#readinessMicStatus")).toHaveText("Микрофон готов");
  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();

  const beforeStart = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(beforeStart.activeRun).toBeNull();

  await page.locator("#beginReadyRunBtn").click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#phaseCaption")).toHaveText("До начала");
  await expect(page.locator("#taskPaper")).toHaveClass(/locked/);
  const afterStart = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(afterStart.activeRun).toMatchObject({ mode: "exam", tasks: [1, 2, 3], currentTask: 1, phase: "idle" });
});

test("an interrupted exam is unchanged until readiness is confirmed", async ({ page }) => {
  const interrupted = {
    version: 2,
    updatedAt: "2026-09-10T08:03:00.000Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [],
    activeRun: {
      id: "readiness-resume",
      variantId: "open-2026",
      variantLabel: "Официальный вариант 2026",
      mode: "exam",
      tasks: [1, 2, 3],
      completedTasks: [1],
      currentTask: 1,
      phase: "answer",
      fastMode: false,
      startedAt: "2026-09-10T08:00:00.000Z",
    },
  };
  await installWorkingMicrophone(page);
  await page.addInitScript(value => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(value));
  }, interrupted);
  await page.goto("/");

  await page.locator("#continueRunBtn").click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessMode")).toHaveText("Продолжение экзамена");
  await expect(page.locator("#readinessTasks")).toHaveText("Задания 2–3");
  const beforeConfirmation = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(beforeConfirmation.activeRun).toEqual(interrupted.activeRun);
  expect(beforeConfirmation.runs).toEqual([]);

  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
  await page.locator("#beginReadyRunBtn").click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#taskBadge")).toHaveText("Задание 2");
  const afterConfirmation = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(afterConfirmation.activeRun).toMatchObject({
    id: "readiness-resume",
    completedTasks: [1],
    currentTask: 2,
    phase: "idle",
  });
});

test("restart archives the interrupted exam only after readiness", async ({ page }) => {
  const interrupted = {
    version: 2,
    updatedAt: "2026-09-10T08:03:00.000Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [],
    activeRun: {
      id: "readiness-restart",
      variantId: "open-2026",
      variantLabel: "Официальный вариант 2026",
      mode: "exam",
      tasks: [1, 2, 3],
      completedTasks: [1],
      currentTask: 2,
      phase: "prep",
      fastMode: false,
      startedAt: "2026-09-10T08:00:00.000Z",
    },
  };
  await installWorkingMicrophone(page);
  await page.addInitScript(value => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(value));
  }, interrupted);
  await page.goto("/");

  await page.locator("#restartInterruptedRunBtn").click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessMode")).toHaveText("Экзамен заново");
  await expect(page.locator("#readinessTasks")).toHaveText("Задания 1–3");
  await expect(page.locator("#readinessDuration")).toHaveText("14 минут");
  const beforeConfirmation = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(beforeConfirmation.activeRun.id).toBe("readiness-restart");
  expect(beforeConfirmation.runs).toEqual([]);

  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
  await page.locator("#beginReadyRunBtn").click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#taskBadge")).toHaveText("Задание 1");
  const afterConfirmation = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(afterConfirmation.runs).toHaveLength(1);
  expect(afterConfirmation.runs[0]).toMatchObject({ id: "readiness-restart", status: "interrupted" });
  expect(afterConfirmation.activeRun.id).not.toBe("readiness-restart");
  expect(afterConfirmation.activeRun).toMatchObject({ currentTask: 1, completedTasks: [], phase: "idle" });
});

test("a microphone denial blocks a task until the retry succeeds", async ({ page }) => {
  await installRetryingMicrophone(page);
  await page.goto("/");

  await page.locator('[data-start="2"]').click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessMode")).toHaveText("Тренировка");
  await expect(page.locator("#readinessTasks")).toHaveText("Задание 2");
  await expect(page.locator("#readinessDuration")).toHaveText("4 минуты");
  await expect(page.locator("#readinessMicStatus")).toHaveText("Нет доступа к микрофону");
  await expect(page.locator("#beginReadyRunBtn")).toBeDisabled();
  const beforeRetry = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(beforeRetry.activeRun).toBeNull();

  await page.locator("#retryReadinessMicBtn").click();

  await expect(page.locator("#readinessMicStatus")).toHaveText("Микрофон готов");
  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
  await page.locator("#beginReadyRunBtn").click();
  const afterRetry = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(afterRetry.activeRun).toMatchObject({ mode: "practice", tasks: [2], currentTask: 2, phase: "idle" });
});

test("back from readiness preserves an interrupted run", async ({ page }) => {
  const interrupted = {
    version: 2,
    updatedAt: "2026-09-10T08:03:00.000Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [],
    activeRun: {
      id: "keep-on-back",
      variantId: "open-2026",
      variantLabel: "Официальный вариант 2026",
      mode: "exam",
      tasks: [1, 2, 3],
      completedTasks: [1],
      currentTask: 2,
      phase: "prep",
      fastMode: false,
      startedAt: "2026-09-10T08:00:00.000Z",
    },
  };
  await installWorkingMicrophone(page);
  await page.addInitScript(value => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(value));
  }, interrupted);
  await page.goto("/");

  await page.locator('[data-start="3"]').click();
  await expect(page.locator("#readinessScreen")).toBeVisible();
  await page.locator("#cancelReadyRunBtn").click();

  await expect(page.locator("#homeScreen")).toBeVisible();
  await expect(page.locator("#resumeRunPanel")).toBeVisible();
  const afterBack = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(afterBack.activeRun.id).toBe("keep-on-back");
  expect(afterBack.runs).toEqual([]);
});

test("readiness fits a 360px viewport with touch-sized actions", async ({ page }) => {
  await installWorkingMicrophone(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/");
  await page.locator('[data-start="1"]').click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  const layout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    pageWidth: document.documentElement.scrollWidth,
  }));
  expect(layout.pageWidth).toBeLessThanOrEqual(layout.viewport);
  for (const selector of ["#cancelReadyRunBtn", "#retryReadinessMicBtn", "#beginReadyRunBtn"]) {
    const box = await page.locator(selector).boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
});

test("readiness moves keyboard focus and restores it when going back", async ({ page }) => {
  await installWorkingMicrophone(page);
  await page.goto("/");
  const startButton = page.locator('[data-start="1"]');

  await startButton.focus();
  await startButton.press("Enter");
  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessTitle")).toBeFocused();

  await page.locator("#cancelReadyRunBtn").click();
  await expect(page.locator("#homeScreen")).toBeVisible();
  await expect(startButton).toBeFocused();

  await startButton.press("Enter");
  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
  await page.locator("#beginReadyRunBtn").click();
  await expect(page.locator("#mainActionBtn")).toBeFocused();
});

test("signing in cancels a readiness action from the guest scope", async ({ page }) => {
  const student = {
    id: 501,
    email: "readiness-scope@example.test",
    displayName: "Readiness Scope",
    role: "student",
    emailVerified: true,
  };
  await installWorkingMicrophone(page);
  await page.route("**/api/auth/me", route => route.fulfill({
    status: 401,
    json: { detail: "Authentication required", code: "authentication_required" },
  }));
  await page.route("**/api/auth/login", route => route.fulfill({ json: { user: student } }));
  await page.route("**/api/progress", route => {
    if (route.request().method() === "PUT") return route.fulfill({ json: { ok: true, updatedAt: 1_789_000_000 } });
    return route.fulfill({ json: { progress: null, updatedAt: null } });
  });
  await page.goto("/");
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#readinessScreen")).toBeVisible();

  await page.locator("#authButton").click();
  await page.locator("#authEmail").fill(student.email);
  await page.locator("#authPassword").fill("password123");
  await page.locator("#authSubmitBtn").click();

  await expect(page.locator("#authButtonText")).toHaveText(student.email);
  await expect(page.locator("#homeScreen")).toBeVisible();
  await expect(page.locator("#readinessScreen")).toHaveClass(/hidden/);
  const accountProgress = await page.evaluate(key => JSON.parse(localStorage.getItem(key)), `egeChineseProgressV2:user:${student.id}`);
  expect(accountProgress.activeRun).toBeNull();
});

test("a disconnected microphone blocks confirmation after an earlier success", async ({ page }) => {
  await page.addInitScript(() => {
    let active = true;
    let requests = 0;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          requests += 1;
          if (requests > 1) throw new DOMException("Device disconnected", "NotReadableError");
          return { get active() { return active; }, getTracks: () => [] };
        },
      },
    });
    window.disconnectReadinessMicrophone = () => { active = false; };
  });
  await page.goto("/");
  await page.locator('[data-start="exam"]').click();
  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();

  await page.evaluate(() => window.disconnectReadinessMicrophone());
  await page.locator("#beginReadyRunBtn").click();

  await expect(page.locator("#readinessScreen")).toBeVisible();
  await expect(page.locator("#readinessMicStatus")).toHaveText("Нет доступа к микрофону");
  await expect(page.locator("#beginReadyRunBtn")).toBeDisabled();
  const progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.activeRun).toBeNull();
});

for (const scenario of [
  { name: "resume", selector: "#continueRunBtn" },
  { name: "restart", selector: "#restartInterruptedRunBtn" },
]) {
  test(`back cancels a ${scenario.name} while its material is still loading`, async ({ page }) => {
    await installWorkingMicrophone(page);
    const delayed = await installDelayedInterruptedMaterial(page, `cancel-${scenario.name}`);
    await page.goto("/");

    await page.locator(scenario.selector).click();
    await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
    await page.locator("#beginReadyRunBtn").click();
    await expect.poll(delayed.wasRequested).toBe(true);
    await page.locator("#cancelReadyRunBtn").click();

    await expect(page.locator("#homeScreen")).toBeVisible();
    const materialResponse = page.waitForResponse(response => response.url().endsWith(`/api/materials/${delayed.materialId}`));
    delayed.releaseMaterial();
    await materialResponse;
    await page.waitForTimeout(100);

    await expect(page.locator("#runnerScreen")).toHaveClass(/hidden/);
    await expect(page.locator("#readinessScreen")).toHaveClass(/hidden/);
    await expect(page.locator("#selectedMaterialTitle")).toHaveText("Официальный вариант 2026");
    await expect(page.locator('[data-start="exam"]')).toBeEnabled();
    await expect(page.locator('[data-start="1"]')).toBeEnabled();
    await expect(page).not.toHaveURL(new RegExp(`variant=${delayed.materialId}`));
    const progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
    expect(progress.activeRun).toEqual(delayed.interrupted.activeRun);
    expect(progress.runs).toEqual([]);
  });
}
