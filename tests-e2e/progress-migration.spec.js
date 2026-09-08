import { expect, test } from "@playwright/test";

test("guest V1 history migrates to V2 and a new run continues from it", async ({ page }) => {
  const legacy = {
    version: 1,
    updatedAt: "2026-09-06T10:15:30Z",
    settings: { lastVariant: "open-2026", fastMode: false },
    runs: [{
      id: "legacy-run", variantId: "open-2026", variantLabel: "Открытый вариант 2026",
      mode: "practice", tasks: [2], completedTasks: [2], currentTask: 2,
      phase: "answer", fastMode: false, startedAt: "2026-09-06T10:00:00Z",
      status: "completed", completedAt: "2026-09-06T10:05:00Z", recordingsCount: 1,
    }],
    activeRun: null,
  };
  await page.addInitScript(value => localStorage.setItem("egeChineseProgressV1", JSON.stringify(value)), legacy);
  await page.goto("/?variant=open-2026");
  await expect(page.locator("#progressSummary")).toContainText("1 тренировка");

  const stored = await page.evaluate(() => ({
    v1: localStorage.getItem("egeChineseProgressV1"),
    v2: JSON.parse(localStorage.getItem("egeChineseProgressV2")),
  }));
  expect(stored.v1).toBeNull();
  expect(stored.v2.version).toBe(2);
  expect(stored.v2.runs[0].id).toBe("legacy-run");

  await page.locator('[data-start="2"]').click();
  const continued = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(continued.version).toBe(2);
  expect(continued.runs[0].id).toBe("legacy-run");
  expect(continued.activeRun.mode).toBe("practice");
});

test("legacy fast-mode preference no longer shortens a new run", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("egeChineseProgressV1", JSON.stringify({
      version: 1,
      settings: { lastVariant: "open-2026", fastMode: true },
    }));
  });

  await page.goto("/?variant=open-2026");
  await expect(page.getByRole("checkbox", { name: /быстро/i })).toHaveCount(0);
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#timerValue")).toHaveText("01:30");

  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("egeChineseProgressV2")));
  expect(stored.activeRun.fastMode).toBe(false);
});
