import { test, expect } from "@playwright/test";

// SPR4-02: «что если» на странице компании — число с формулой и происхождением входов; без данных — отказ, а не ноль.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("сценарии: ставка с формулой, курс без данных — отказ", async ({ page }) => {
  const email = `e2e-sc-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();
  await page.goto("/company");
  const result = page.getByTestId("scenario-result");
  await expect(result).toContainText("Формула:", { timeout: 15_000 });
  await expect(result).toContainText("Оценка по отрасли");
  await expect(page.getByText(/Коридор банка/)).toBeVisible();
  await page.getByLabel("Долг, млн ₽").fill("1000");
  await expect(result).toContainText("Вы указали");
  await page.getByRole("tab", { name: "Курс" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Не хватает" })).toBeVisible();
  await page.screenshot({ path: "test-results/scenarios.png", fullPage: false });
});
