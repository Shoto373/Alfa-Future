import path from "node:path";
import { test, expect } from "@playwright/test";

// SPR3-03, приемка: новый PDF → черновики с проверками → правка аналитиком → публикация.
// Демо-PDF синтетический, ответы модели распознавания записаны (бюджет не тратится).

const api = process.env.E2E_API_URL || "http://localhost:8000";
const PDF = path.resolve(__dirname, "../../backend/app/knowledge/recorded/demo_review.pdf");

test("аналитик: загрузка PDF, проверка черновиков и публикация тезиса", async ({ page }) => {
  // Демо-сотрудник банка из локального compose.yaml (DEMO_ACCOUNTS=1, OPERATOR_EMAILS).
  const login = await page.request.post(`${api}/api/v1/auth/login`, { data: { email: "operator@alfa.test", password: "alfa-demo-2026" } });
  test.skip(!login.ok(), "демо-учетные записи выключены на этом стенде");

  await page.goto("/admin/kb");
  await expect(page.getByRole("heading", { name: "Тезисы аналитики" })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await page.getByRole("button", { name: "Загрузить" }).click();
  await expect(page.getByRole("status")).toContainText(/поставлен на распознавание|уже загружен/);

  // Распознавание — задача воркера; список обновляется сам.
  const doc = page.getByRole("link", { name: /ДЕМО\. Макроэкономический обзор/ });
  await expect(doc).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Готов к проверке").first()).toBeVisible({ timeout: 90_000 });
  await doc.click();

  const drafts = page.getByTestId("kb-draft");
  await expect(drafts).toHaveCount(11);
  await expect(page.getByRole("img", { name: "Скан страницы 1" })).toBeVisible();

  // Ошибка распознавания числа: проверка показывает, правка исправляет.
  // Карточка находится по цитате со страницы: после правки текст проверки меняется, цитата — нет.
  const inflation = drafts.filter({ hasText: "6,8% против 6,2% в предыдущем прогнозе" });
  await expect(inflation.getByText("✗ Нет на странице: 6.5")).toBeVisible();
  await expect(inflation).toHaveCount(1);
  await inflation.getByLabel("Значение").fill("6,8%");
  await inflation.getByLabel("Тезис").fill("Годовая инфляция на конец 2026 г. составит 6,8% (прежний прогноз 6,2%).");
  await inflation.getByRole("button", { name: "Сохранить правку" }).click();
  await expect(inflation.getByText("✓ Все числа тезиса есть на странице")).toBeVisible();

  // Публикация прогноза ставки с замещением прежнего прогноза банка.
  const rate = drafts.filter({ hasText: "ключевой ставки на конец 2026 г. до 15,0%" });
  await expect(rate.getByText("Заменяет прежний прогноз rate-05")).toBeVisible();
  await expect(rate).toHaveCount(1);
  await page.screenshot({ path: "test-results/kb-review.png", fullPage: false });
  await rate.getByRole("button", { name: "Опубликовать" }).click();
  await page.getByRole("button", { name: /Опубликованы/ }).click();
  await expect(page.getByTestId("kb-draft").filter({ hasText: /Опубликован как kb-/ })).toHaveCount(1);
});
