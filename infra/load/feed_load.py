"""Нагрузочный прогон (DoD спринта 3): N одновременных пользователей открывают ленту, главную и разбор.

    docker compose run --rm --no-deps -v ./infra/load:/load --entrypoint python worker /load/feed_load.py --users 50

Запускается в отдельном контейнере, а не в экземпляре API: иначе генератор делит с ним процессор.

Каждый виртуальный пользователь входит демо-учеткой (свой сеанс) и по кругу запрашивает ленту компании,
сведения о компании и быстрый разбор новости из ленты (на правилах: модель не вызывается).
Итог: число запросов, ответы 5xx, p50/p95 ленты и разбора. Код выхода 1 — есть 5xx или p95 ленты выше порога.
"""

import argparse
import asyncio
import os
import random
import statistics
import time

import httpx


async def login(client_args: dict, base: str, email: str, password: str) -> tuple[httpx.Cookies, str]:
    """Один вход на всех виртуальных пользователей: вход ограничен по частоте (защита от подбора)."""
    async with httpx.AsyncClient(base_url=base, timeout=60, **client_args) as c:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return c.cookies, r.json()["memberships"][0]["company_id"]


async def user(client_args: dict, base: str, session: tuple, deadline: float, out: dict, think: float) -> None:
    cookies, company = session
    async with httpx.AsyncClient(base_url=base, timeout=60, cookies=cookies, **client_args) as c:
        news_id, rounds = None, 0
        while time.monotonic() < deadline:
            rounds += 1
            for name, call in (("feed", lambda: c.get("/api/v1/feed", params={"company_id": company, "limit": 500})),
                               ("company", lambda: c.get(f"/api/v1/companies/{company}"))):
                started = time.perf_counter()
                resp = await call()
                out.setdefault(name, []).append(time.perf_counter() - started)
                out["status"].append(resp.status_code)
                # Ответ разбирается только один раз: генератор однопоточный, разбор 400 КБ JSON на каждом
                # запросе задерживал бы следующие и завышал бы измеренное время ответа сервера.
                if name == "feed" and news_id is None and resp.status_code == 200:
                    items = resp.json()["items"][:10]
                    news_id = items[rounds % len(items)]["news"]["news_id"] if items else None
            await asyncio.sleep(think * (0.5 + random.random()))  # пользователь читает ленту, а не жмет F5
            # Разбор — каждый пятый круг: у одного пользователя лимит 30 разборов в минуту (429 ожидаемы и не ошибка).
            if news_id is None or rounds % 5:
                continue
            started = time.perf_counter()
            resp = await c.post("/api/v1/insights", json={"company_id": company, "news_id": news_id, "fast": True})
            out.setdefault("insight", []).append(time.perf_counter() - started)
            out["status"].append(resp.status_code)


def p(values: list[float], q: float) -> float:
    return statistics.quantiles(values, n=100)[q - 1] if len(values) >= 2 else (values[0] if values else 0.0)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://nginx")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--feed-p95", type=float, default=1.0, help="порог p95 ленты, с")
    parser.add_argument("--think", type=float, default=3.0,
                        help="пауза пользователя между открытиями ленты, с (0 — непрерывный поток запросов, стресс)")
    args = parser.parse_args()
    email = os.environ.get("LOAD_EMAIL", "demo@alfa.test")
    password = os.environ.get("LOAD_PASSWORD", os.environ.get("DEMO_PASSWORD", "alfa-demo-2026"))
    out: dict = {"status": []}
    # Origin фронтенда: изменяющие запросы без него проходят, с чужим — отклоняются (как у браузера).
    client_args = {"headers": {"Origin": os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")}}
    session = await login(client_args, args.base_url, email, password)
    deadline = time.monotonic() + args.seconds
    await asyncio.gather(*(user(client_args, args.base_url, session, deadline, out, args.think) for _ in range(args.users)))
    errors = sum(1 for s in out["status"] if s >= 500)
    limited = sum(1 for s in out["status"] if s == 429)
    print(f"пользователей {args.users}, пауза {args.think} с, {args.seconds} с: запросов {len(out['status'])}, 5xx {errors}, 429 {limited}")
    for name in ("feed", "company", "insight"):
        values = out.get(name, [])
        print(f"  {name}: {len(values)} запросов, p50 {p(values, 50):.3f} с, p95 {p(values, 95):.3f} с")
    feed_p95 = p(out.get("feed", [0.0]), 95)
    ok = errors == 0 and feed_p95 <= args.feed_p95
    print("ИТОГ:", "ок" if ok else "не выполнено", f"(p95 ленты {feed_p95:.3f} с, порог {args.feed_p95} с)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
