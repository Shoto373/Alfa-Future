import { test, expect } from "@playwright/test";

// SPR3-02, приемка: новость из ленты-заглушки Интерфакса упоминает контрагента компании — видно в ленте и в карточке.
// Компания U_9 («Полный Привод Групп») — пилотная; в демо-ленте есть ее поставщик и покупатель.

const api = process.env.E2E_API_URL || "http://localhost:8000";
const PILOT = "U_9";

test("лента-заглушка Интерфакса: упоминание контрагента в ленте и в разборе", async ({ page }) => {
  const email = `e2e-src-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна Морозова", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const claim = await page.request.post(`${api}/api/v1/companies/${PILOT}/claim`, { data: { role: "cfo" } });
  test.skip(claim.status() === 409, "пилотная компания уже занята на этом стенде");
  expect(claim.ok()).toBeTruthy();
  // Только быстрый разбор: версию модели не запрашиваем.
  await page.route("**/api/v1/insights", async (route) => {
    if (route.request().method() === "POST" && !route.request().postDataJSON()?.fast) await route.abort();
    else await route.fallback();
  });

  // Воркер забирает ленту-заглушку в первом цикле после старта.
  await expect.poll(async () => {
    const feed = await (await page.request.get(`${api}/api/v1/feed?company_id=${PILOT}&limit=500`)).json();
    return (feed.items as { news: { source: string; mentions_company?: boolean } }[])
      .filter((i) => i.news.source === "Интерфакс" && i.news.mentions_company).length;
  }, { timeout: 90_000, intervals: [2_000] }).toBeGreaterThan(0);

  await page.goto("/pulse");
  const card = page.getByTestId("news-card").filter({ hasText: "Сытый Колос-Урал" }).first();
  // Значок в шапке карточки (точный текст); причина отбора ниже добавляет название поставщика.
  await expect(card.getByText("Упоминается ваш поставщик", { exact: true })).toBeVisible();
  await expect(card.getByText("Упоминается ваш поставщик — ООО «Сытый Колос-Урал»")).toBeVisible();
  await card.getByRole("link").first().click();
  const mentions = page.getByRole("region", { name: "Организации в новости" });
  await expect(mentions).toBeVisible({ timeout: 30_000 });
  await expect(mentions.getByText("ООО «Сытый Колос-Урал»")).toBeVisible();
  await expect(mentions.getByText("ваш поставщик")).toBeVisible();
  await page.screenshot({ path: "test-results/sources-mentions.png" });
});
