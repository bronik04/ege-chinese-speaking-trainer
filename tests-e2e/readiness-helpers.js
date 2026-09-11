import { expect } from "@playwright/test";

export async function installWorkingMicrophone(page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => ({ active: true, getTracks: () => [] }),
      },
    });
  });
}

export async function confirmReadiness(page) {
  await expect(page.locator("#beginReadyRunBtn")).toBeEnabled();
  await page.locator("#beginReadyRunBtn").click();
}

export async function chooseAndConfirmReadiness(page, selector) {
  await page.locator(selector).click();
  await confirmReadiness(page);
}
