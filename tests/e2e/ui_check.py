"""Проверка пользовательского сценария в headless Chromium (Playwright, необязательный инструмент).

    python -m pip install playwright==1.55.0 && python -m playwright install chromium
    python tests/e2e/ui_check.py --front http://localhost:3000 [--shots ./shots]

Сценарий: вход демо-пользователем -> главная с точкой входа -> лента ->
разбор новости -> ход анализа -> уточняющий вопрос -> оценка -> смена роли
и компании -> своя новость -> аналитика банка -> качество -> мобильная ширина.
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

results = []


def step(name, fn):
    try:
        fn()
        results.append((name, "OK", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((name, "FAIL", str(exc).splitlines()[0][:220]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--front", default="http://localhost:3000")
    ap.add_argument("--shots", default=None)
    args = ap.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    F = args.front.rstrip("/")

    def shot(page, name):
        if shots:
            page.screenshot(path=str(shots / f"{name}.png"), full_page=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        print("browser:", browser.version)

        def login():
            page.goto(F + "/")
            page.wait_for_url("**/login")
            expect(page.get_by_text("Вход для проверки")).to_be_visible()
            shot(page, "01_login")
            page.locator(".login-user").first.click()
            page.wait_for_url(F + "/")

        def home():
            expect(page.get_by_role("link", name="Открыть ленту")).to_be_visible()
            expect(page.locator(".nav-item.accent")).to_contain_text("Альфа.Пульс")
            expect(page.locator(".pulse-hero .news-card").first).to_be_visible(timeout=15000)
            shot(page, "02_home")

        def feed():
            page.get_by_role("link", name="Открыть ленту").click()
            page.wait_for_url("**/pulse")
            expect(page.locator(".feed .news-card").first).to_be_visible(timeout=15000)
            expect(page.locator(".company-panel")).to_be_visible(timeout=15000)
            assert page.locator(".feed .reason").count() > 0
            shot(page, "03_feed")

        state = {}

        def insight():
            state["first_title"] = page.locator(".feed .news-card h3").first.inner_text()
            page.locator(".feed .news-card .btn-primary").first.click()
            page.wait_for_url("**/pulse/n/**")
            expect(page.locator(".insight-head h1")).to_be_visible(timeout=60000)
            for t in ["1. Что произошло", "2. Почему это важно для компании", "3. Какие последствия возможны",
                      "4. Что можно сделать", "5. Как это оценивает Альфа-Банк", "6. На чем основан вывод"]:
                expect(page.get_by_role("heading", name=t)).to_be_visible()
            assert page.locator(".origin-bank").count() > 0, "нет утверждений банка"
            assert page.locator(".origin-ai").count() > 0, "нет выводов AI"
            assert page.locator(".sources li").count() >= 2
            shot(page, "04_insight")

        def trace():
            page.get_by_role("button", name="Как получен вывод").click()
            expect(page.locator(".trace li").first).to_be_visible()
            assert page.locator(".trace li").count() >= 6
            shot(page, "05_trace")

        def chat():
            page.get_by_role("button", name="Покажи в разрезе контрагентов").click()
            expect(page.locator(".chat-a").first).to_be_visible(timeout=30000)
            expect(page.locator(".chat-a").first).to_contain_text("контрагент")
            page.locator(".chat-form input").fill("Какие источники использованы?")
            page.get_by_role("button", name="Спросить").click()
            expect(page.locator(".chat-a")).to_have_count(2, timeout=30000)
            page.locator(".chat").scroll_into_view_if_needed()
            shot(page, "06_chat")

        def feedback():
            page.locator(".feedback button[aria-label='Полезно']").first.click()
            expect(page.get_by_text("Спасибо за оценку").first).to_be_visible()

        def role_switch():
            before = page.locator(".insight-head h1").inner_text()
            page.locator(".role-select select").select_option("treasurer")
            expect(page.locator(".insight-head h1")).to_be_visible(timeout=60000)
            page.wait_for_timeout(800)
            page.goto(F + "/pulse")
            expect(page.locator(".feed .news-card").first).to_be_visible(timeout=15000)
            assert "Руководитель казначейства" in page.locator(".page-head").inner_text()
            state["role_before"] = before

        def company_switch():
            name_before = page.locator(".switcher-name").inner_text()
            page.locator(".switcher-btn").click()
            page.locator(".switcher-pop li button").nth(3).click()
            expect(page.locator(".switcher-name")).not_to_have_text(name_before)
            expect(page.locator(".feed .news-card").first).to_be_visible(timeout=15000)

        def own_news():
            page.locator("textarea").fill("Правительство одобрило снижение экспортных пошлин на удобрения и зерно с 1 декабря 2026 года, "
                                          "что поддержит поставки в Китай и Турцию и расчеты в юанях.")
            page.get_by_role("button", name="Разобрать").click()
            page.wait_for_url("**/pulse/n/**")
            expect(page.locator(".insight-head h1")).to_be_visible(timeout=60000)
            shot(page, "07_own_news")

        def analytics():
            page.goto(F + "/pulse/analytics")
            expect(page.locator(".docs .card").first).to_be_visible(timeout=15000)
            assert page.locator(".docs .card").count() == 9
            shot(page, "08_analytics")

        def quality():
            page.goto(F + "/pulse/quality")
            expect(page.get_by_text("Журнал обращений к инструментам")).to_be_visible(timeout=15000)
            assert page.locator(".table tbody tr").count() > 0
            shot(page, "09_quality")

        def mobile():
            m = browser.new_page(viewport={"width": 375, "height": 812}, locale="ru-RU")
            m.goto(F + "/login")
            m.locator(".login-user").first.click()
            m.wait_for_url(F + "/")
            m.goto(F + "/pulse")
            expect(m.locator(".feed .news-card").first).to_be_visible(timeout=15000)
            assert m.evaluate("document.documentElement.scrollWidth <= 375"), "горизонтальная прокрутка"
            if shots:
                m.screenshot(path=str(shots / "10_mobile.png"), full_page=False)

        for name, fn in [("вход демо-пользователем", login), ("главная: точка входа и топ-новости", home),
                         ("персональная лента и контекст компании", feed), ("разбор: 6 разделов, банк отделен от AI", insight),
                         ("ход анализа агента", trace), ("уточняющие вопросы", chat), ("оценка раздела", feedback),
                         ("смена роли", role_switch), ("смена компании", company_switch), ("своя новость", own_news),
                         ("аналитика банка", analytics), ("качество и аудит", quality), ("мобильная ширина 375px", mobile)]:
            step(name, fn)
        browser.close()

    sys.stdout.reconfigure(encoding="utf-8")
    for name, status, err in results:
        print(f"{status:4} {name} {err}")
    sys.exit(any(r[1] != "OK" for r in results))


if __name__ == "__main__":
    main()
