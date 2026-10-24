import { test, expect } from "@playwright/test";

// SPR4-07: события воронки пишутся с экранов, дашборд пилота показывает метрики и эксперименты.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("события воронки и дашборд пилота", async ({ page, browser }) => {
  const email = `e2e-product-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();
  const events = page.waitForRequest((r) => r.url().endsWith("/api/v1/events") && r.postDataJSON().kind === "feed_view");
  await page.goto("/pulse");
  await events;
  const opened = page.waitForRequest((r) => r.url().endsWith("/api/v1/events") && r.postDataJSON().kind === "insight_open");
  await page.locator('a[href^="/pulse/n/"]').first().click();
  expect((await opened).postDataJSON().props.source).toBe("feed");
  await page.getByRole("button", { name: "Полезно" }).first().click();

  const operator = await browser.newContext();
  const login = await operator.request.post(`${api}/api/v1/auth/login`, { data: { email: "operator@alfa.test", password: "alfa-demo-2026" } });
  test.skip(!login.ok(), "демо-учетные записи выключены на этом стенде");
  const op = await operator.newPage();
  await op.goto("/quality/product");
  await expect(op.getByRole("heading", { name: "Метрики пилота" })).toBeVisible();
  await expect(op.getByTestId("product-kpis")).toContainText("Активные руководители");
  await expect(op.getByRole("heading", { name: /порядок разделов разбора/ })).toBeVisible();
  const report = await (await operator.request.get(`${api}/api/v1/admin/product?days=7`)).json();
  expect(report.events.feed_view).toBeGreaterThan(0);
  expect(report.events.insight_open).toBeGreaterThan(0);
  expect(report.events.feedback).toBeGreaterThan(0);
  await op.screenshot({ path: "test-results/product.png", fullPage: true });
});
