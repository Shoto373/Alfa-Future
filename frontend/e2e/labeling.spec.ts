import { test, expect } from "@playwright/test";

// SPR3-06: аналитик размечает пару «новость × компания × роль» — оценка сохраняется, прогресс растет.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("разметка ленты: оценка пары и переход к следующей", async ({ page }) => {
  const login = await page.request.post(`${api}/api/v1/auth/login`, { data: { email: "operator@alfa.test", password: "alfa-demo-2026" } });
  test.skip(!login.ok(), "демо-учетные записи выключены на этом стенде");
  await page.goto("/admin/labeling");
  const pair = page.getByTestId("label-pair");
  await expect(pair).toBeVisible({ timeout: 60_000 });
  const before = await page.getByLabel("Прогресс разметки").innerText();
  const title = await pair.locator("h2").nth(1).innerText();
  await page.getByRole("radio", { name: /Важна, нужна реакция/ }).click();
  await page.getByLabel("Причина (коротко)").fill("e2e: проверка экрана разметки");
  await page.getByRole("button", { name: "Сохранить и дальше" }).click();
  await expect(page.getByLabel("Прогресс разметки")).not.toHaveText(before);
  await expect(pair.locator("h2").nth(1)).not.toHaveText(title);
  await page.screenshot({ path: "test-results/labeling.png" });
});
