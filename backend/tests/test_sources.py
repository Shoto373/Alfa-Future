"""Источники новостей (SPR3-02): адаптеры, реестр с метриками, лицензия «только лид»,
сюжеты в PostgreSQL и организации в новостях."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app import database, pipeline
from app.companies import profiles
from app.models import News, NewsEntity
from app.news import entities, parser, store
from app.news.sources import base, licensed, registry

FIXTURES = Path(__file__).parent / "fixtures"
DEMO = Path(registry.__file__).parent / "demo"
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>ЦБ повысил ключевую ставку до 16%</title><link>https://example.org/a</link>
<pubDate>Thu, 22 Oct 2026 10:00:00 +0300</pubDate>
<description>Совет директоров Банка России повысил ключевую ставку до 16% годовых из-за ускорения инфляции и роста кредитования.</description></item>
</channel></rss>"""


@pytest.fixture
def rss(monkeypatch):
    monkeypatch.setenv("RSS_SOURCES", "Тест|https://example.org/rss")
    monkeypatch.setattr(parser, "_get", lambda url, max_redirects=3: RSS)
    monkeypatch.setenv("RSS_FULL_TEXT", "0")


def test_registry_describes_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("RSS_SOURCES", "Интерфакс|https://www.interfax.ru/rss.asp")
    monkeypatch.setenv("LICENSED_FEED_DIR", str(DEMO))
    manual = tmp_path / "manual.json"
    manual.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("MANUAL_NEWS_FILE", str(manual))
    adapters = registry.adapters()
    kinds = {a.kind: a for a in adapters}
    assert set(kinds) == {"rss", "licensed", "manual"}
    assert kinds["rss"].trust == 0.95 and kinds["rss"].license == "full"
    assert kinds["licensed"].license == "lead", "лицензированная лента — только заголовок и лид"
    assert len({a.id for a in adapters}) == len(adapters), "id источников уникальны"


def test_rss_through_adapter_without_duplicates(client, rss):
    first = registry.collect()
    assert first["added"] == 1 and first["sources"][0]["error"] is None
    item = next(i for i in store.all_items() if i["kind"] == "rss")
    assert item["source_id"].startswith("rss:") and item["trust"] == 0.8 and item["license"] == "full"
    again = registry.collect()
    assert again["added"] == 0 and again["duplicates"] == 1, "повторный сбор не плодит дубли"
    stat = registry.stats()[item["source_id"]]
    assert stat["added_total"] == 1 and stat["errors_total"] == 0 and stat["latency_ms"] is not None
    assert stat["lag_seconds"] is not None, "задержка от публикации до ленты — метрика источника"


def test_licensed_stub_takes_the_same_path_and_keeps_only_lead(client, monkeypatch):
    monkeypatch.setenv("LICENSED_FEED_DIR", str(DEMO))
    report = registry.collect()
    assert report["added"] >= 4 and all(s["error"] is None for s in report["sources"])
    stub = [i for i in store.all_items() if i.get("license") == "lead"]
    assert {i["source"] for i in stub} == {"Интерфакс", "ПРАЙМ"}
    assert all(len(i["text"]) <= base.LEAD_LIMIT + 1 for i in stub)
    assert not any("процентные расходы компании за девять месяцев" in i["text"] for i in stub), "тело ленты не хранится"


def test_formats_of_licensed_feeds():
    interfax = licensed.parse_interfax((DEMO / "interfax.xml").read_text(encoding="utf-8"))
    prime = licensed.parse_prime((DEMO / "prime.json").read_text(encoding="utf-8"))
    assert interfax[0].external_id == "ifx-demo-001" and interfax[0].published_at.startswith("2026-10-24")
    assert prime[0].url.startswith("https://1prime.ru/") and prime[0].title


def test_failing_source_is_counted_and_does_not_stop_others(client, rss, monkeypatch):
    monkeypatch.setenv("LICENSED_FEED_DIR", str(FIXTURES / "missing-feed-dir"))
    report = registry.collect()
    failed = [s for s in report["sources"] if s["error"]]
    assert len(failed) == 2 and report["added"] == 1, "ошибка ленты не мешает RSS"
    assert all(registry.stats()[s["id"]]["errors_total"] == 1 for s in failed)


def test_manual_adapter(client, tmp_path, monkeypatch):
    path = tmp_path / "manual.json"
    path.write_text(json.dumps([{"title": "Минфин увеличил налоговую нагрузку на экспортеров удобрений",
                                 "text": "Правительство повысило экспортные пошлины на удобрения и налог на добычу, "
                                         "что увеличит налоговую нагрузку на химические компании.",
                                 "published_at": "2026-10-24T09:00:00+03:00"}], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MANUAL_NEWS_FILE", str(path))
    assert registry.collect()["added"] == 1
    assert any(i["source"] == "Редакция Альфа.Пульса" for i in store.all_items())


def test_source_interval_from_sources_file(client, tmp_path, monkeypatch, rss):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps([{"kind": "rss", "name": "Редкая лента", "url": "https://example.org/rss",
                                 "interval_minutes": 60, "trust": 0.5}]), encoding="utf-8")
    monkeypatch.setenv("SOURCES_FILE", str(path))
    assert len(registry.collect()["sources"]) == 1
    assert registry.collect()["sources"] == [], "до срока источник не опрашивается"
    assert len(registry.collect(force=True)["sources"]) == 1


# --- организации в новостях ---

def _named() -> list[dict]:
    return [c for c in profiles.list_companies(limit=10**6)[1]
            if len(entities.normalize(c["display_name"]).replace("-", " ").split()) >= 2]


def _render(text: str, named: list[dict]) -> str:
    forms = {"ООО": "общество с ограниченной ответственностью", "АО": "акционерное общество",
             "ПАО": "публичное акционерное общество"}

    def sub(m: re.Match) -> str:
        name = named[int(m.group(2))]["display_name"]
        form, quoted = name.split(" ", 1)
        core = quoted.strip("«»")
        return {"name": name, "core": core, "quoted": quoted, "full": f"{forms[form].capitalize()} {quoted}",
                "bare_form": f"{form} {core}"}[m.group(1)]

    return re.sub(r"\{(name|core|quoted|full|bare_form):(\d+)\}", sub, text)


def test_entities_found_in_90_percent_of_fixtures(client):
    named = _named()
    cases = json.loads((FIXTURES / "entities" / "news.json").read_text(encoding="utf-8"))["cases"]
    misses = []
    for case in cases:
        text = _render(case["text"], named)
        found = {e["company_id"] for e in entities.extract(text) if e["company_id"]}
        if found != {named[i]["company_id"] for i in case["expect"]}:
            misses.append(text)
    assert 1 - len(misses) / len(cases) >= 0.9, misses


def test_entities_codes_and_third_parties(client):
    text = ("ПАО «Северный Альянс» (ИНН 7707083893, ОГРН 1027700132195) подписало соглашение; "
            "ИНН 7707083890 с ошибкой в контрольной цифре не считается.")
    found = entities.extract(text)
    assert {e["method"] for e in found} == {"legal_form", "inn", "ogrn"}
    assert {"name": "ПАО «Северный Альянс»", "company_id": None, "method": "legal_form"} in found
    assert not any(e["name"].endswith("7707083890") for e in found)


def test_single_word_names_need_quotes_or_form(client):
    single = next((c for c in profiles.list_companies(limit=10**6)[1]
                   if re.fullmatch(r"\w+",entities.normalize(c["display_name"]))), None)
    if single is None:
        pytest.skip("в профилях нет однословных названий")
    core = single["display_name"].split("«")[1].rstrip("»")
    assert entities.extract(f"{core} в центре города открылась после ремонта.") == []
    assert entities.extract(f"Компания «{core}» отчиталась о прибыли.")[0]["company_id"] == single["company_id"]


def test_feed_marks_news_about_company_and_counterparties(client, company):
    cid = company["company_id"]
    name = profiles.get(cid)["display_name"]
    text = (f"{name} повысило цены на продукцию на 10% из-за роста ключевой ставки и стоимости кредитов. "
            "Компания объясняет решение ростом процентных расходов.")
    created = client.post("/api/v1/news", json={"title": f"{name} повышает цены из-за ставки", "text": text}).json()
    news_id = created["news"]["news_id"]
    feed = client.get("/api/v1/feed", params={"company_id": cid, "limit": 500}).json()["items"]
    item = next(i for i in feed if i["news"]["news_id"] == news_id)
    assert item["news"]["mentions_company"] is True
    assert item["news"]["mentions"][0] == {"name": name, "company_id": cid, "method": "dictionary", "relation": "self"}
    detail = client.get(f"/api/v1/news/{news_id}", params={"company_id": cid}).json()
    assert detail["mentions_company"] and detail["entities"][0]["company_id"] == cid

    supplier = next(r for r, rel in entities.relations(cid).items() if rel == "supplier" and profiles.get(r))
    news = {"news_id": "x-supplier", "title": profiles.get(supplier)["display_name"], "text": ""}
    assert entities.mentions(news, cid)[0]["relation"] == "supplier"


def test_index_writes_entities_and_persists_stories(client, monkeypatch):
    monkeypatch.setenv("LICENSED_FEED_DIR", str(DEMO))
    registry.collect()
    assert pipeline.index_news()["entities"] > 0
    assert pipeline.index_news()["entities"] == 0, "без изменений индекс не пересчитывается"
    with database.session() as db:
        rows = list(db.scalars(select(NewsEntity)))
        stories = dict(db.execute(select(News.news_id, News.story_id)).all())
    assert any(r.company_id for r in rows), "найдены компании профилей"
    assert all(stories.values()), "у каждой новости сюжет хранится в базе"
    store.reset_cache()
    assert {i["news_id"]: i.get("story_id") for i in store.all_items()} == stories, "после перезапуска — те же сюжеты"
