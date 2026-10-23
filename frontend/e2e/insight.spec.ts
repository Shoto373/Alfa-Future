import { test, expect } from "@playwright/test";
import type { Claim, Insight } from "../lib/types";

const newsId = "новость%25 & курс";
const claim: Claim = { text: "Ставка влияет на расходы компании.", origin: "ai", source_ids: ["source"], features: [] };
const insight: Insight = {
  schema_version: "1.0.0", insight_id: "fast-insight", request_id: "request", company_id: "company", role: "cfo",
  news_id: newsId, created_at: "2026-10-23T09:00:00Z", mode: "rules", model: null,
  title: "Банк России сохранил ставку", headline: "Быстрый разбор готов",
  what_happened: { summary: "Ставка сохранена", facts: [{ ...claim, origin: "fact" }], actors: [], dates: [], assumptions: [] },
  why_important: [claim], risks: [claim], opportunities: [], actions: [claim], questions: [],
  bank_view: { available: false, summary: null, theses: [], conflicts: [] }, products: [], features_used: [],
  sources: [{ source_id: "source", kind: "news", title: "Первоисточник новости", url: "https://example.com/news",
    doc_id: null, page: null, date: null, excerpt: "Решение по ключевой ставке" }],
  relevance: { score: 85, reasons: [] }, quality: { passed: true, attempts: 1, checks: [] }, trace: [], disclaimer: "Для анализа",
};

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`быстрый разбор, источники и помощник после слияния ${viewport.width}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const requests: { news_id: string; fast: boolean; force_refresh: boolean }[] = [];
    let finishUpgrade!: () => void;
    const upgrade = new Promise<void>((resolve) => { finishUpgrade = resolve; });
    await page.route("**/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/auth/me")) {
        await route.fulfill({ json: {
          user_id: "insight-user", name: "Анна", email: "anna@example.com",
          memberships: [{ company_id: "company", company_name: "Тестовая компания", role: "cfo", is_admin: false, is_founder: false }],
        } });
      } else if (path.endsWith("/feed")) {
        await route.fulfill({ json: { items: [], topic_counts: [] } });
      } else if (path.endsWith("/insights")) {
        const body = route.request().postDataJSON();
        requests.push(body);
        if (body.fast) await route.fulfill({ json: insight });
        else {
          await upgrade;
          await route.fulfill({ json: { ...insight, insight_id: "full-insight", mode: "llm", model: "test", headline: "Разбор модели готов" } });
        }
      } else if (path.endsWith("/questions")) {
        await route.fulfill({ json: { insight_id: "full-insight", question: "Что важно?", answer: "Проверьте расходы на кредиты.",
          claims: [], sources: [], mode: "llm", refused: false } });
      } else {
        await route.fulfill({ status: 404, json: {} });
      }
    });

    await page.goto(`/pulse/n/${encodeURIComponent(newsId)}`);
    await expect(page.getByRole("heading", { name: "Быстрый разбор готов", exact: true })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("AI-модель дополняет выводы");
    await expect(page.getByText("Вывод по правилам", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Пересчитать", exact: true })).toBeDisabled();
    const sources = page.getByRole("button", { name: /6\. На чем основан вывод/ });
    await expect(sources).toHaveAttribute("aria-expanded", "false");
    await page.getByRole("link", { name: "[1]", exact: true }).first().click();
    await expect(sources).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("Первоисточник новости", { exact: true })).toBeVisible();
    await expect(page).toHaveURL(/#src-1$/);
    finishUpgrade();
    await expect(page.getByRole("heading", { name: "Разбор модели готов", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Пересчитать", exact: true })).toBeEnabled();
    await expect(page.getByText("Вывод AI", { exact: true }).first()).toBeVisible();
    expect(requests).toEqual([
      { company_id: "company", news_id: newsId, force_refresh: false, fast: true },
      { company_id: "company", news_id: newsId, force_refresh: false, fast: false },
    ]);

    await page.getByRole("button", { name: "Уточнить у аналитика", exact: true }).click();
    const assistant = page.getByRole("dialog", { name: "Уточнить у аналитика" });
    const question = assistant.getByRole("textbox");
    await expect(question).toBeFocused();
    const box = (await assistant.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    await question.fill("Что важно?");
    await assistant.getByRole("button", { name: "Спросить", exact: true }).click();
    await expect(assistant.getByTestId("chat-turn")).toContainText("Проверьте расходы на кредиты.");
    await expect(question).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("assistant.png"), animations: "disabled" });
    await page.keyboard.press("Escape");
    await expect(assistant).toBeHidden();
    await page.getByRole("button", { name: "Уточнить у аналитика", exact: true }).click();
    await expect(assistant.getByTestId("chat-turn")).toContainText("Проверьте расходы на кредиты.");
    await assistant.getByRole("button", { name: "Свернуть", exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  });
}
