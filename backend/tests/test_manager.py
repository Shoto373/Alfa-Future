"""Связь с банком (SPR4-06): предложение только при потребности, заявка только с согласия,
менеджер видит заявки и события только своих клиентов."""

import pytest

from app.companies import profiles
from app.domain_config import runtime
from app.offers import leads, needs
from tests.conftest import register

OPERATOR = "operator@alfa.test"


def _news(topics: list[str], countries: list[str] | None = None) -> dict:
    return {"classification": {"topics": [{"topic": t} for t in topics], "countries": countries or []}}


def _companies() -> list[dict]:
    return [profiles.get(c["company_id"]) for c in profiles.list_companies(limit=10**6)[1]]


def test_rules_live_in_domain_config(client):
    assert {"factoring", "fx_hedge", "ved_account"} <= set(runtime.OFFERS)
    assert runtime.OFFERS["factoring"]["exposure"] == "customers_concentration"


def test_no_need_no_offer(client):
    companies = _companies()
    concentrated = next(c for c in companies if (c["customers"]["top1_share"] or 0) >= 0.5)
    spread = next((c for c in companies if (c["customers"]["top1_share"] or 0) < 0.5), None)
    risk, good = {"effect": "neg"}, {"effect": "pos"}
    found = needs.offers_for(risk, concentrated, _news(["consumer_demand"]))
    assert [o["offer_id"] for o in found] == ["factoring"] and found[0]["label"] == "Реклама банка"
    assert "покупател" in found[0]["reason"]
    assert needs.offers_for(good, concentrated, _news(["consumer_demand"])) == [], "событие не риск — нет потребности"
    assert needs.offers_for(risk, concentrated, _news(["labor"])) == [], "тема не та — нет предложения"
    if spread:
        assert needs.offers_for(risk, spread, _news(["consumer_demand"])) == [], "нет концентрации покупателей"


def test_fx_and_new_country_need_foreign_trade(client):
    companies = _companies()
    ved = next(c for c in companies if c.get("fts_flag"))
    local = next(c for c in companies if not c.get("fts_flag"))
    assert [o["offer_id"] for o in needs.offers_for({"effect": "mixed"}, ved, _news(["fx"]))] == ["fx_hedge"]
    assert needs.offers_for({"effect": "mixed"}, local, _news(["fx"])) == [], "без ВЭД хеджирование не предлагаем"
    known = ved["fts_countries"][0]
    assert needs.offers_for({"effect": "neg"}, ved, _news(["imports_exports"], [known])) == [], "страна уже в расчетах"
    new = needs.offers_for({"effect": "neg"}, ved, _news(["imports_exports"], ["Бразилия"]))
    assert [o["offer_id"] for o in new] == ["ved_account"] and "Бразилия" in new[0]["reason"]
    assert needs.offers_for({"effect": "none"}, ved, _news(["fx"])) == [], "событие без влияния — без предложения"


def _insight_with_offer(client, company_id: str) -> tuple[dict, dict] | None:
    feed = client.get("/api/v1/feed", params={"company_id": company_id, "limit": 40}).json()["items"]
    for item in feed:
        ins = client.post("/api/v1/insights", json={"company_id": company_id, "news_id": item["news"]["news_id"],
                                                    "fast": True}).json()
        offers = client.get(f"/api/v1/insights/{ins['insight_id']}/offers").json()["offers"]
        if offers:
            return ins, offers[0]
    return None


@pytest.fixture
def lead_setup(client, company, new_client):
    found = _insight_with_offer(client, company["company_id"])
    if found is None:
        pytest.skip("в ленте компании нет события с потребностью")
    return found


def test_lead_needs_consent_and_is_visible_only_to_own_manager(client, company, new_client, lead_setup, monkeypatch):
    ins, offer = lead_setup
    body = {"insight_id": ins["insight_id"], "offer_id": offer["offer_id"]}
    assert client.post("/api/v1/leads", json=body).status_code == 400, "без согласия заявки нет"
    assert client.post("/api/v1/leads", json=body | {"consent": False}).status_code == 400
    assert client.post("/api/v1/leads", json=body | {"consent": True, "offer_id": "nope"}).status_code == 400
    created = client.post("/api/v1/leads", json=body | {"consent": True, "comment": "=HYPERLINK(1)"})
    assert created.status_code == 201 and created.json()["created"] and created.json()["status"] == "new"
    again = client.post("/api/v1/leads", json=body | {"consent": True}).json()
    assert again["created"] is False and again["id"] == created.json()["id"], "повтор не плодит заявки"
    assert client.get(f"/api/v1/insights/{ins['insight_id']}/offers").json()["leads"][0]["offer_id"] == offer["offer_id"]

    mine, other = new_client(), new_client()
    register(mine, "mgr@alfa-bank.test")
    register(other, "other-mgr@alfa-bank.test")
    assert mine.get("/api/v1/manager/leads").status_code == 403, "не менеджер — нет кабинета"
    leads.assign("mgr@alfa-bank.test", company["company_id"])
    leads.assign("other-mgr@alfa-bank.test", next(c["company_id"] for c in _companies() if c["company_id"] != company["company_id"]))
    assert mine.get("/api/v1/auth/me").json()["is_manager"] is True
    items = mine.get("/api/v1/manager/leads").json()["items"]
    assert [i["id"] for i in items] == [created.json()["id"]] and items[0]["headline"] == ins["headline"]
    assert other.get("/api/v1/manager/leads").json()["items"] == [], "чужой менеджер не видит заявку"
    lead_id = items[0]["id"]
    assert other.patch(f"/api/v1/manager/leads/{lead_id}", json={"status": "done"}).status_code == 404
    assert mine.patch(f"/api/v1/manager/leads/{lead_id}", json={"status": "in_progress"}).json()["status"] == "in_progress"
    csv_text = mine.get("/api/v1/manager/leads.csv").text
    assert "'=HYPERLINK(1)" in csv_text and "contact_email" in csv_text, "формула в CSV обезврежена"
    clients = mine.get("/api/v1/manager/clients", params={"hours": 24 * 30}).json()
    assert [c["company_id"] for c in clients["clients"]] == [company["company_id"]] and clients["priority_formula"]


def test_operator_assigns_managers(raw_client, company, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", OPERATOR)
    register(raw_client, OPERATOR)
    r = raw_client.post("/api/v1/admin/managers", json={"email": "Mgr@Alfa-Bank.test", "company_id": company["company_id"]})
    assert r.status_code == 200 and r.json()["managers"] == ["mgr@alfa-bank.test"]
    assert raw_client.delete("/api/v1/admin/managers", params={"email": "mgr@alfa-bank.test",
                                                               "company_id": company["company_id"]}).json()["managers"] == []
