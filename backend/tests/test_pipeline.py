"""Автоматический конвейер: сбор из RSS, разборы на правилах и AI-версия в пределах лимитов."""

import asyncio

import httpx

from app import pipeline, storage
from app.agent import llm
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
    assert len(ready) == min(3, len(feed)), "лучшие новости ленты уже разобраны"

    again = asyncio.run(pipeline.cycle())
    assert again["rss"]["added"] == 0 and again["rss"]["duplicates"] >= 1
    assert again["rules_built"] == 0, "готовые разборы не строятся повторно"
    assert client.get("/api/v1/meta").json()["pipeline"]["last"]["rules_built"] == 0


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
    calls = _spy(monkeypatch)
    report = asyncio.run(pipeline.cycle())
    assert calls.count(True) == 1, "не больше PIPELINE_LLM_PER_CYCLE AI-разборов за цикл"
    assert report["rules_built"] >= 1


def test_cycle_leaves_llm_budget_to_users(client, company, monkeypatch):
    monkeypatch.setenv("PIPELINE_RULES_TOP", "2")
    monkeypatch.setenv("PIPELINE_LLM_SHARE", "0")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))
    report = asyncio.run(pipeline.cycle())
    assert report["llm_built"] == 0 and report["llm_skipped"]
    assert report["rules_built"] >= 1


def test_attempted_llm_card_is_not_upgraded_again():
    card = {"mode": "rules", "trace": [{"name": "llm_compose", "status": "ok"}]}
    assert storage.llm_attempted(card)
    assert not storage.llm_attempted({"mode": "rules", "trace": [{"name": "llm_compose", "status": "warning"}]})
