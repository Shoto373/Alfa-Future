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


def test_without_key_reason_is_disabled_not_outage(client, company, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    news = store.make_item("ЦБ сохранил ключевую ставку", "Банк России сохранил ключевую ставку на уровне 14%.", "Проверка")
    assert asyncio.run(orchestrator.run(company, "cfo", news, "req_nokey"))["fallback_reason"] == "disabled"
    assert asyncio.run(orchestrator.run(company, "cfo", news, "req_fast", use_llm=False))["fallback_reason"] is None
    # Ключ есть, но шлюз недавно не ответил (предохранитель) — это «не отвечает», а не «не подключена».
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", float("inf"))
    assert asyncio.run(orchestrator.run(company, "cfo", news, "req_breaker"))["fallback_reason"] == "unavailable"


def test_cached_rules_card_reports_disabled_when_opened_without_key(client, company):
    import asyncio

    from app import pipeline, ranking
    from app.news import store

    news = ranking.company_feed(company["company_id"], "cfo", 500)[0]["news"]
    card = asyncio.run(pipeline._analyze(company, "cfo", store.get(news["news_id"]), use_llm=False))  # как конвейер
    assert card["fallback_reason"] is None, "конвейер строит правилами намеренно — причины в разборе нет"
    body = {"company_id": company["company_id"], "news_id": news["news_id"]}
    assert client.post("/api/v1/insights", json={**body, "fast": True}).json()["fallback_reason"] is None
    opened = client.post("/api/v1/insights", json=body).json()
    assert opened["insight_id"] == card["insight_id"] and opened["fallback_reason"] == "disabled"


# --- Защита общего бюджета: доля компании, частота, один разбор, оповещения, экономный режим, выключатель ---

def test_one_company_cannot_spend_the_whole_day(client, gateway, monkeypatch):
    _, cost = gateway
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", str(round(cost * 10.5, 4)))
    monkeypatch.setenv("LLM_COMPANY_SHARE", "0.2")  # 20% лимита — ровно 2 вызова на компанию
    with llm_usage.for_company("A"):
        results = [_call(i) for i in range(4)]
    assert results.count("ok") == 2 and all("доля компании" in r for r in results if r != "ok")
    with llm_usage.for_company("B"):
        assert _call(0) == "ok", "доля другой компании не тронута"
    rows = {r["company_id"]: r for r in llm_usage.by_company()}
    assert rows["A"]["calls"] == 2 and rows["A"]["rejected_by_share"] == 2 and rows["B"]["calls"] == 1
    assert llm_usage.usage()["reserved_cost"] == 0


def test_refresh_and_questions_are_rate_limited_per_user(client, company, gateway, monkeypatch):
    monkeypatch.setenv("LLM_USER_REFRESH_PER_HOUR", "2")
    monkeypatch.setenv("LLM_USER_QUESTIONS_PER_HOUR", "1")
    req = {"company_id": company["company_id"], "news_id": "seed-rate-hold", "force_refresh": True}
    assert client.post("/api/v1/insights", json=req).status_code == 200
    ins = client.post("/api/v1/insights", json=req).json()
    r = client.post("/api/v1/insights", json=req)
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert client.post(f"/api/v1/insights/{ins['insight_id']}/questions", json={"question": "Что дальше?"}).status_code == 200
    r = client.post(f"/api/v1/insights/{ins['insight_id']}/questions", json={"question": "А риски?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_rate_limit_is_off_without_model(client, company, monkeypatch):
    monkeypatch.setenv("LLM_USER_REFRESH_PER_HOUR", "1")
    req = {"company_id": company["company_id"], "news_id": "seed-rate-hold", "force_refresh": True}
    assert all(client.post("/api/v1/insights", json=req).status_code == 200 for _ in range(3)), "без модели запрос бесплатен"


def test_same_analysis_is_built_once(client, company, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    real, calls = orchestrator.run, []

    async def slow(*a, **k):
        calls.append(1)
        await asyncio.sleep(0.2)  # второй запрос приходит, пока первый строится
        return await real(*a, **k)

    monkeypatch.setattr(orchestrator, "run", slow)
    news = store.get("seed-rate-hold")

    async def both():
        return await asyncio.gather(orchestrator.run_once(company, "cfo", news, "req_a"),
                                    orchestrator.run_once(company, "cfo", news, "req_b"))

    (first, lead_a), (second, lead_b) = asyncio.run(both())
    assert len(calls) == 1 and first["insight_id"] == second["insight_id"] and {lead_a, lead_b} == {True, False}
    asyncio.run(orchestrator.run_once(company, "cfo", news, "req_c"))
    assert len(calls) == 2, "после завершения следующий запрос строит заново (кэш — забота API)"


def test_budget_alerts_fire_once_per_threshold(client, monkeypatch):
    from app import notify

    sent = []
    monkeypatch.setattr(notify, "send_async", sent.append)
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", "1")
    llm_usage.commit(llm_usage.reserve(MODEL, 30, 10), 100, 0.6)   # 60% — порог 50%
    llm_usage.commit(llm_usage.reserve(MODEL, 30, 10), 100, 0.25)  # 85% — порог 80%
    llm_usage.commit(llm_usage.reserve(MODEL, 30, 10), 100, 0.05)  # 90% — новых порогов нет
    assert len(sent) == 2 and "50%" in sent[0] and "80%" in sent[1]
    with pytest.raises(llm_usage.BudgetExceeded):
        llm_usage.reserve(MODEL, 30, 2000)                         # не помещается — 100%, вызовы отклоняются
    with pytest.raises(llm_usage.BudgetExceeded):
        llm_usage.reserve(MODEL, 30, 2000)
    assert len(sent) == 3 and "100%" in sent[2], "о исчерпании — одно сообщение, не на каждый отказ"


def test_economy_model_near_the_limit(client, gateway, monkeypatch):
    models = []
    real = llm.httpx.post

    def capture(url, json, timeout, headers):
        models.append(json["model"])
        return real(url, json=json, timeout=timeout, headers=headers)

    monkeypatch.setattr(llm.httpx, "post", capture)
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT", "100")
    llm.chat_json(SYSTEM, USER, "compose", MAX_TOKENS)
    llm_usage.commit(llm_usage.reserve(MODEL, 30, 10), 1000, 85)  # потрачено 85% дня
    llm.chat_json(SYSTEM, USER, "compose", MAX_TOKENS)
    llm.chat_json(SYSTEM, USER, "plan", MAX_TOKENS)
    assert models == [MODEL, "z-ai/glm-5.3-flash", "z-ai/glm-5.3-flash"], "у края лимита черновик пишет GLM"


def test_operator_can_pause_ai_without_removing_key(client, company, gateway, new_client, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    assert client.post("/api/v1/ops/llm", json={"paused": True}).status_code == 403, "администратор клиента — не банк"
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com")
    assert client.post("/api/v1/ops/llm", json={"paused": True}).json()["paused"] is True
    assert not llm.available() and llm.configured()
    ins = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_paused"))
    assert ins["mode"] == "rules" and ins["fallback_reason"] == "paused"
    assert llm_usage.usage()["calls"] == 0, "модель не вызывалась"
    state = client.post("/api/v1/ops/llm", json={"paused": False}).json()
    assert state["paused"] is False and state["connected"] is True and state["by"] == "owner@example.com"


def test_me_marks_bank_operator(client, monkeypatch):
    assert client.get("/api/v1/auth/me").json()["is_operator"] is False, "администратор клиента — не сотрудник банка"
    monkeypatch.setenv("OPERATOR_EMAILS", "OWNER@example.com")
    assert client.get("/api/v1/auth/me").json()["is_operator"] is True


def test_company_share_refusal_has_its_own_reason(client, company, gateway, monkeypatch):
    import asyncio

    from app.agent import orchestrator
    from app.news import store

    monkeypatch.setenv("LLM_COMPANY_SHARE", "0")  # доля компании исчерпана, общий лимит свободен
    ins = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_share"))
    assert ins["mode"] == "rules" and ins["fallback_reason"] == "company_budget", "плашка: лимит вашей компании"


def test_waiting_request_gets_insight_only_after_it_is_saved(client, company, monkeypatch):
    import asyncio

    from app import storage
    from app.agent import orchestrator
    from app.news import store

    real = orchestrator.run

    async def slow(*a, **k):
        await asyncio.sleep(0.2)
        return await real(*a, **k)

    monkeypatch.setattr(orchestrator, "run", slow)
    news = store.get("seed-rate-hold")

    async def save(ins):
        await asyncio.sleep(0.2)  # сохранение не мгновенное
        await asyncio.to_thread(storage.save_insight, ins)

    async def both():
        return await asyncio.gather(orchestrator.run_once(company, "cfo", news, "req_a", on_built=save),
                                    orchestrator.run_once(company, "cfo", news, "req_b"))

    (first, _), (second, lead_b) = asyncio.run(both())
    assert lead_b is False and storage.get_insight(second["insight_id"]) is not None, "ждущий получил уже сохраненный разбор"
