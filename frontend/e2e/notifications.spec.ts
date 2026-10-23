import { test, expect } from "@playwright/test";
import type { FeedItem } from "../lib/types";

const items: FeedItem[] = Array.from({ length: 12 }, (_, index) => ({
  news: {
    news_id: `notification-${index}`,
    title: `Событие ${index + 1}: изменение условий финансирования и новые возможности для производственных компаний`,
    lead: "Подробности события для компании.",
    source: "Новости экономики",
    url: null,
    kind: "seed",
    published_at: "2026-10-23T09:00:00Z",
    topics: [],
    sectors: [],
    countries: [],
    direction: null,
    duplicates: 0,
  },
  relevance: { score: 90, reasons: [] },
  cached_insight_id: null,
}));

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 900, height: 500 },
  { width: 390, height: 600 },
  { width: 844, height: 300 },
]) {
  test(`уведомления прокручиваются внутри меню ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/auth/me")) {
        await route.fulfill({ json: {
          user_id: "notifications-user", name: "Анна", email: "anna@example.com",
          memberships: [{
            company_id: "notifications-company",
            company_name: "ООО «Производственная компания с длинным названием»",
            role: "cfo", is_admin: false, is_founder: false,
          }],
        } });
      } else if (url.pathname.endsWith("/feed")) {
        await route.fulfill({ json: { items, topic_counts: [] } });
      } else {
        await route.fulfill({ status: 404, json: {} });
      }
    });

    await page.goto("/pulse");
    const trigger = page.getByRole("button", { name: /Уведомления Альфа.Пульс/ });
    await expect(trigger).toHaveAccessibleName(/непрочитанных 12/);
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: "Важные события" });
    const list = dialog.getByRole("region", { name: "Список уведомлений" });
    const footer = dialog.getByRole("link", { name: "Вся лента", exact: true });
    const markAll = dialog.getByRole("button", { name: "Прочитать все" });
    const last = list.getByRole("link").last();
    await expect(list.getByRole("listitem")).toHaveCount(10);
    await expect(footer).toBeInViewport({ ratio: 1 });
    await expect(markAll).toBeInViewport({ ratio: 1 });
    await expect(last).not.toBeInViewport();

    const panel = (await dialog.boundingBox())!;
    expect(panel.x).toBeGreaterThanOrEqual(0);
    expect(panel.x + panel.width).toBeLessThanOrEqual(viewport.width);
    expect(panel.y + panel.height).toBeLessThanOrEqual(viewport.height - 8);
    const footerBefore = await footer.boundingBox();

    await list.hover();
    await page.mouse.wheel(0, 4000);
    await expect(last).toBeInViewport({ ratio: 1 });
    await page.mouse.wheel(0, 4000);
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    expect(await footer.boundingBox()).toEqual(footerBefore);
    await expect(markAll).toBeInViewport({ ratio: 1 });

    // Клавиатура прокручивает ту же область; переход к последней новости не теряется.
    await list.focus();
    await page.keyboard.press("Home");
    await expect.poll(() => list.evaluate((element) => element.scrollTop)).toBe(0);
    await last.focus();
    await expect(last).toBeInViewport({ ratio: 1 });
    await expect(footer).toBeInViewport({ ratio: 1 });

    // При уменьшении высоты открытое меню пересчитывает доступное место.
    await page.setViewportSize({ width: viewport.width, height: 300 });
    await expect(footer).toBeInViewport({ ratio: 1 });
    await markAll.click();
    await expect(trigger).toHaveAccessibleName(/нет новых/);
    await list.evaluate((element) => element.scrollTo(0, 0));
    await expect(list.getByText("Новых событий нет. Ниже история.")).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
}
