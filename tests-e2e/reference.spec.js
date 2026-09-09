import { expect, test } from "@playwright/test";

test("reference library filters phrases and switches exam tasks", async ({ page }) => {
  await page.goto("/reference.html");
  await expect(page.locator(".reference-tab")).toHaveCount(3);
  await expect(page.locator(".reference-tabs")).toHaveCSS("border-radius", "16px");
  await expect(page.locator(".reference-tab").nth(0)).toHaveClass(/active/);
  const activeReferenceTab = page.locator(".reference-tab.active");
  await expect(activeReferenceTab).toHaveCSS("background-color", "rgb(92, 14, 14)");
  await expect(activeReferenceTab).toHaveCSS("background-image", "none");
  await expect(activeReferenceTab).toHaveCSS("color", "rgb(244, 236, 219)");
  await page.locator(".reference-tab").nth(1).hover();
  await expect(page.locator(".reference-tab").nth(1)).not.toHaveCSS("background-color", "rgb(92, 14, 14)");
  await expect(page.locator(".reference-task-head h2")).toHaveText("Пять вопросов");
  await expect(page.locator(".reference-criteria h3")).toHaveText("Критерии оценивания");
  await expect(page.locator(".reference-criteria > header > strong")).toHaveText("Максимум 5");
  await expect(page.locator(".reference-group summary small")).toHaveCount(0);
  await page.locator('[data-reference-task="task-2"]').click();
  await expect(page).toHaveURL(/#task-2$/);
  await expect(page.locator(".reference-task-head h2")).toHaveText("Описание фотографии");
  await expect(page.locator(".example-card")).toHaveCount(1);
  await expect(page.locator(".examples-heading h3")).toHaveText("Примеры ответов");
  await expect(page.locator(".criteria-card")).toHaveCount(3);
  await expect(page.locator(".reference-criteria > header > strong")).toHaveText("Максимум 7");

  await page.locator("#referenceSearch").fill("скидка");
  await expect(page.locator(".phrase-card")).toHaveCount(2);
  await expect(page.locator(".phrase-card").first()).toContainText("优惠");
  await page.locator("#referenceSearch").fill("");
  await page.locator('[data-reference-task="task-3"]').click();
  const introGroup = page.locator(".reference-group").first();
  await expect(introGroup.locator(".phrase-card")).toHaveCount(1);
  const copyButton = page.locator(".copy-phrase").first();
  await expect(copyButton).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(copyButton).toHaveCSS("background-image", "none");
  await expect(copyButton).toHaveCSS("box-shadow", "none");
  await copyButton.hover();
  await expect(copyButton).toHaveCSS("background-color", "rgb(232, 211, 138)");
  const listBox = await introGroup.locator(".phrase-list").boundingBox();
  const cardBox = await introGroup.locator(".phrase-card").boundingBox();
  expect(Math.abs(listBox.width - cardBox.width)).toBeLessThan(2);
});

test("shared account, wordmark and footer are available across public pages", async ({ page }) => {
  for (const path of ["/", "/variants.html", "/reference.html", "/variant-editor.html", "/history.html"]) {
    await page.goto(path);
    await expect(page.locator(".brand-mark")).toHaveText("口试");
    await expect(page.locator(".account-btn")).toBeVisible();
    await expect(page.locator('.site-nav a[href="history.html"]')).toHaveText("История");
    await expect(page.locator(".site-footer")).toBeVisible();
    await expect(page.locator('a[href="about.html"]')).toHaveCount(0);
  }
  const response = await page.goto("/about.html");
  expect(response?.status()).toBe(404);
  await page.goto("/reference.html");
  await page.locator("[data-account-link]").click();
  await expect(page.locator("#authModal")).toBeVisible();
});

test("home uses horizontal motto and keeps account at the far right", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".hero-idiom")).toHaveText("熟能生巧");
  await expect(page.locator(".hero-copy h1")).toContainText("Мастерство приходит с практикой");
  const lastAction = await page.locator(".header-actions > :last-child").getAttribute("id");
  expect(lastAction).toBe("authButton");
  await expect(page.locator("#authButton")).toHaveCSS("background-color", "rgb(244, 236, 219)");
  const taskChoice = page.locator('[data-start="1"]');
  await expect(taskChoice).toBeEnabled();
  await expect(taskChoice).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await taskChoice.hover();
  await expect(taskChoice).toHaveCSS("background-color", "rgb(232, 211, 138)");
  await page.locator("#authButton").click();
  await expect(page.locator("#loginTab")).toHaveCSS("background-color", "rgb(92, 14, 14)");
  await expect(page.locator("#loginTab")).toHaveCSS("background-image", "none");
});

test("home exam action uses the classic cream and gold colors", async ({ page }) => {
  await page.goto("/");
  const examAction = page.locator('.home-screen [data-start="exam"]');
  await expect(examAction).toBeEnabled();
  await expect(examAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(examAction).toHaveCSS("background-image", "none");
  await expect(examAction).toHaveCSS("color", "rgb(92, 14, 14)");
  await expect(examAction).toHaveCSS("border-radius", "999px");
  await expect(examAction).toHaveCSS("box-shadow", "none");

  await examAction.hover();
  await expect(examAction).toHaveCSS("background-color", "rgb(232, 211, 138)");
  await expect(examAction).toHaveCSS("color", "rgb(92, 14, 14)");
});

test("primary actions share the flat cream and gold palette", async ({ page }) => {
  await page.goto("/");
  const homeAction = page.locator('.home-screen [data-start="exam"]');
  await expect(homeAction).toBeEnabled();
  await expect(homeAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(homeAction).toHaveCSS("background-image", "none");
  await expect(homeAction).toHaveCSS("color", "rgb(92, 14, 14)");

  await page.locator('[data-start="1"]').click();
  const runnerAction = page.locator("#mainActionBtn");
  await expect(runnerAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(runnerAction).toHaveCSS("background-image", "none");
  await expect(runnerAction).toHaveCSS("box-shadow", "none");

  await page.locator("#exitBtn").click();
  await page.locator("#authButton").click();
  const authAction = page.locator("#authSubmitBtn");
  await expect(authAction).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await expect(authAction).toHaveCSS("background-image", "none");
  await expect(authAction).toHaveCSS("box-shadow", "none");
  await authAction.hover();
  await expect(authAction).toHaveCSS("background-color", "rgb(232, 211, 138)");
});

test("account dialog follows the shared card system and closes safely", async ({ page }) => {
  await page.goto("/");
  await page.locator("#authButton").click();
  await expect(page.locator("#authModal")).toBeVisible();
  await expect(page.locator("#authModal .auth-dialog")).toHaveCSS("border-radius", "16px");
  await expect(page.locator(".auth-tabs")).toHaveCSS("border-radius", "999px");
  await expect(page.locator("#authSubmitBtn")).toHaveCSS("border-radius", "999px");
  await expect(page.locator("#authCloseBtn")).toHaveCSS("min-height", "44px");
  await expect(page.locator("#loginTab")).toHaveCSS("min-height", "44px");
  await page.locator("#authCloseBtn").click();
  await expect(page.locator("#authModal")).toHaveClass(/hidden/);
});

test("reference link is hidden only during an active task", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#referenceLink")).toBeVisible();
  await page.locator('[data-start="1"]').click();
  await expect(page.locator("#referenceLink")).toBeHidden();
});

test("runner keeps locked task content out of the accessibility tree", async ({ page }) => {
  await page.goto("/");
  await page.locator('[data-start="1"]').click();
  await expect(page.locator(".exam-steps")).toHaveCSS("border-radius", "16px");
  await expect(page.locator(".task-paper")).toHaveCSS("border-radius", "16px");
  await expect(page.locator(".timer-panel")).toHaveCSS("border-radius", "16px");
  await expect(page.locator("#runnerScreen")).not.toHaveAttribute("aria-live");
  await expect(page.locator("#taskContent")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator("#taskContent")).toHaveJSProperty("inert", true);
  await page.locator("#mainActionBtn").click();
  await expect(page.locator("#taskContent")).toHaveAttribute("aria-hidden", "false");
  await expect(page.locator("#taskContent")).toHaveJSProperty("inert", false);
});

test("mobile navigation and utility controls fit the viewport and a finger", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const mobileTargets = async selectors => {
    for (const selector of selectors) {
      const box = await page.locator(selector).first().boundingBox();
      expect(box?.height, `${selector} should be at least 44px tall`).toBeGreaterThanOrEqual(44);
    }
  };
  await page.evaluate(() => {
    const fixture = document.createElement("div");
    fixture.innerHTML = '<button class="secondary-btn" data-mobile-target>Дополнительное действие</button><a class="download-link" data-mobile-download href="#">Скачать</a>';
    document.body.append(fixture);
  });
  await mobileTargets(["#checkMicBtn", ".material-catalog-link", "[data-mobile-target]", "[data-mobile-download]"]);
  await page.locator('[data-start="1"]').click();
  await page.locator("#mainActionBtn").click();
  await expect(page.locator("#skipBtn")).toBeVisible();
  await mobileTargets(["#exitBtn", "#skipBtn"]);
  await page.goto("/reference.html");
  await mobileTargets([".copy-phrase", ".header-link"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.goto("/variants.html");
  await mobileTargets([".year-filter", "#catalogAccessNotice a"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("keyboard focus stays visible on selected and ordinary controls", async ({ page }) => {
  await page.goto("/");
  const microphoneCheck = page.locator("#checkMicBtn");
  await microphoneCheck.focus();
  await expect(microphoneCheck).toHaveCSS("outline-style", "solid");
  await expect(microphoneCheck).toHaveCSS("outline-color", "rgb(139, 26, 26)");

  await page.goto("/reference.html");
  const activeTab = page.locator(".reference-tab.active");
  await activeTab.focus();
  await expect(activeTab).toHaveCSS("outline-style", "solid");
  await expect(activeTab).toHaveCSS("outline-color", "rgb(139, 26, 26)");

  const search = page.locator("#referenceSearch");
  await search.focus();
  await expect(search).toHaveCSS("outline-style", "solid");
  await expect(search).toHaveCSS("outline-color", "rgb(139, 26, 26)");
});

test("interactive controls stay flat and fit a mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator('[data-start="exam"]')).toHaveCSS("background-image", "none");
  await page.locator("#authButton").click();
  await expect(page.locator("#authSubmitBtn")).toHaveCSS("background-image", "none");
  await expect(page.locator("#authCloseBtn")).toHaveCSS("background-color", "rgb(244, 236, 219)");
  await page.locator("#authCloseBtn").hover();
  await expect(page.locator("#authCloseBtn")).toHaveCSS("background-color", "rgb(232, 211, 138)");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  await page.goto("/reference.html");
  await expect(page.locator(".reference-tab.active")).toHaveCSS("background-image", "none");
  await expect(page.locator(".copy-phrase").first()).toHaveCSS("min-height", "44px");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  await page.goto("/variants.html");
  await expect(page.locator(".year-filter.active")).toHaveCSS("background-image", "none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
