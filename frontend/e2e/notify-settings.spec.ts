import { test, expect } from "@playwright/test";

// SPR4-04: настройки уведомлений сохраняются, тестовая сводка приходит в колокольчик, переход по ней отмечает прочтение.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("уведомления: настройки, тестовая сводка, колокольчик", async ({ page }) => {
  const email = `e2e-notify-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();

  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: /^Уведомления · / })).toBeVisible();
  await page.getByLabel("Порог важности").fill("90");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByRole("status")).toContainText("Настройки сохранены");
  await page.reload();
  await expect(page.getByText("90 из 100")).toBeVisible();

  await page.getByRole("button", { name: "Отправить тестовую сводку" }).click();
  await expect(page.getByRole("status")).toContainText(/Тестовая сводка отправлена|меньше трех событий/);
  const sent = (await page.getByRole("status").textContent())?.includes("отправлена");
  test.skip(!sent, "в ленте этой компании меньше трех событий");

  const bell = page.getByRole("button", { name: /Уведомления Альфа.Пульс: непрочитанных/ });
  await expect(bell).toBeVisible({ timeout: 70_000 });
  await bell.click();
  await page.getByTestId("inbox").getByRole("link").first().click();
  await expect(page).toHaveURL(/\/pulse\/n\/.+from=digest&d=\d+/);
  const inbox = await (await page.request.get(`${api}/api/v1/notifications?company_id=${free.company_id}`)).json();
  expect(inbox.unread).toBe(0);
  await page.screenshot({ path: "test-results/notifications.png" });
});
