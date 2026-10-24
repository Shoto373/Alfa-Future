import { test, expect } from "@playwright/test";

// SPR4-05: диалог с разбором — расчет по формуле, уточнение, оценка ответа; история сохраняется после перезагрузки.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("диалог: расчет, уточнение и история", async ({ page }) => {
  const email = `e2e-dialog-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();
  const feed = await (await page.request.get(`${api}/api/v1/feed?company_id=${free.company_id}&limit=5`)).json();
  await page.goto(`/pulse/n/${encodeURIComponent(feed.items[0].news.news_id)}`);

  await page.getByRole("button", { name: "Уточнить у аналитика" }).click();
  const panel = page.getByRole("dialog", { name: "Уточнить у аналитика" });
  const input = panel.getByRole("textbox");
  await input.fill("Как изменятся процентные расходы, если ставка вырастет на 1 п.п.?");
  await panel.getByRole("button", { name: "Спросить" }).click();
  await expect(panel.getByTestId("chat-turn")).toHaveCount(1, { timeout: 30_000 });
  await input.fill("А если на 2 п.п.?");
  await panel.getByRole("button", { name: "Спросить" }).click();
  await expect(panel.getByTestId("chat-turn")).toHaveCount(2, { timeout: 30_000 });
  await panel.getByTestId("chat-turn").first().getByRole("button", { name: "Полезно" }).click();
  await expect(panel.getByTestId("chat-turn").first().getByRole("button", { name: "Полезно" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await page.getByRole("button", { name: "Уточнить у аналитика" }).click();
  await expect(page.getByTestId("chat-turn")).toHaveCount(2, { timeout: 15_000 });
  await page.screenshot({ path: "test-results/dialog.png" });
});
