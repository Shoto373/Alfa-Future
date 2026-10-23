import { test, expect, type Page } from "@playwright/test";
import type { Member } from "../lib/types";

const COMPANY = "ООО «Логист-Ниндзя Восток»";

async function mockProfile(page: Page, admin = true) {
  let members: Member[] = [
    { member_id: "self", user_id: "user", name: "Анна", email: "anna@example.com", role: "ceo", is_admin: admin, is_founder: true, status: "active" },
    { member_id: "other", user_id: "colleague", name: "Мария", email: "maria@example.com", role: "cfo", is_admin: true, is_founder: false, status: "active" },
    { member_id: "invited", user_id: null, name: null, email: "invite@example.com", role: "accountant", is_admin: false, is_founder: false, status: "invited" },
  ];
  const mutations: { member: string; method: string; data?: unknown }[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/auth/me")) {
      await route.fulfill({ json: {
        user_id: "user", name: "Анна", email: "anna@example.com",
        memberships: [{ company_id: "company", company_name: COMPANY, role: "ceo", is_admin: admin, is_founder: true }],
      } });
    } else if (url.pathname.endsWith("/members")) {
      await route.fulfill({ json: { members } });
    } else if (url.pathname.includes("/members/")) {
      const id = url.pathname.split("/").at(-1)!;
      if (method === "PATCH") {
        const data = route.request().postDataJSON();
        mutations.push({ member: id, method, data });
        members = members.map((member) => member.member_id === id ? { ...member, ...data } : member);
        await route.fulfill({ json: members.find((member) => member.member_id === id) });
      } else if (method === "DELETE") {
        mutations.push({ member: id, method });
        members = members.filter((member) => member.member_id !== id);
        await route.fulfill({ status: 204 });
      } else {
        await route.fulfill({ status: 405 });
      }
    } else if (url.pathname.endsWith("/feed")) {
      await route.fulfill({ json: { items: [], topic_counts: [] } });
    } else {
      await route.fulfill({ status: 404, json: {} });
    }
  });
  return mutations;
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`профиль скрывает собственные действия и управляет участниками через меню ${viewport.width}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const mutations = await mockProfile(page);
    await page.goto("/profile");
    const company = page.getByRole("region", { name: COMPANY, exact: true });
    const header = company.locator(":scope > div").first();
    await expect(header.getByText("Генеральный директор", { exact: true })).toHaveCount(0);
    await expect(header.getByText("Администратор", { exact: true })).toHaveCount(0);
    await expect(header.getByRole("button", { name: "Действия с компанией" })).toBeVisible();

    const self = company.getByRole("listitem").filter({ hasText: "Анна (вы)" });
    await expect(self.getByText("Генеральный директор", { exact: true })).toBeVisible();
    await expect(self.getByRole("combobox")).toHaveCount(0);
    await expect(self.getByRole("button")).toHaveCount(0);

    const other = company.getByRole("listitem").filter({ hasText: "maria@example.com" });
    const trigger = other.getByRole("button", { name: "Действия с участником: Мария", exact: true });
    await expect(other.getByRole("button", { name: "Снять админа", exact: true })).toHaveCount(0);
    await expect(other.getByRole("button", { name: "Удалить", exact: true })).toHaveCount(0);
    await trigger.click();
    const menu = other.getByRole("menu");
    const remove = menu.getByRole("menuitem", { name: "Удалить", exact: true });
    await expect(menu.getByRole("menuitem", { name: "Снять админа" })).toBeFocused();
    await expect(remove).toBeInViewport({ ratio: 1 });
    await page.keyboard.press("ArrowDown");
    await expect(remove).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(trigger).toBeFocused();

    await trigger.click();
    await menu.getByRole("menuitem", { name: "Снять админа" }).click();
    await expect(other.getByText("Администратор", { exact: true })).toHaveCount(0);
    await other.getByRole("combobox").selectOption("accountant");
    const confirmation = page.getByRole("dialog", { name: "Изменить роль участника?" });
    await expect(confirmation).toBeVisible();
    await expect(confirmation).toContainText("Мария");
    await expect(confirmation).toContainText("Финансовый директор");
    await expect(confirmation).toContainText("Главный бухгалтер");
    await expect(confirmation.getByRole("button", { name: "Отмена", exact: true })).toBeFocused();
    expect(mutations).toEqual([{ member: "other", method: "PATCH", data: { is_admin: false } }]);
    await confirmation.getByRole("button", { name: "Отмена", exact: true }).click();
    await expect(confirmation).toBeHidden();
    await expect(other.getByRole("combobox")).toHaveValue("cfo");
    await expect(other.getByRole("combobox")).toBeFocused();
    await other.getByRole("combobox").selectOption("accountant");
    await page.keyboard.press("Escape");
    await expect(confirmation).toBeHidden();
    await expect(other.getByRole("combobox")).toHaveValue("cfo");
    expect(mutations).toHaveLength(1);
    await other.getByRole("combobox").selectOption("accountant");
    await page.screenshot({ path: testInfo.outputPath("role-confirmation.png") });
    await confirmation.getByRole("button", { name: "Изменить роль", exact: true }).click();
    await expect(confirmation).toBeHidden();
    await expect(other.getByRole("combobox")).toHaveValue("accountant");
    await trigger.click();
    await expect(menu.getByRole("menuitem", { name: "Сделать админом" })).toBeVisible();
    await page.getByRole("heading", { name: "Участники", exact: true }).click();
    await expect(menu).toBeHidden();
    await trigger.click();
    await remove.click();
    await expect(other).toHaveCount(0);
    expect(mutations).toEqual([
      { member: "other", method: "PATCH", data: { is_admin: false } },
      { member: "other", method: "PATCH", data: { role: "accountant" } },
      { member: "other", method: "DELETE" },
    ]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("profile.png"), fullPage: true });
  });
}

test("обычный участник видит роли без элементов редактирования", async ({ page }) => {
  const mutations = await mockProfile(page, false);
  await page.goto("/profile");
  const company = page.getByRole("region", { name: COMPANY, exact: true });
  await expect(company.getByText("Мария", { exact: true })).toBeVisible();
  await expect(company.getByRole("combobox")).toHaveCount(0);
  await expect(company.getByRole("button", { name: /^Действия с участником:/ })).toHaveCount(0);
  await expect(company.getByRole("heading", { name: "Пригласить участника" })).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test("ошибка смены роли остаётся в модалке и позволяет повторить сохранение", async ({ page }) => {
  const mutations = await mockProfile(page);
  let fail = true;
  await page.route("**/api/v1/companies/company/members/other", async (route) => {
    if (fail) {
      fail = false;
      await route.fulfill({ status: 503, json: { error: {
        code: "UNAVAILABLE", message: "Не удалось сохранить роль. Повторите попытку.", retryable: true,
      } } });
    } else {
      await route.fallback();
    }
  });
  await page.goto("/profile");
  const role = page.getByRole("combobox", { name: "Роль: Мария", exact: true });
  await role.selectOption("accountant");
  const dialog = page.getByRole("dialog", { name: "Изменить роль участника?" });
  await dialog.getByRole("button", { name: "Изменить роль", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Не удалось сохранить роль");
  await expect(dialog).toBeVisible();
  await expect(role).toHaveValue("cfo");
  expect(mutations).toEqual([]);
  await dialog.getByRole("button", { name: "Изменить роль", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(role).toHaveValue("accountant");
  expect(mutations).toEqual([{ member: "other", method: "PATCH", data: { role: "accountant" } }]);
});
