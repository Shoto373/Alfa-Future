"""Сквозной smoke-тест backend спринта 1 (только стандартная библиотека).

    python tests/e2e/smoke.py --base-url http://localhost:8000

Любая непройденная проверка дает ненулевой код выхода.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

COMPANIES = ("demo_company_001", "demo_company_002")
ROLES = ("ceo", "cfo")
EVENT_ID = "demo_event_001"
INSIGHT_FIELDS = {
    "schema_version": str, "request_id": str, "company_id": str, "event_id": str, "role": str,
    "status": str, "is_mock": bool, "title": str, "facts": list, "company_relevance": str,
    "risks": list, "opportunities": list, "actions": list, "bank_position": type(None),
    "model_conclusion": str, "sources": list, "uncertainty": list,
}


class Checker:
    def __init__(self):
        self.failures: list[str] = []
        self.passed = 0

    def check(self, condition: bool, name: str, detail: object = "") -> bool:
        if condition:
            self.passed += 1
            print(f"  ok   {name}")
        else:
            self.failures.append(name)
            print(f"  FAIL {name} {detail}")
        return condition


def call(base: str, method: str, path: str, body: object = None, timeout: float = 15):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, raw.decode(errors="replace")


def wait_healthy(base: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            status, body = call(base, "GET", "/healthz", timeout=3)
            if status == 200:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def check_error(c: Checker, name: str, result, status: int, code: str):
    got_status, body = result
    error = body.get("error", {}) if isinstance(body, dict) else {}
    c.check(got_status == status and error.get("code") == code, f"{name}: {status} {code}", (got_status, body))
    c.check(isinstance(error.get("request_id"), str) and error.get("request_id"), f"{name}: request_id в ошибке")
    c.check(error.get("retryable") is (status in (503, 504)), f"{name}: retryable")


def run(base: str, wait: float) -> int:
    c = Checker()
    print(f"Smoke {base}")

    if not c.check(wait_healthy(base, wait), "backend отвечает на /healthz"):
        return finish(c)
    status, body = call(base, "GET", "/healthz")
    c.check(status == 200 and body == {"status": "ok", "service": "backend"}, "healthz тело", body)

    status, body = call(base, "GET", "/api/v1/companies")
    items = body.get("items") if isinstance(body, dict) else None
    c.check(status == 200 and isinstance(items, list), "список компаний", (status, body))
    ids = [i.get("company_id") for i in items or []]
    for company_id in COMPANIES:
        c.check(company_id in ids, f"компания {company_id} в списке", ids)
    c.check(all(i.get("is_synthetic") is True for i in items or []), "все компании синтетические")

    relevance: dict[str, set[str]] = {}
    request_ids = set()
    for company_id in COMPANIES:
        for role in ROLES:
            label = f"{company_id}/{role}"
            payload = {"company_id": company_id, "role": role, "event_id": EVENT_ID}
            status, card = call(base, "POST", "/api/v1/insights", payload)
            if not c.check(status == 200 and isinstance(card, dict), f"{label}: 200", (status, card)):
                continue
            missing = [k for k, t in INSIGHT_FIELDS.items() if not isinstance(card.get(k), t)]
            extra = set(card) - set(INSIGHT_FIELDS)
            c.check(not missing and not extra, f"{label}: поля и типы карточки", (missing, extra))
            c.check((card.get("company_id"), card.get("event_id"), card.get("role")) == (company_id, EVENT_ID, role),
                    f"{label}: company_id/event_id/role")
            c.check(card.get("schema_version") == "0.1.0", f"{label}: schema_version")
            c.check(card.get("status") == "completed", f"{label}: status")
            c.check(card.get("is_mock") is True, f"{label}: is_mock=true")
            c.check("bank_position" in card and card["bank_position"] is None, f"{label}: bank_position=null")
            c.check(bool(card.get("request_id")) and card["request_id"] not in request_ids,
                    f"{label}: уникальный request_id")
            request_ids.add(card.get("request_id"))
            c.check("LLM" in card.get("model_conclusion", ""), f"{label}: model_conclusion сообщает про LLM")
            sources = card.get("sources") or []
            c.check(any(s.get("kind") == "synthetic_fixture" and s.get("source_id") == EVENT_ID for s in sources),
                    f"{label}: источник synthetic_fixture")
            relevance.setdefault(company_id, set()).add(card.get("company_relevance"))

    a, b = (relevance.get(cid, set()) for cid in COMPANIES)
    c.check(bool(a) and bool(b) and a.isdisjoint(b), "две компании дают различимый company_relevance")

    base_req = {"company_id": COMPANIES[0], "role": "cfo", "event_id": EVENT_ID}
    check_error(c, "неизвестная компания", call(base, "POST", "/api/v1/insights", {**base_req, "company_id": "unknown"}),
                404, "COMPANY_NOT_FOUND")
    check_error(c, "неизвестное событие", call(base, "POST", "/api/v1/insights", {**base_req, "event_id": "unknown"}),
                404, "EVENT_NOT_FOUND")
    check_error(c, "неверная роль", call(base, "POST", "/api/v1/insights", {**base_req, "role": "cto"}),
                400, "INVALID_REQUEST")
    check_error(c, "лишнее поле", call(base, "POST", "/api/v1/insights", {**base_req, "extra": 1}),
                400, "INVALID_REQUEST")
    check_error(c, "тело больше 64 КиБ", call(base, "POST", "/api/v1/insights", {**base_req, "pad": "x" * 70000}),
                413, "REQUEST_TOO_LARGE")

    return finish(c)


def finish(c: Checker) -> int:
    print(f"\n{c.passed} passed, {len(c.failures)} failed")
    return 1 if c.failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--wait", type=float, default=60, help="сколько секунд ждать /healthz")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run(args.base_url.rstrip("/"), args.wait))


if __name__ == "__main__":
    main()
