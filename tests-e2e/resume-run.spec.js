import { expect, test } from "@playwright/test";

const storedProgress = {
  version: 2,
  updatedAt: "2026-09-10T08:03:00.000Z",
  settings: { lastVariant: "open-2026", fastMode: false },
  runs: [],
  activeRun: {
    id: "interrupted-exam",
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

async function seedInterruptedRun(page, progress = storedProgress) {
  await page.addInitScript(value => {
    localStorage.setItem("egeChineseProgressV2", JSON.stringify(value));
  }, progress);
}

test("student continues an interrupted exam from the first unfinished task", async ({ page }) => {
  await seedInterruptedRun(page);
  await page.goto("/");

  await expect(page.locator("#resumeRunPanel")).toBeVisible();
  await expect(page.locator("#resumeRunPanel")).toContainText("Официальный вариант 2026");
  await expect(page.locator("#resumeRunPanel")).toContainText("Задание 2");
  let progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.runs).toEqual([]);
  expect(progress.activeRun.id).toBe("interrupted-exam");

  await page.locator("#continueRunBtn").click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#taskBadge")).toHaveText("Задание 2");
  await expect(page.locator("#phaseCaption")).toHaveText("До начала");
  await expect(page.locator("#taskPaper")).toHaveClass(/locked/);
  await expect(page.locator("#timerValue")).toHaveText("02:00");
  progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.activeRun).toMatchObject({
    id: "interrupted-exam",
    completedTasks: [1],
    currentTask: 2,
    phase: "idle",
  });
});

test("starting an interrupted exam again archives the old run and creates a new one", async ({ page }) => {
  await seedInterruptedRun(page);
  await page.goto("/");

  await page.locator("#restartInterruptedRunBtn").click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#taskBadge")).toHaveText("Задание 1");
  const progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.runs).toHaveLength(1);
  expect(progress.runs[0]).toMatchObject({ id: "interrupted-exam", status: "interrupted", recordingsCount: 0 });
  expect(progress.activeRun.id).not.toBe("interrupted-exam");
  expect(progress.activeRun).toMatchObject({
    mode: "exam",
    completedTasks: [],
    currentTask: 1,
    phase: "idle",
  });
});

test("an interrupted run with an unavailable material moves to history", async ({ page }) => {
  await seedInterruptedRun(page, {
    ...storedProgress,
    settings: { ...storedProgress.settings, lastVariant: "removed-material" },
    activeRun: {
      ...storedProgress.activeRun,
      variantId: "removed-material",
      variantLabel: "Удалённый вариант",
    },
  });
  await page.goto("/");

  await expect(page.locator("#resumeRunPanel")).toHaveClass(/hidden/);
  await expect(page.locator("#toast")).toHaveText("Незавершённый вариант больше недоступен. Попытка сохранена в истории");
  const progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.activeRun).toBeNull();
  expect(progress.runs).toHaveLength(1);
  expect(progress.runs[0]).toMatchObject({
    id: "interrupted-exam",
    status: "interrupted",
    recordingsCount: 0,
  });
});

test("choosing another training archives the offered interrupted run", async ({ page }) => {
  await seedInterruptedRun(page);
  await page.goto("/");

  await page.locator('[data-start="3"]').click();

  await expect(page.locator("#runnerScreen")).toBeVisible();
  await expect(page.locator("#taskBadge")).toHaveText("Задание 3");
  const progress = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(progress.runs).toHaveLength(1);
  expect(progress.runs[0]).toMatchObject({ id: "interrupted-exam", status: "interrupted" });
  expect(progress.activeRun).toMatchObject({ mode: "practice", tasks: [3], currentTask: 3 });
});
