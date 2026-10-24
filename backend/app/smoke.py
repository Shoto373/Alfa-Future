"""Быстрая проверка запущенного сервиса (локально или на проде) — перед защитой и после выкладки.

    docker compose -f compose.yaml exec backend python -m app.smoke
    python -m app.smoke --base-url https://pointers-team.online --front https://pointers-team.online

Ничего не создает: не регистрирует пользователей и не привязывает компании, поэтому безопасна на проде.
Проверки разбора и бюджета — под существующими учетными записями из переменных окружения
(не из аргументов, чтобы пароль не остался в истории команд):
  SMOKE_EMAIL, SMOKE_PASSWORD                    — участник компании: лента, разбор, разбор из кэша ≤ 2 с;
  SMOKE_OPERATOR_EMAIL, SMOKE_OPERATOR_PASSWORD  — сотрудник банка: бюджет LLM не превышен.
Без них эти проверки пропускаются. Модель не вызывается: разборы запрашиваются в быстром режиме.
Код выхода 1, если хотя бы одна проверка не прошла.
"""

import argparse
import os
import sys
import time
import uuid

import httpx

CACHE_SECONDS = 2.0


class Smoke:
    def __init__(self, base: str):
        self.api = base.rstrip("/") + "/api/v1"
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
        return ok

    def skip(self, name: str, why: str) -> None:
        print(f"SKIP {name} — {why}")

    def client(self) -> httpx.Client:
        return httpx.Client(timeout=30, follow_redirects=True)

    def login(self, c: httpx.Client, email: str, password: str) -> httpx.Response:
        return c.post(f"{self.api}/auth/login", json={"email": email, "password": password})

    def meta(self) -> None:
        with self.client() as c:
            r = c.get(f"{self.api}/meta")
        if not self.check("сервис отвечает (/meta)", r.status_code == 200, f"HTTP {r.status_code}"):
            return
        m = r.json()
        p = m.get("pipeline") or {}
        self.check("конвейер новостей без ошибки", not p.get("error"),
                   f"состояние {p.get('state')}, интервал {p.get('interval_minutes')} мин, последний запуск {p.get('started_at')}")
        self.check("в базе есть новости", (m.get("news") or 0) > 0, f"{m.get('news')} новостей")
        self.check("расходы LLM не открыты без входа", "llm_usage" not in (m.get("llm") or {}))

    def brute_force(self) -> None:
        email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"  # несуществующий адрес: ничей вход не блокируется
        with self.client() as c:
            codes = [self.login(c, email, "wrong-password").status_code for _ in range(6)]
        self.check("подбор пароля блокируется (429)", codes[:5] == [401] * 5 and codes[5] == 429, f"ответы {codes}")

    def member(self, email: str, password: str) -> None:
        with self.client() as c:
            if not self.check("вход участника компании", self.login(c, email, password).status_code == 200):
                return
            me = c.get(f"{self.api}/auth/me").json()
            if not self.check("у участника есть компания", bool(me.get("memberships"))):
                return
            company_id = me["memberships"][0]["company_id"]
            r = c.get(f"{self.api}/feed", params={"company_id": company_id, "limit": 5})
            items = r.json().get("items", []) if r.status_code == 200 else []
            if not self.check("лента компании", bool(items), f"HTTP {r.status_code}, новостей {len(items)}"):
                return
            body = {"company_id": company_id, "news_id": items[0]["news"]["news_id"], "fast": True}
            first = c.post(f"{self.api}/insights", json=body)
            self.check("разбор новости", first.status_code == 200 and bool(first.json().get("headline") and first.json().get("sources")),
                       f"HTTP {first.status_code}, режим {first.json().get('mode') if first.status_code == 200 else '—'}")
            started = time.perf_counter()
            again = c.post(f"{self.api}/insights", json=body)
            took = time.perf_counter() - started
            self.check(f"повторный разбор из кэша ≤ {CACHE_SECONDS:g} с", again.status_code == 200 and took <= CACHE_SECONDS,
                       f"{took:.2f} с")
            c.post(f"{self.api}/auth/logout")

    def operator(self, email: str, password: str) -> None:
        with self.client() as c:
            if not self.check("вход сотрудника банка", self.login(c, email, password).status_code == 200):
                return
            r = c.get(f"{self.api}/metrics")
            if not self.check("метрики открываются сотруднику", r.status_code == 200, f"HTTP {r.status_code}"):
                return
            u = r.json()["ai"]["llm_usage"]
            self.check("бюджет LLM не превышен", u["cost"] <= u["cost_limit"] and u["tokens"] <= u["limit"],
                       f"потрачено {u['cost']} из {u['cost_limit']} ₽, токенов {u['tokens']} из {u['limit']}")
            c.post(f"{self.api}/auth/logout")

    def front(self, url: str) -> None:
        try:
            r = httpx.get(url, timeout=30, follow_redirects=True)
            self.check("интерфейс открывается", r.status_code == 200, f"HTTP {r.status_code}")
        except httpx.HTTPError as exc:
            self.check("интерфейс открывается", False, type(exc).__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000", help="адрес backend или сайта с /api")
    ap.add_argument("--front", help="адрес интерфейса, например http://localhost:3000")
    args = ap.parse_args()

    s = Smoke(args.base_url)
    try:
        s.meta()
        s.brute_force()
        env = os.environ.get
        if env("SMOKE_EMAIL") and env("SMOKE_PASSWORD"):
            s.member(env("SMOKE_EMAIL"), env("SMOKE_PASSWORD"))
        else:
            s.skip("лента, разбор и кэш", "не заданы SMOKE_EMAIL и SMOKE_PASSWORD")
        if env("SMOKE_OPERATOR_EMAIL") and env("SMOKE_OPERATOR_PASSWORD"):
            s.operator(env("SMOKE_OPERATOR_EMAIL"), env("SMOKE_OPERATOR_PASSWORD"))
        else:
            s.skip("бюджет LLM", "не заданы SMOKE_OPERATOR_EMAIL и SMOKE_OPERATOR_PASSWORD")
        if args.front:
            s.front(args.front)
    except httpx.HTTPError as exc:
        s.check("сервис доступен", False, f"{type(exc).__name__}: {exc}")
    print("Итог:", "все проверки прошли" if not s.failed else f"не прошло проверок: {s.failed}")
    return 1 if s.failed else 0


if __name__ == "__main__":
    sys.exit(main())
