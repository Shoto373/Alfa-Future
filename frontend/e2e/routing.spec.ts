import { test, expect } from "@playwright/test";

test("фильтр темы синхронизирован с URL, перезагрузкой и историей", async ({ page }) => {
  const specialTopic = "ставка & курс%";
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/me")) {
      await route.fulfill({ json: {
        user_id: "routing-user", name: "Тест", email: "routing@example.com",
        memberships: [{ company_id: "routing-company", company_name: "Тестовая компания", role: "cfo", is_admin: false, is_founder: false }],
      } });
    } else if (url.pathname.endsWith("/feed")) {
      await route.fulfill({ json: { items: [], topic_counts: [
        { topic: "key_rate", name: "Ключевая ставка", count: 1 },
        { topic: specialTopic, name: "Ставка и курс", count: 1 },
      ] } });
    } else {
      await route.fulfill({ status: 404, json: {} });
    }
  });

  await page.goto("/pulse?topic=key_rate&keep=1");
  const chips = page.getByRole("toolbar", { name: "Фильтр по темам" });
  const rate = chips.getByRole("button", { name: "Ключевая ставка" });
  const special = chips.getByRole("button", { name: "Ставка и курс" });
  const all = chips.getByRole("button", { name: "Все темы", exact: true });
  await expect(rate).toHaveClass("chip on");

  const filtered = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/feed") && url.searchParams.get("topic") === specialTopic;
  });
  await special.click();
  await filtered;
  await expect(special).toHaveClass("chip on");
  expect(new URL(page.url()).searchParams.get("topic")).toBe(specialTopic);
  expect(new URL(page.url()).searchParams.get("keep")).toBe("1");

  await page.reload();
  await expect(special).toHaveClass("chip on");
  await all.click();
  await expect(page).toHaveURL(/\/pulse\?keep=1$/);
  await expect(all).toHaveClass("chip on");
  await page.goBack();
  await expect(special).toHaveClass("chip on");
  await page.goBack();
  await expect(rate).toHaveClass("chip on");
  await page.goForward();
  await expect(special).toHaveClass("chip on");
});
