/**
 * Capture README screenshots from a running TERRA stack.
 * Usage:
 *   TERRA_SCREENSHOT_BASE_URL=https://localhost:4434 node scripts/capture-readme-screenshots.mjs
 */
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const baseURL = process.env.TERRA_SCREENSHOT_BASE_URL || "https://localhost:4434";
const email = process.env.TERRA_ADMIN_EMAIL || "admin@terra.local";
const password = process.env.TERRA_ADMIN_PASSWORD || "ChangeMe!Admin-1st-login";
const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "docs", "images");

async function login(page) {
  await page.goto(`${baseURL}/auth/login`, { waitUntil: "networkidle" });
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.includes("/auth/login"), { timeout: 15_000 });
}

async function main() {
  await mkdir(outDir, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: true,
    colorScheme: "dark",
  });
  const page = await context.newPage();

  await page.goto(`${baseURL}/auth/login`, { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(outDir, "login.png"), fullPage: false });

  await login(page);

  await page.goto(`${baseURL}/`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(outDir, "home-map.png"), fullPage: false });

  await page.goto(`${baseURL}/devices`, { waitUntil: "networkidle" });
  await page.locator(".terra-dg-table").waitFor({ timeout: 20_000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(outDir, "devices-grid.png"), fullPage: false });

  await page.goto(`${baseURL}/devices/10`, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(outDir, "device-detail.png"), fullPage: false });

  const historyRoot = page.locator("#terra-cellular-history-root");
  if (await historyRoot.count()) {
    await historyRoot.scrollIntoViewIfNeeded();
    await page.waitForTimeout(3000);
  }
  await page.screenshot({ path: path.join(outDir, "cellular-history.png"), fullPage: false });

  await page.goto(`${baseURL}/administration/sd-wan`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: path.join(outDir, "sdwan-admin.png"), fullPage: false });

  await browser.close();
  console.log(`Screenshots written to ${outDir}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
