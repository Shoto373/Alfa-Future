"""Бюджет LLM с резервированием: параллельные вызовы не превышают дневной лимит вместе."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import database, llm_usage
from app.agent import llm
from app.models import LLMReservation

SYSTEM, USER, MAX_TOKENS = "Ответь JSON.", '{"news": "ставка"}', 200
MODEL = "deepseek/deepseek-v4.1-flash"


@pytest.fixture
def gateway(monkeypatch):
    """LLM подключена; шлюз отвечает за 0,3 с и списывает ровно оценку резерва."""
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL_COMPOSE", MODEL)
    monkeypatch.setattr(llm, "_down_until", 0.0)
    tokens, cost = llm_usage.estimate(MODEL, len(SYSTEM) + len(USER), MAX_TOKENS)

    def post(url, json, timeout, headers):
        time.sleep(0.3)  # все 20 вызовов успевают зарезервировать до первого списания
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
            "usage": {"total_tokens": tokens, "cost": cost}})

    monkeypatch.setattr(llm.httpx, "post", post)
    return tokens, cost


def _call(_):
    try:
        llm.chat_json(SYSTEM, USER, "compose", MAX_TOKENS)
        return "ok"
    except llm.LLMError as exc:
        return str(exc)


def test_parallel_calls_cannot_exceed_daily_limit(client, gateway, monkeypatch):
    _, cost = gateway
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", str(round(cost * 5.5, 4)))  # помещается ровно 5 вызовов
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(_call, range(20)))

    assert results.count("ok") == 5, results
    assert all("Бюджет LLM" in r for r in results if r != "ok")
    u = llm_usage.usage()
    assert u["calls"] == 5 and u["rejected_by_budget"] == 15
    assert u["cost"] <= float(round(cost * 5.5, 4)), "сумма не превышает лимит"
    assert u["reserved_cost"] == 0 and u["reserved_tokens"] == 0 and llm_usage.reserved_active() == 0


def test_failed_call_releases_reservation(client, gateway, monkeypatch):
    def down(url, json, timeout, headers):
        raise httpx.ReadTimeout("slow", request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", down)
    with pytest.raises(llm.LLMError):
        llm.chat_json(SYSTEM, USER, "compose", MAX_TOKENS)
    u = llm_usage.usage()
    assert u["reserved_cost"] == 0 and u["errors"] == 1 and u["calls"] == 1 and u["cost"] == 0


def test_stale_reservation_is_swept(client):
    res = llm_usage.reserve(MODEL, 300, 100)
    assert llm_usage.usage()["reserved_tokens"] == res.tokens
    with database.session() as db:
        db.get(LLMReservation, res.id).created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    assert llm_usage.sweep() == 1
    assert llm_usage.usage()["reserved_tokens"] == 0
    llm_usage.commit(res, 10, 0.01)  # опоздавшее списание не уводит резерв в минус
    u = llm_usage.usage()
    assert u["reserved_tokens"] == 0 and u["tokens"] == 10


def test_cost_is_estimated_when_gateway_omits_it():
    assert llm_usage.cost_of(MODEL, 1000, None) == pytest.approx(0.06)
    assert llm_usage.cost_of(MODEL, 1000, 0.2) == 0.2
    assert llm_usage.cost_of("moonshotai/kimi-k2.6", 1000, None) > llm_usage.cost_of(MODEL, 1000, None)


def test_budget_refusal_falls_back_to_rules_with_reason(client, company, gateway, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", "0")
    news = store.make_item("ЦБ повысил ключевую ставку до 16%", "Банк России повысил ключевую ставку до 16%.", "Проверка")
    ins = asyncio.run(orchestrator.run(company, "cfo", news, "req_budget"))
    assert ins["mode"] == "rules" and ins["fallback_reason"] == "budget", "плашка в карточке: исчерпан лимит, а не сбой"
    step = next(s for s in ins["trace"] if s["name"] == "llm_compose")
    assert step["status"] == "warning" and "Бюджет LLM" in step["detail"]
    assert llm_usage.usage()["rejected_by_budget"] >= 1


def test_precompute_demo_is_idempotent(client, company):
    import asyncio

    from app import precompute_demo

    companies = [company]
    items = precompute_demo.plan(companies, ["cfo", "ceo"], 2)
    assert items and not any(it["ready"] for it in items)
    report = asyncio.run(precompute_demo.build(items))
    assert report["built"] == len(items) and report["llm_cost_rub"] == 0, "без ключа — правила, бесплатно"
    again = precompute_demo.plan(companies, ["cfo", "ceo"], 2)
    assert all(it["ready"] for it in again), "повторный запуск ничего не перестраивает"
    assert asyncio.run(precompute_demo.build(again))["built"] == 0


def test_demo_companies_default_to_metallurgy_and_auto(raw_client):
    from app import precompute_demo

    sectors = [c["sector"] for c in precompute_demo.demo_companies()]
    assert set(sectors) <= {"metallurgy", "auto"} and sectors


def test_metrics_show_reserve_rejections_and_fallback_rate(client, company, gateway, monkeypatch):
    import asyncio

    from app import storage
    from app.agent import orchestrator
    from app.news import store

    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", "0")
    news = store.make_item("ЦБ сохранил ключевую ставку", "Банк России сохранил ключевую ставку на уровне 14%.", "Проверка")
    store.add(news)
    storage.save_insight(asyncio.run(orchestrator.run(company, "cfo", news, "req_metrics")))
    ai = storage.metrics()["ai"]
    assert ai["rejected_by_budget"] >= 1 and ai["reserved_cost"] == 0
    assert ai["fallback_rate"] == 1.0, "модель вызывалась, но бюджет не дал — разбор на правилах"


def test_precompute_respects_max_cost(client, company, gateway, monkeypatch):
    import asyncio

    from app import precompute_demo

    items = precompute_demo.plan([company], ["cfo"], 3)
    report = asyncio.run(precompute_demo.build(items, max_cost=0))
    assert report["max_cost_reached"] and report["llm_cost_rub"] == 0, "предел 0 ₽ — модель не вызывается"
    assert all(i["mode"] == "rules" for i in report["items"])


def test_demo_opens_from_cache_fast(client, company):
    import asyncio
    import time

    from app import precompute_demo, storage

    items = precompute_demo.plan([company], ["cfo"], 3)
    asyncio.run(precompute_demo.build(items))
    check = precompute_demo.check_cache(items)
    assert check["ok"] and check["opened"] == len(items) and check["not_cached"] == 0
    # Через API: открытие готового разбора — из кэша и не дольше 2 с.
    t0 = time.perf_counter()
    r = client.post("/api/v1/insights", json={"company_id": company["company_id"], "news_id": items[0]["news_id"]})
    assert r.status_code == 200 and time.perf_counter() - t0 <= precompute_demo.CACHE_OPEN_LIMIT_S
    cached = storage.cached_insight(company["company_id"], "cfo", items[0]["news_id"])
    assert r.json()["insight_id"] == cached["insight_id"]


def test_llm_outage_is_reported_as_unavailable(client, company, gateway, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    def down(url, json, timeout, headers):
        raise httpx.ConnectError("refused", request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", down)
    news = store.make_item("ЦБ сохранил ключевую ставку", "Банк России сохранил ключевую ставку на уровне 14%.", "Проверка")
    ins = asyncio.run(orchestrator.run(company, "cfo", news, "req_down"))
    assert ins["mode"] == "rules" and ins["fallback_reason"] == "unavailable"


def test_usage_is_split_by_model(client, gateway):
    tokens, cost = gateway
    llm.chat_json(SYSTEM, USER, "compose", MAX_TOKENS)
    rows = llm_usage.by_model()
    assert [r["model"] for r in rows] == [MODEL]
    row = rows[0]
    assert row["calls"] == 1 and row["tokens"] == tokens and row["cost"] == pytest.approx(cost, abs=1e-3)
    assert row["price_per_1k"] == pytest.approx(cost / tokens * 1000, rel=0.05) and row["estimate_per_1k"] == 0.06


def test_daily_report_shows_budget(client, monkeypatch):
    from datetime import date

    from app import quality

    monkeypatch.setattr(llm_usage, "budget_day", lambda: date(2026, 10, 23))
    llm_usage.commit(llm_usage.reserve(MODEL, 300, 100), 1000, 0.25)  # расход вчерашнего дня бюджета
    monkeypatch.setattr(llm_usage, "budget_day", lambda: date(2026, 10, 24))  # отчет уходит на следующее утро
    d = quality.daily()
    assert d["budget"]["day"] == "2026-10-23" and d["budget"]["cost"] == 0.25
    assert d["budget"]["by_model"][0]["model"] == MODEL
    line = quality.report_text(d).splitlines()[-1]
    assert "0.25 из" in line and "отклонено бюджетом 0" in line and MODEL in line
