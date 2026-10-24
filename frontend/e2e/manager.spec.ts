import { test, expect, type APIRequestContext } from "@playwright/test";

// SPR4-06: предложение по потребности → заявка только с согласия → ее видит закрепленный менеджер.
const api = process.env.E2E_API_URL || "http://localhost:8000";

async function register(request: APIRequestContext, email: string) {
  expect((await request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
}

test("заявка «обсудить с менеджером» доходит до своего менеджера", async ({ page, browser }) => {
  const stamp = Date.now();
  await register(page.request, `e2e-lead-${stamp}@example.com`);
  const companies = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .filter((c) => !c.claimed);
  // Компания, у которой в ленте есть событие с потребностью (предложение банка показывается не всегда — и это правильно).
  let found: { companyId: string; insightId: string; newsId: string } | null = null;
  for (const c of companies.slice(0, 6)) {
    if (!(await page.request.post(`${api}/api/v1/companies/${c.company_id}/claim`, { data: { role: "cfo" } })).ok()) continue;
    const feed = await (await page.request.get(`${api}/api/v1/feed?company_id=${c.company_id}&limit=15`)).json();
    for (const item of feed.items) {
      const ins = await (await page.request.post(`${api}/api/v1/insights`, { data: { company_id: c.company_id, news_id: item.news.news_id, fast: true } })).json();
      const offers = await (await page.request.get(`${api}/api/v1/insights/${ins.insight_id}/offers`)).json();
      if (offers.offers.length) { found = { companyId: c.company_id, insightId: ins.insight_id, newsId: item.news.news_id }; break; }
    }
    if (found) break;
    await page.request.delete(`${api}/api/v1/companies/${c.company_id}`);
  }
  test.skip(!found, "в лентах свободных компаний нет события с потребностью");

  const operator = await browser.newContext();
  const login = await operator.request.post(`${api}/api/v1/auth/login`, { data: { email: "operator@alfa.test", password: "alfa-demo-2026" } });
  test.skip(!login.ok(), "демо-учетные записи выключены на этом стенде");
  const managerEmail = `e2e-mgr-${stamp}@alfa-bank.test`;
  expect((await operator.request.post(`${api}/api/v1/admin/managers`, { data: { email: managerEmail, company_id: found!.companyId } })).ok()).toBeTruthy();

  await page.goto(`/pulse/n/${encodeURIComponent(found!.newsId)}`);
  const offers = page.getByTestId("bank-offers");
  await expect(offers).toContainText("Реклама банка", { timeout: 30_000 });
  await offers.getByRole("button", { name: "Обсудить с менеджером" }).first().click();
  const send = offers.getByRole("button", { name: "Отправить менеджеру" });
  await expect(send).toBeDisabled();
  await offers.getByRole("checkbox").check();
  await send.click();
  await expect(offers.getByRole("status")).toContainText("Заявка отправлена");

  const manager = await browser.newContext();
  await register(manager.request, managerEmail);
  const mpage = await manager.newPage();
  await mpage.goto("/manager");
  await expect(mpage.getByRole("heading", { name: "Клиенты и заявки" })).toBeVisible();
  await expect(mpage.getByTestId("manager-leads").locator("li").first()).toBeVisible();
  await mpage.getByRole("combobox").first().selectOption("in_progress");
  await expect(mpage.getByRole("combobox").first()).toHaveValue("in_progress");
  await mpage.setViewportSize({ width: 375, height: 812 });
  await mpage.reload();
  await expect(mpage.getByTestId("manager-leads")).toBeVisible();
  expect(await mpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);
  await mpage.screenshot({ path: "test-results/manager.png", fullPage: true });
});
