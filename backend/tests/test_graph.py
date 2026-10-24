"""Граф контрагентов и мониторинг (SPR4-01): второй уровень с цепочкой, алерт, признак ленты, вывод в разборе."""

from pathlib import Path

import pytest

from app import monitoring, pipeline
from app.companies import graph, profiles
from app.news import store
from tests.conftest import register

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def test_graph_shares_and_profile():
    g = graph.build(DATA)
    assert g.stats["payment_edges"] > 1000 and g.stats["build_seconds"] < 120
    payer = next(iter(g.suppliers))
    assert sum(share for _, share, _, _ in g.suppliers[payer]) == pytest.approx(1.0), "доли поставщиков компании — 100%"
    assert set(g.stats["out_degree"]["histogram"]) == {"1", "2–5", "6–20", "21–100", ">100"}


def _pilot() -> tuple[str, dict]:
    """Компания профилей, у которой есть контрагент второго уровня из профилей (его можно назвать в новости)."""
    for c in profiles.list_companies(limit=10**6)[1]:
        for n in graph.neighbors(c["company_id"]):
            if n["level"] == 2 and profiles.get(n["company_id"]) and graph.chain_to(c["company_id"], n["company_id"])["level"] == 2:
                return c["company_id"], n
    pytest.skip("в синтетических данных нет цепочки второго уровня до компании из профилей")


def test_second_level_chain_explained(client):
    cid, n = _pilot()
    assert n["weight"] >= graph.SECOND_LEVEL_MIN and n["text"].startswith("вы → ")
    assert n["text"].count("→") == 2 and "%" in n["text"], "цепочка «вы → А (доля) → Б (доля)»"
    links = [x for x in graph.neighbors(cid) if x["relation"] == "person"]
    assert all("возможная связь" in x["text"] for x in links), "связь через физлиц — только «возможная»"


def test_sync_writes_edges_once(client):
    assert graph.sync() > 1000
    assert graph.sync() == 0, "без смены данных граф не переписывается"


def test_counterparty_event_alert_feed_and_insight(raw_client, new_client):
    cid, n = _pilot()
    owner = new_client()
    register(owner, "pilot@example.com")
    assert owner.post(f"/api/v1/companies/{cid}/claim", json={"role": "cfo"}).status_code == 201
    name = profiles.get(n["company_id"])["display_name"]
    item = store.make_item(f"{name} задерживает поставки из-за роста ключевой ставки",
                           f"{name} сообщил о задержке поставок: после повышения ключевой ставки ставки по кредитам выросли, "
                           "компания сокращает закупки и переносит отгрузки.", "Тест")
    store.add(item)
    pipeline.index_news()
    assert monitoring.scan() >= 1
    events = owner.get(f"/api/v1/companies/{cid}/counterparties").json()["events"]
    alert = next(e for e in events if e["news_id"] == item["news_id"])
    assert alert["level"] == 2 and alert["chain"] == n["text"] and alert["strength"] > 0
    assert monitoring.scan() == 0, "алерт по паре «компания × новость × контрагент» — один раз"

    feed = owner.get("/api/v1/feed", params={"company_id": cid, "limit": 500}).json()["items"]
    hit = next(i for i in feed if i["news"]["news_id"] == item["news_id"])
    assert any(r["kind"] == "counterparty" and n["text"] in r["text"] for r in hit["relevance"]["reasons"])

    ins = owner.post("/api/v1/insights", json={"company_id": cid, "news_id": item["news_id"], "fast": True}).json()
    claim = ins["why_important"][0]
    assert n["text"] in claim["text"] and "client:graph" in claim["source_ids"] and claim["origin"] == "client_data"
    assert any(s["source_id"] == "client:graph" for s in ins["sources"])
    assert any(s["name"] == "lookup_counterparty_chain" for s in ins["trace"])


def test_counterparties_screen_data(client, company):
    data = client.get(f"/api/v1/companies/{company['company_id']}/counterparties").json()
    assert len(data["top"]) <= graph.TOP and all(x["level"] == 1 for x in data["top"])
    assert all(x["level"] == 2 and x["text"].count("→") == 2 for x in data["second_level"])
