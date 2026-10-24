import { test, expect, type Page } from "@playwright/test";

// SPR3-07: три ширины (телефон, планшет, ноутбук), нижняя навигация на телефоне, кэш ленты при возврате
// и экран «нет доступа» для чужой компании. Разбор — только быстрый (без модели): версию LLM не запрашиваем.

const api = process.env.E2E_API_URL || "http://localhost:8000";
const WIDTHS = [
  { name: "телефон", width: 375, height: 812, bottomNav: true },
  { name: "планшет", width: 768, height: 1024, bottomNav: true },
  { name: "ноутбук", width: 1280, height: 800, bottomNav: false },
];

async function login(page: Page): Promise<string> {
  const email = `e2e-resp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;
  const reg = await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна Морозова", email, password: "e2e-password-1" } });
  expect(reg.ok()).toBeTruthy();
  const lookup = await page.request.get(`${api}/api/v1/companies/lookup?limit=50`);
  const free = ((await lookup.json()).items as { company_id: string; claimed: boolean }[]).filter((c) => !c.claimed);
  expect(free.length).toBeGreaterThan(0);
  const claim = await page.request.post(`${api}/api/v1/companies/${free[0].company_id}/claim`, { data: { role: "cfo" } });
  expect(claim.ok()).toBeTruthy();
  // Только быстрый разбор: запрос версии модели обрывается, страница показывает карточку на правилах.
  await page.route("**/api/v1/insights", async (route) => {
    if (route.request().method() === "POST" && !route.request().postDataJSON()?.fast) await route.abort();
    else await route.fallback();
  });
  return free[0].company_id;
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "страница шире экрана").toBeLessThanOrEqual(1);
}

for (const size of WIDTHS) {
  test(`${size.name} ${size.width}px: главная, лента и разбор без горизонтальной прокрутки`, async ({ page }) => {
    await page.setViewportSize({ width: size.width, height: size.height });
    await login(page);
    const bottomNav = page.getByRole("navigation", { name: "Разделы" });

    await page.goto("/");
    await expect(page.getByRole("region", { name: "Альфа.Пульс на главной" })).toBeVisible();
    await noHorizontalScroll(page);
    if (size.bottomNav) await expect(bottomNav).toBeVisible();
    else await expect(bottomNav).toBeHidden();

    await page.goto("/pulse");
    await expect(page.getByTestId("news-card").first()).toBeVisible();
    await noHorizontalScroll(page);

    await page.getByTestId("news-card").first().getByRole("link").first().click();
    await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible({ timeout: 30_000 });
    await noHorizontalScroll(page);
    await page.screenshot({ path: `test-results/responsive-${size.width}.png` });

    if (size.bottomNav) {
      await bottomNav.getByRole("link", { name: "Аналитика" }).click();
      await expect(page).toHaveURL(/\/pulse\/analytics$/);
      await expect(bottomNav.getByRole("link", { name: "Аналитика" })).toHaveAttribute("aria-current", "page");
      await noHorizontalScroll(page);
    }
  });
}

test("лента → разбор → назад: лента из кэша, без повторного запроса", async ({ page }) => {
  await login(page);
  let feedRequests = 0;
  page.on("request", (r) => { if (new URL(r.url()).pathname.endsWith("/api/v1/feed")) feedRequests += 1; });
  await page.goto("/pulse");
  await expect(page.getByTestId("news-card").first()).toBeVisible();
  const before = feedRequests;
  expect(before).toBeGreaterThan(0);
  await page.getByTestId("news-card").first().getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible({ timeout: 30_000 });
  await page.goBack();
  await expect(page.getByTestId("news-card").first()).toBeVisible();
  expect(feedRequests).toBe(before);
});

test("ссылка на чужую компанию — экран «нет доступа», сервер отвечает 403", async ({ page }) => {
  const mine = await login(page);
  const lookup = await page.request.get(`${api}/api/v1/companies/lookup?limit=50`);
  const foreign = ((await lookup.json()).items as { company_id: string }[]).find((c) => c.company_id !== mine)!.company_id;
  const direct = await page.request.get(`${api}/api/v1/companies/${foreign}`);
  expect(direct.status()).toBe(403);

  await page.goto(`/pulse?company=${encodeURIComponent(foreign)}`);
  await expect(page.getByRole("heading", { name: "Нет доступа к компании" })).toBeVisible();
  await expect(page.getByTestId("news-card")).toHaveCount(0);
  await page.getByRole("link", { name: /^Открыть «/ }).click();
  await expect(page.getByTestId("news-card").first()).toBeVisible();
});

test("главная при прогретом API: LCP ≤ 2,5 с", async ({ page }) => {
  await login(page);
  await page.goto("/");
  await expect(page.getByTestId("top-news").getByRole("listitem").first()).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("top-news").getByRole("listitem").first()).toBeVisible();
  const lcp = await page.evaluate(() => new Promise<number>((resolve) => {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      resolve(entries[entries.length - 1].startTime);
    }).observe({ type: "largest-contentful-paint", buffered: true });
  }));
  console.log(`LCP главной: ${Math.round(lcp)} мс`);
  expect(lcp).toBeLessThanOrEqual(2500);
});

for (const width of [768, 1024]) {
  test(`планшет ${width}px: лента рядом с разбором, переход к следующей новости`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 768 ? 1024 : 768 });
    await login(page);
    await page.goto("/pulse");
    await page.getByTestId("news-card").first().getByRole("link").first().click();
    const rail = page.getByRole("complementary", { name: "Лента рядом с разбором" });
    await expect(rail).toBeVisible();
    await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible({ timeout: 30_000 });
    const railBox = await rail.boundingBox();
    const insightBox = await page.getByRole("heading", { name: "1. Что произошло" }).boundingBox();
    expect(railBox!.x + railBox!.width).toBeLessThanOrEqual(insightBox!.x);  // рядом, а не друг под другом
    await noHorizontalScroll(page);
    await page.screenshot({ path: `test-results/tablet-split-${width}.png` });

    const next = rail.getByRole("link").nth(1);
    const href = (await next.getAttribute("href"))!;
    await next.click();
    await expect(page).toHaveURL((url) => url.pathname === href);
    await expect(rail.locator("a[aria-current=page]")).toHaveAttribute("href", href);
  });
}

test("ноутбук: колонки ленты рядом с разбором нет", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await login(page);
  await page.goto("/pulse");
  await page.getByTestId("news-card").first().getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("complementary", { name: "Лента рядом с разбором" })).toBeHidden();
});
