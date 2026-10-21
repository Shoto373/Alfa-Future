"""Сквозной smoke-тест backend (только стандартная библиотека).

    python tests/e2e/smoke.py --base-url http://localhost:8000

Проходит основной сценарий кейса: компании -> персональная лента ->
разбор новости агентом -> уточняющий вопрос -> обратная связь -> метрики,
плюс новость, которой нет в демо-ленте, и ошибки API.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


class Checker:
    def __init__(self):
        self.failures, self.passed = [], 0

    def check(self, ok: bool, name: str, detail: object = "") -> bool:
        if ok:
            self.passed += 1
            print(f"  ok   {name}")
        else:
            self.failures.append(name)
            print(f"  FAIL {name} {str(detail)[:300]}")
        return ok


def call(base, method, path, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def wait(base, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if call(base, "GET", "/healthz", timeout=3)[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def check_insight(c: Checker, label: str, ins: dict, company_id: str, role: str, news_id: str):
    c.check((ins.get("company_id"), ins.get("role"), ins.get("news_id")) == (company_id, role, news_id), f"{label}: контекст запроса сохранен")
    c.check(ins.get("schema_version") == "1.0.0", f"{label}: schema_version 1.0.0")
    c.check(bool(ins.get("headline")) and ins.get("headline") != ins.get("title"), f"{label}: вывод не повторяет заголовок")
    for sec in ("why_important", "actions"):
        c.check(bool(ins.get(sec)), f"{label}: раздел {sec} заполнен")
    c.check(bool(ins.get("risks") or ins.get("opportunities")), f"{label}: есть риски или возможности")
    ids = {s["source_id"] for s in ins.get("sources", [])}
    claims = [cl for sec in ("why_important", "risks", "opportunities", "actions") for cl in ins.get(sec, [])]
    c.check(all(cl["source_ids"] and set(cl["source_ids"]) <= ids for cl in claims), f"{label}: каждый вывод связан с источником")
    bank = ins.get("bank_view", {})
    c.check(all(t["origin"] == "bank" for t in bank.get("theses", [])), f"{label}: позиция банка отделена от выводов AI")
    stages = [s["stage"] for s in ins.get("trace", [])]
    c.check({"plan", "tool", "check", "finalize"} <= set(stages), f"{label}: трасса агента", stages)
    c.check(ins.get("quality", {}).get("passed") is True, f"{label}: самопроверка пройдена", ins.get("quality"))


def run(base: str, wait_s: float) -> int:
    c = Checker()
    print(f"Smoke {base}")
    if not c.check(wait(base, wait_s), "backend отвечает на /healthz"):
        return finish(c)

    status, meta = call(base, "GET", "/api/v1/meta")
    c.check(status == 200 and meta["data"]["profiles"] > 0, "профили компаний построены", meta)
    c.check(meta["knowledge"]["documents"] >= 9, "база знаний банка загружена")

    status, companies = call(base, "GET", "/api/v1/companies?limit=50")
    items = companies.get("items", []) if isinstance(companies, dict) else []
    c.check(status == 200 and len(items) >= 2, "список компаний")
    if len(items) < 2:
        return finish(c)
    a, b = items[0]["company_id"], next(i["company_id"] for i in items if i["sector"] != items[0]["sector"])

    _, fa = call(base, "GET", f"/api/v1/feed?company_id={a}&role=cfo")
    _, fb = call(base, "GET", f"/api/v1/feed?company_id={b}&role=ceo")
    la, lb = fa.get("items", []), fb.get("items", [])
    c.check(bool(la) and bool(lb), "лента строится для двух компаний")
    c.check([i["relevance"]["score"] for i in la] == sorted([i["relevance"]["score"] for i in la], reverse=True), "лента отсортирована по релевантности")
    c.check(all(i["relevance"]["reasons"] for i in la[:3]), "у топ-новостей есть объяснение релевантности")
    c.check([(i["news"]["news_id"], i["relevance"]["score"]) for i in la[:5]] != [(i["news"]["news_id"], i["relevance"]["score"]) for i in lb[:5]],
            "ленты разных компаний и ролей отличаются")

    news_id = la[0]["news"]["news_id"]
    status, ins = call(base, "POST", "/api/v1/insights", {"company_id": a, "role": "cfo", "news_id": news_id})
    if c.check(status == 200, "разбор новости агентом", ins):
        check_insight(c, "разбор A/cfo", ins, a, "cfo", news_id)
        _, other = call(base, "POST", "/api/v1/insights", {"company_id": b, "role": "ceo", "news_id": news_id})
        c.check(other.get("headline") != ins.get("headline") or other.get("why_important") != ins.get("why_important"),
                "одна новость по-разному интерпретирована для разных компаний")
        status, ans = call(base, "POST", f"/api/v1/insights/{ins['insight_id']}/questions", {"question": "Какие источники использованы?"})
        c.check(status == 200 and ans.get("sources"), "уточняющий вопрос: ответ с источниками", ans)
        status, ans = call(base, "POST", f"/api/v1/insights/{ins['insight_id']}/questions", {"question": "Покажи в разрезе контрагентов"})
        c.check(status == 200 and ans.get("claims"), "уточняющий вопрос: другой разрез данных", ans)
        status, _ = call(base, "POST", "/api/v1/feedback", {"insight_id": ins["insight_id"], "rating": 1, "section": "risks"})
        c.check(status == 200, "обратная связь сохранена")

    status, added = call(base, "POST", "/api/v1/news", {"text": "Правительство одобрило снижение экспортных пошлин на удобрения и зерно "
                                                                 "с 1 декабря 2026 года, что должно поддержать поставки в Китай и Турцию."})
    if c.check(status == 200 and added["news"]["topics"], "новость пользователя классифицирована", added):
        nid = added["news"]["news_id"]
        status, ins2 = call(base, "POST", "/api/v1/insights", {"company_id": a, "role": "ceo", "news_id": nid})
        if c.check(status == 200, "ранее не показанная новость разобрана", ins2):
            check_insight(c, "новая новость", ins2, a, "ceo", nid)

    status, m = call(base, "GET", "/api/v1/metrics")
    c.check(status == 200 and m["content"]["insights"] >= 1, "метрики качества доступны")
    status, audit = call(base, "GET", "/api/v1/audit")
    c.check(status == 200 and any(x["tool"] == "search_bank_analytics" for x in audit["items"]), "журнал обращений к инструментам")

    for name, path, body, code, exp in [
        ("неизвестная компания", "/api/v1/insights", {"company_id": "nope", "role": "cfo", "news_id": news_id}, 404, "COMPANY_NOT_FOUND"),
        ("неизвестная новость", "/api/v1/insights", {"company_id": a, "role": "cfo", "news_id": "nope"}, 404, "NEWS_NOT_FOUND"),
        ("неверная роль", "/api/v1/insights", {"company_id": a, "role": "intern", "news_id": news_id}, 400, "INVALID_REQUEST"),
        ("тело больше 64 КиБ", "/api/v1/news", {"text": "x" * 70000}, 413, "REQUEST_TOO_LARGE"),
        ("SSRF по ссылке", "/api/v1/news", {"url": "http://127.0.0.1:8000/healthz"}, 422, "FETCH_FAILED"),
    ]:
        status, body_ = call(base, "POST", path, body)
        err = body_.get("error", {}) if isinstance(body_, dict) else {}
        c.check(status == code and err.get("code") == exp and err.get("request_id"), f"{name}: {code} {exp}", (status, body_))
    return finish(c)


def finish(c: Checker) -> int:
    print(f"\n{c.passed} passed, {len(c.failures)} failed")
    return 1 if c.failures else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--wait", type=float, default=180)
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(args.base_url.rstrip("/"), args.wait))


if __name__ == "__main__":
    main()
