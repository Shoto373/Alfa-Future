import { test, expect, type Page } from "@playwright/test";

const api = process.env.E2E_API_URL || "http://localhost:8000";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: /Анна Морозова/ }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("region", { name: "Альфа.Пульс на главной" })).toBeVisible();
  await expect(page.locator(".home .top-list li").first()).toBeVisible();
}

test("вход, компания, роль и персонализированная лента", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await login(page);
  await page.goto("/pulse");
  await expect(page.getByRole("heading", { name: /^Лента / })).toBeVisible();
  await expect(page.locator(".news-card").first()).toBeVisible();
  const role = page.locator("select").first();
  const changedFeed = page.waitForResponse(r => r.url().includes("/api/v1/feed?") && r.url().includes("role=treasurer"));
  await role.selectOption("treasurer");
  expect((await changedFeed).ok()).toBeTruthy();
  await expect(page.getByText(/роль «Руководитель казначейства»/)).toBeVisible();
  const current = await page.locator(".switcher-name").innerText();
  await page.locator(".switcher-btn").click();
  const dialog = page.getByRole("dialog", { name: "Выбор организации" });
  await expect(dialog.locator("li button").nth(1)).toBeVisible();
  await dialog.locator("li button").nth(1).click();
  await expect(page.locator(".switcher-name")).not.toHaveText(current);
  await expect(page.getByRole("heading", { name: /^Лента / })).toContainText(await page.locator(".switcher-name").innerText());
  await expect(page.getByText("Подбираем новости под компанию…")).toBeHidden();
  await expect(page.locator(".news-card").first()).toBeVisible();
  await page.screenshot({ path: "../data/review/acceptance/feed.png", fullPage: false });
  expect(errors).toEqual([]);
});

test("разбор, трасса, уточнение, оценка и первоисточник", async ({ page, request }) => {
  await login(page);
  await page.goto("/pulse/n/seed-rate-hold");
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible();
  await expect(page.getByText("Самопроверка пройдена", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Как получен вывод" }).click();
  await expect(page.getByRole("heading", { name: "Ход анализа агента" })).toBeVisible();
  await page.getByRole("button", { name: "Покажи в разрезе контрагентов" }).click();
  await expect(page.locator(".chat-turn").last()).toContainText("Структура платежей");
  await page.getByRole("button", { name: "Полезно", exact: true }).first().click();
  await expect(page.getByText("Спасибо за оценку").first()).toBeVisible();
  const pdf = page.locator('a[href*="/analytics/"][href*="/pdf#page="]').first();
  const href = await pdf.getAttribute("href");
  expect(href).toMatch(/#page=\d+/);
  const response = await request.get(href!.split("#")[0]);
  expect(response.ok()).toBeTruthy();
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect(response.headers()["content-disposition"]).toContain("inline");
  expect((await response.body()).subarray(0, 4).toString()).toBe("%PDF");
  const popupPromise = page.waitForEvent("popup");
  await pdf.click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(href!);
  await popup.close();
  await page.getByRole("button", { name: "Скрыть ход анализа" }).click();
  await page.locator(".insight-head").scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../data/review/acceptance/insight.png", fullPage: false });
});

test("новая новость и сохраненный разбор после перезагрузки", async ({ page }) => {
  await login(page);
  await page.goto("/pulse");
  await page.getByPlaceholder("Например: Минфин предложил повысить НДС…").fill(
    `Банк России сохранил ключевую ставку на уровне 14%. Условия новых кредитов не изменились. Проверка браузера ${Date.now()}.`
  );
  await page.getByRole("button", { name: "Разобрать", exact: true }).click();
  await expect(page).toHaveURL(/\/pulse\/n\//);
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible();
  const url = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible();
  expect(page.url()).toBe(url);
});

test("состояния загрузки и ошибки с повтором", async ({ page }) => {
  await login(page);
  let fail = true;
  await page.route("**/api/v1/feed?**", async route => {
    if (fail) {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: {
        code: "DATA_UNAVAILABLE", message: "Проверка временной недоступности", retryable: true, request_id: "req_e2e",
      } }) });
    } else {
      await new Promise(resolve => setTimeout(resolve, 800));
      await route.continue();
    }
  });
  await page.goto("/pulse");
  await expect(page.getByText("Проверка временной недоступности")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: /Повторить/ }).click();
  await expect(page.getByText("Подбираем новости под компанию…")).toBeVisible();
  await expect(page.locator(".news-card").first()).toBeVisible();
});

test("аналитика, новый стиль и мобильный экран", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("link", { name: "Альфа-Бизнес, главная" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Качество и аудит" })).toHaveCount(0);
  await page.screenshot({ path: "../data/review/acceptance/home-new-style.png", fullPage: true });
  await page.goto("/pulse/analytics");
  await expect(page.getByRole("heading", { name: "Аналитика Альфа-Банка" })).toBeVisible();
  await expect(page.getByText("устарел", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pulse");
  await expect(page.locator(".news-card").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: "../data/review/acceptance/mobile.png", fullPage: true });
});

test("отказ провайдера LLM дает разбор на правилах и предупреждение в трассе", async ({ page }) => {
  const failureApi = process.env.E2E_FAILURE_API_URL;
  test.skip(!failureApi, "Set E2E_FAILURE_API_URL to the isolated API with an unreachable local LLM endpoint");
  await page.route(`${api}/**`, async route => {
    const response = await route.fetch({ url: route.request().url().replace(api, failureApi!) });
    await route.fulfill({ response });
  });
  await login(page);
  await page.goto("/pulse/n/seed-rate-hold");
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible();
  await expect(page.getByText("Агент на правилах (без LLM)", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Как получен вывод" }).click();
  await expect(page.locator(".trace")).toContainText("LLM-план не получен");
  await page.screenshot({ path: "../data/review/acceptance/provider-fallback.png", fullPage: true });
});
