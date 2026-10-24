"""Автоматический конвейер: сбор из RSS, разборы на правилах и AI-версия в пределах лимитов."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.companies import ai_settings as company_ai
from app import llm, pipeline, storage
from app.news import parser

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>ЦБ повысил ключевую ставку до 16%</title><link>https://example.org/a</link>
<pubDate>Thu, 22 Oct 2026 10:00:00 +0300</pubDate>
<description>Совет директоров Банка России повысил ключевую ставку до 16% годовых из-за ускорения инфляции и роста кредитования.</description></item>
<item><title>Футбольный клуб выиграл кубок</title><link>https://example.org/b</link>
<pubDate>Thu, 22 Oct 2026 11:00:00 +0300</pubDate>
<description>Спортивный матч завершился победой хозяев поля, болельщики праздновали до утра на центральной площади.</description></item>
</channel></rss>"""


def _rss(monkeypatch):
    monkeypatch.setenv("RSS_SOURCES", "Тест|https://example.org/rss")
    monkeypatch.setattr(parser, "_get", lambda url, max_redirects=3: RSS)


def _spy(monkeypatch) -> list[bool]:
    calls: list[bool] = []
    real = pipeline._analyze

    async def spy(company, role, news, use_llm):
        calls.append(use_llm)
        return await real(company, role, news, use_llm)

    monkeypatch.setattr(pipeline, "_analyze", spy)
    return calls


def test_cycle_collects_news_and_prepares_cards(client, company, monkeypatch):
    _rss(monkeypatch)
    monkeypatch.setenv("PIPELINE_RULES_TOP", "3")
    calls = _spy(monkeypatch)

    report = asyncio.run(pipeline.cycle())
    assert report["rss"]["added"] == 1 and report["rss"]["skipped"] == 1  # спорт отсеян
    assert report["pairs"] == 1 and report["rules_built"] >= 1
    assert calls and not any(calls), "без LLM — только разборы на правилах"

    feed = client.get("/api/v1/feed", params={"company_id": company["company_id"]}).json()["items"]
    ready = [i for i in feed[:3] if i["cached_insight_id"]]
    assert all(i["cached_effect"] in {"neg", "pos", "mixed", "unclear", "none"} for i in ready), "метка знака в ленте"
    assert len(ready) == min(3, len(feed)), "лучшие новости ленты уже разобраны"

    again = asyncio.run(pipeline.cycle())
    assert again["rss"]["added"] == 0 and again["rss"]["duplicates"] >= 1
    assert again["rules_built"] == 0, "готовые разборы не строятся повторно"
    status = client.get("/api/v1/meta").json()["pipeline"]
    assert status["state"] == "disabled" and status["rules_built"] == 0  # в тестах RSS_REFRESH_MINUTES=0


def test_cycle_upgrades_top_cards_with_llm_within_limits(client, company, monkeypatch):
    monkeypatch.setenv("PIPELINE_RULES_TOP", "3")
    monkeypatch.setenv("PIPELINE_LLM_PER_CYCLE", "1")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", 0.0)

    def fake_post(url, json, timeout, headers):
        content = ('{"headline": "Для компании ставка 14% сохраняет дорогой долг", "risks": [{"text": "Долг остается дорогим", '
                   '"origin": "ai", "source_ids": ["news:seed-rate-hold"], "features": ["products.loans"]}]}')
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 100}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    company_ai.save(company["company_id"], True, 40, "test")  # заранее — все новости ленты от 40
    calls = _spy(monkeypatch)
    report = asyncio.run(pipeline.cycle())
    assert calls.count(True) == 1, "не больше PIPELINE_LLM_PER_CYCLE AI-разборов за цикл"
    assert report["rules_built"] >= 1


def test_cycle_respects_company_ai_setting(client, company, monkeypatch):
    """Компания выключила «AI-разборы заранее» — конвейер строит только быстрые разборы."""
    monkeypatch.setenv("PIPELINE_RULES_TOP", "3")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))
    company_ai.save(company["company_id"], False, 40, "test")
    calls = _spy(monkeypatch)
    report = asyncio.run(pipeline.cycle())
    assert calls.count(True) == 0 and report["llm_built"] == 0
    assert report["rules_built"] >= 1


def test_cycle_leaves_llm_budget_to_users(client, company, monkeypatch):
    monkeypatch.setenv("PIPELINE_RULES_TOP", "2")
    monkeypatch.setenv("PIPELINE_LLM_SHARE", "0")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))
    company_ai.save(company["company_id"], True, 40, "test")
    report = asyncio.run(pipeline.cycle())
    assert report["llm_built"] == 0 and report["llm_skipped"]
    assert report["rules_built"] >= 1


def test_attempted_llm_card_is_not_upgraded_again():
    card = {"mode": "rules", "trace": [{"name": "llm_compose", "status": "ok"}]}
    assert storage.llm_attempted(card)
    assert not storage.llm_attempted({"mode": "rules", "trace": [{"name": "llm_compose", "status": "warning"}]})


def test_cycle_with_empty_audience_builds_nothing(raw_client, monkeypatch):
    calls = _spy(monkeypatch)
    report = asyncio.run(pipeline.cycle())
    assert report["pairs"] == 0 and report["rules_built"] == 0 and report["llm_built"] == 0
    assert calls == [], "без привязанных компаний разборов нет"
    assert pipeline.status()["started_at"] == report["started_at"]


def test_rss_failure_does_not_stop_cycle(client, company, monkeypatch):
    monkeypatch.setenv("RSS_SOURCES", "Тест|https://example.org/rss")
    monkeypatch.setenv("PIPELINE_RULES_TOP", "2")

    def down(url, max_redirects=3):
        raise parser.FetchError("source is down")

    monkeypatch.setattr(parser, "_get", down)
    report = asyncio.run(pipeline.cycle())
    assert report["rss"]["failed"] == ["Тест"] and report["rss"]["added"] == 0
    assert report["rules_built"] >= 1, "лента из уже известных новостей разбирается"

    monkeypatch.setattr(parser, "refresh", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    report = asyncio.run(pipeline.cycle())
    assert report["rss"]["error"] == "RuntimeError" and report["error"] is None


def test_failed_analysis_does_not_stop_cycle(client, company, monkeypatch):
    from app.agent import orchestrator

    monkeypatch.setenv("PIPELINE_RULES_TOP", "3")
    real, seen = orchestrator.run, []

    async def flaky(company, role, news, request_id, use_llm=True, charge_company=True):
        seen.append(news["news_id"])
        if len(seen) == 1:
            raise RuntimeError("broken card")
        return await real(company, role, news, request_id, use_llm=use_llm)

    monkeypatch.setattr(orchestrator, "run", flaky)
    report = asyncio.run(pipeline.cycle())
    assert len(seen) >= 2 and report["rules_built"] == len(seen) - 1


def test_only_one_worker_claims_the_cycle(raw_client, monkeypatch):
    monkeypatch.setenv("RSS_REFRESH_MINUTES", "15")  # статус включенного конвейера; задача в тесте не стартует
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(lambda _: pipeline.claim(15), range(8)))
    assert sum(c is not None for c in claims) == 1, "цикл занимает ровно один воркер"
    assert pipeline.status()["state"] == "running"

    started_at = next(c for c in claims if c)
    asyncio.run(pipeline.cycle(started_at))
    assert pipeline.claim(15) is None, "недавно пройденный цикл не повторяется другим воркером"
    assert pipeline.status()["state"] == "idle"


def test_stale_running_mark_is_released(raw_client):
    from app import database

    with database.session() as db:
        database.set_state(pipeline.STATE_KEY, {"state": "running", "started_at": "2020-01-01T00:00:00+00:00"}, db)
    assert pipeline.claim(15) is not None, "процесс упал посреди цикла — отметка не блокирует навсегда"


def test_api_does_not_start_background_pipeline(raw_client):
    """Фоновые задачи — у воркера (app/worker): API их не запускает, даже со включенным конвейером."""
    from app.main import app

    assert not hasattr(app.state, "pipeline")
    assert raw_client.get("/api/v1/meta").json()["pipeline"]["state"] == "disabled"


def test_run_cycle_marks_failure_and_reraises(raw_client, monkeypatch):
    """Задача воркера news_cycle: сбой — в статусе цикла и наружу, чтобы очередь повторила задачу."""
    async def broken(started_at=None):
        raise RuntimeError("rss down")

    monkeypatch.setattr(pipeline, "cycle", broken)
    try:
        pipeline.run_cycle(15)
        raise AssertionError("сбой должен пробрасываться")
    except RuntimeError:
        pass
    assert pipeline.status()["error"] == "RuntimeError"


def test_optional_steps_do_not_break_cycle_and_report_sees_results(client, company, monkeypatch):
    from app import database, quality

    monkeypatch.setenv("PIPELINE_RULES_TOP", "2")
    monkeypatch.setattr(pipeline, "_name_stories", lambda: (_ for _ in ()).throw(RuntimeError("model down")))
    seen = {}

    def fake_report():
        seen.update(database.state(pipeline.STATE_KEY) or {})
        return True

    monkeypatch.setattr(quality, "maybe_send_daily", fake_report)
    report = asyncio.run(pipeline.cycle())
    assert report["stories_named"] == 0 and report["rules_built"] >= 1, "сбой названий сюжетов не мешает разборам"
    assert seen["rules_built"] == report["rules_built"], "отчет о качестве читает итоги этого цикла"
    assert report["quality_report"] is True and pipeline.status()["quality_report"] is True
