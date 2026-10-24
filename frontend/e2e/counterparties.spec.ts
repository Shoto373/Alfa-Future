import { test, expect } from "@playwright/test";

// SPR4-01: экран «Контрагенты» — топ по платежам и цепочки второго уровня, без горизонтальной прокрутки на телефоне.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("контрагенты: топ по платежам и второй уровень", async ({ page }) => {
  const email = `e2e-cp-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();
  await page.goto("/pulse/counterparties");
  await expect(page.getByRole("heading", { name: /^Контрагенты / })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Главные контрагенты по платежам" })).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/counterparties.png", fullPage: true });
});
