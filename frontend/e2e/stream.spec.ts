import { test, expect } from "@playwright/test";

// SPR4-03: разбор приходит потоком (SSE через nginx), без запасного POST /insights; первый раздел — сразу.
const api = process.env.E2E_API_URL || "http://localhost:8000";

test("разбор потоком: SSE через nginx, без запасного запроса", async ({ page }) => {
  const email = `e2e-sse-${Date.now()}@example.com`;
  expect((await page.request.post(`${api}/api/v1/auth/register`, { data: { name: "Анна", email, password: "e2e-password-1" } })).ok()).toBeTruthy();
  const free = ((await (await page.request.get(`${api}/api/v1/companies/lookup?limit=50`)).json()).items as { company_id: string; claimed: boolean }[])
    .find((c) => !c.claimed)!;
  expect((await page.request.post(`${api}/api/v1/companies/${free.company_id}/claim`, { data: { role: "cfo" } })).ok()).toBeTruthy();

  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/api/v1/insights")) posts.push(r.url()); });
  const stream = page.waitForResponse((r) => r.url().includes("/api/v1/insights/stream"));
  await page.goto("/pulse");
  const started = Date.now();
  await page.getByTestId("news-card").first().getByRole("link").first().click();
  expect((await stream).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "1. Что произошло" })).toBeVisible();
  expect(Date.now() - started, "первый раздел — за 3 с").toBeLessThan(3000);
  expect(posts, "поток работает — запасной POST не нужен").toEqual([]);
});
