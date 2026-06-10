import { expect, test } from "@playwright/test";

const adminEmail = process.env.TERRA_ADMIN_EMAIL || "admin@test.tld";
const adminPassword = process.env.TERRA_ADMIN_PASSWORD || "ChangeMe!Admin-1st-login";

test.describe("devices grid", () => {
  test("loads React island after login", async ({ page }) => {
    await page.goto("/auth/login");
    await page.getByLabel(/email/i).fill(adminEmail);
    await page.getByLabel(/password/i).fill(adminPassword);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.goto("/devices");
    await expect(page.locator("#terra-devices-grid-root")).toBeVisible();
    await expect(page.locator(".terra-dg-table")).toBeVisible({ timeout: 15_000 });
  });

  test("search filters rows", async ({ page }) => {
    await page.goto("/auth/login");
    await page.getByLabel(/email/i).fill(adminEmail);
    await page.getByLabel(/password/i).fill(adminPassword);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.goto("/devices");
    const search = page.getByPlaceholder(/search hostname/i);
    await search.fill("zzzz-no-device-match-zzzz");
    await expect(page.getByText(/no devices match/i)).toBeVisible({ timeout: 10_000 });
  });
});
