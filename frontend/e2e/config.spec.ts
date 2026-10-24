import { test, expect } from "@playwright/test";

// SPR4-00: аналитик правит конфигурацию — валидатор ловит перевернутый знак, превью показывает ленту компании.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("отрасли и темы: проверка ловит перевернутый знак, превью ленты", async ({ page }) => {
  const login = await page.request.post(`${api}/api/v1/auth/login`, { data: { email: "operator@alfa.test", password: "alfa-demo-2026" } });
  test.skip(!login.ok(), "демо-учетные записи выключены на этом стенде");
  await page.goto("/admin/config");
  await expect(page.getByRole("heading", { name: "Отрасли и темы" })).toBeVisible();
  await page.getByRole("tab", { name: /Отрасли/ }).click();
  const yaml = page.getByLabel("YAML: sectors");
  const text = await yaml.inputValue();
  // Строительство: рост ставки — риск (-1). Переворачиваем знак и проверяем.
  const flipped = text.replace(/(construction:[\s\S]*?key_rate: \{sign: )-1/, "$11");
  expect(flipped).not.toBe(text);
  await yaml.fill(flipped);
  await page.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByLabel("Результат проверки")).toContainText("sectors.construction.sensitivity.key_rate");
  await expect(page.getByRole("button", { name: "Опубликовать" })).toBeDisabled();

  await yaml.fill(text);
  await page.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByRole("status")).toContainText("Ошибок нет");
  await page.getByRole("button", { name: "Показать превью" }).click();
  await expect(page.getByTestId("config-preview")).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: "test-results/config.png" });
});
