import { expect, test } from "@playwright/test";

test("catalog filters variants and opens the selected exam", async ({ page }) => {
  await page.goto("/variants.html");
  await expect(page.locator(".variant-card")).toHaveCount(7);
  await page.locator('[data-year="2026"]').click();
  await expect(page.locator(".variant-card")).toHaveCount(2);
  await page.locator("#variantSearch").fill("открытый");
  await expect(page.locator(".variant-card")).toHaveCount(1);
  await page.locator(".variant-open").click();
  await expect(page).toHaveURL(/variant=open-2026/);
  await expect(page.locator("#variantSelect")).toHaveValue("open-2026");
});
