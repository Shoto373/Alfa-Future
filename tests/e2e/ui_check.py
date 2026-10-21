"""UI-проверки чек-листа docs/sprint-01/acceptance.md в headless Chromium.

Необязательный инструмент приемки, не входит в зависимости проекта:

    python -m pip install playwright==1.55.0 && python -m playwright install chromium
    docker compose -f compose.yaml up --build -d
    (cd frontend && NEXT_PUBLIC_API_MOCK=empty npx next dev -p 3001)   # для шага 11
    python tests/e2e/ui_check.py http://localhost:3001

Шаги 8-10 останавливают и снова запускают контейнер backend.
"""
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

FRONT = "http://localhost:3000"
MOCK_FRONT = sys.argv[1] if len(sys.argv) > 1 else None
results = []


def step(n, name, fn):
    try:
        fn()
        results.append((n, name, "OK", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((n, name, "FAIL", str(exc).splitlines()[0][:200]))


def compose(*args):
    subprocess.run(["docker", "compose", "-f", "compose.yaml", *args], cwd=Path(__file__).resolve().parents[2],
                   check=True, capture_output=True)


def wait_backend():
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen("http://localhost:8000/healthz", timeout=2)
            return
        except OSError:
            time.sleep(1)
    raise RuntimeError("backend not healthy")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    # Задержка ответа /insights внутри браузера: window.__delayMs задается тестом.
    page.add_init_script("""
      const orig = window.fetch;
      window.__delayMs = 0;
      window.fetch = async (...args) => {
        const res = await orig(...args);
        if (String(args[0]).includes('/api/v1/insights') && window.__delayMs) {
          await new Promise(r => setTimeout(r, window.__delayMs));
        }
        return res;
      };
    """)
    print("browser:", browser.version)

    def s1():
        page.goto(FRONT)
        expect(page.get_by_text("Демонстрационный макет хакатона")).to_be_visible()
        page.get_by_role("link", name="Открыть новостную аналитику").click()
        page.wait_for_url("**/analytics")

    def s2():
        expect(page.locator("select option")).to_have_count(2, timeout=10000)

    def s3():
        hdr = page.locator(".analytics-header")
        expect(hdr.get_by_text("Тестовые данные")).to_be_visible()
        expect(hdr.get_by_text("Анализ без LLM")).to_be_visible()

    def s4():
        page.select_option("select", "demo_company_001")
        page.get_by_label("CFO — финансовый директор").check()
        page.evaluate("window.__delayMs = 1500")
        page.get_by_role("button", name="Запустить анализ").click()
        expect(page.get_by_role("button", name="Анализируем…")).to_be_disabled()
        card = page.get_by_role("article", name="Карточка анализа")
        expect(card).to_be_visible(timeout=10000)
        page.evaluate("window.__delayMs = 0")
        for h in ["Факты", "Риски", "Возможности", "Действия", "Неопределенность", "Источники"]:
            expect(card.get_by_role("heading", name=h)).to_be_visible()
        expect(card.get_by_text("Аналитика банка еще не подключена")).to_be_visible()
        expect(card).to_contain_text("кредитные обязательства")

    def s5():
        page.select_option("select", "demo_company_002")
        page.get_by_label("CEO — генеральный директор").check()
        page.get_by_role("button", name="Запустить анализ").click()
        card = page.get_by_role("article", name="Карточка анализа")
        expect(card).to_contain_text("депозитные инструменты", timeout=10000)
        expect(card).to_contain_text("планы финансирования")

    def s6():
        page.get_by_label("CFO — финансовый директор").check()
        expect(page.get_by_role("article", name="Карточка анализа")).to_have_count(0)

    def s7():
        page.select_option("select", "demo_company_001")
        page.evaluate("window.__delayMs = 2000")
        page.get_by_role("button", name="Запустить анализ").click()
        page.wait_for_timeout(300)
        page.select_option("select", "demo_company_002")
        page.wait_for_timeout(3000)
        page.evaluate("window.__delayMs = 0")
        expect(page.get_by_role("article", name="Карточка анализа")).to_have_count(0)
        expect(page.get_by_role("button", name="Запустить анализ")).to_be_enabled()

    def s8():
        compose("stop", "backend")
        page.get_by_role("button", name="Запустить анализ").click()
        alert = page.locator(".state-error")
        expect(alert).to_contain_text("Нет связи с сервером", timeout=12000)
        expect(alert.get_by_role("button", name="Повторить")).to_be_visible()

    def s10():
        page.reload()
        alert = page.locator(".state-error")
        expect(alert).to_contain_text("Не удалось загрузить компании", timeout=12000)
        expect(alert.get_by_role("button", name="Повторить")).to_be_visible()

    def s9():
        compose("start", "backend")
        wait_backend()
        page.locator(".state-error").get_by_role("button", name="Повторить").click()
        expect(page.locator("select option")).to_have_count(2, timeout=10000)
        page.get_by_role("button", name="Запустить анализ").click()
        expect(page.get_by_role("article", name="Карточка анализа")).to_be_visible(timeout=10000)

    def s11():
        mp = browser.new_page()
        mp.goto(MOCK_FRONT + "/analytics")
        expect(mp.get_by_text("Список компаний пуст")).to_be_visible(timeout=60000)
        expect(mp.get_by_text("Локальный mock API: empty")).to_be_visible()

    def phone():
        m = browser.new_page(viewport={"width": 375, "height": 800})
        m.goto(FRONT + "/analytics")
        expect(m.locator("select option")).to_have_count(2, timeout=10000)
        assert m.evaluate("document.documentElement.scrollWidth <= 375"), "horizontal scroll"

    step(1, "главная, баннер, переход", s1)
    step(2, "загрузка списка, две компании", s2)
    step(3, "постоянные метки", s3)
    step(4, "001/CFO: блокировка кнопки, разделы, позиция банка", s4)
    step(5, "002/CEO: другая проекция", s5)
    step(6, "смена роли очищает карточку", s6)
    step(7, "смена выбора во время запроса", s7)
    step(8, "backend остановлен: ошибка и повтор", s8)
    step(10, "перезагрузка без backend: ошибка списка", s10)
    step(9, "backend запущен: повтор работает", s9)
    if MOCK_FRONT:
        step(11, "пустой список (mock empty)", s11)
    step(12, "ширина 375px без горизонтальной прокрутки", phone)
    browser.close()

sys.stdout.reconfigure(encoding="utf-8")
for n, name, status, err in sorted(results):
    print(f"{n:>2} {status:4} {name} {err}")
sys.exit(any(r[2] != "OK" for r in results))
