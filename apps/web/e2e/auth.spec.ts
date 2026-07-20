import { test, expect } from "@playwright/test";

test.describe("auth pages", () => {
  test("login page renders", async ({ page }) => {
    const res = await page.goto("/login", { waitUntil: "domcontentloaded" });
    test.skip(!res || !res.ok(), "dev server unreachable, skipping");

    await expect(page).toHaveTitle(/Sign in/i);
    await expect(page.getByRole("heading", { name: /welcome back/i })).toBeVisible();
    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  test("register page renders", async ({ page }) => {
    const res = await page.goto("/register", { waitUntil: "domcontentloaded" });
    test.skip(!res || !res.ok(), "dev server unreachable, skipping");

    await expect(page.getByRole("heading", { name: /create your account/i })).toBeVisible();
    await expect(page.locator("#first_name")).toBeVisible();
    await expect(page.locator("#last_name")).toBeVisible();
    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.locator("#password_confirm")).toBeVisible();
  });
});
