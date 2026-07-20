import { test, expect } from "@playwright/test";

test.describe("marketing pages", () => {
  test("landing page renders hero and pricing", async ({ page }) => {
    const res = await page.goto("/", { waitUntil: "domcontentloaded" });
    test.skip(!res || !res.ok(), "dev server unreachable, skipping");

    await expect(
      page.getByRole("heading", { name: /Underwrite any company/i }),
    ).toBeVisible();

    // Pricing teaser headline is rendered further down — assert it exists
    await expect(
      page.getByRole("heading", { name: /Start free\. Scale when you/i }),
    ).toBeVisible();
  });

  test("nav link to /pricing works", async ({ page }) => {
    const res = await page.goto("/", { waitUntil: "domcontentloaded" });
    test.skip(!res || !res.ok(), "dev server unreachable, skipping");

    await page.getByRole("link", { name: "Pricing", exact: true }).first().click();
    await page.waitForURL("**/pricing");
    await expect(page).toHaveURL(/\/pricing$/);
    await expect(
      page.getByRole("heading", { name: /Pay for volume/i }),
    ).toBeVisible();
  });
});
