"""Фичефлаги, эксперименты и продуктовая аналитика (SPR4-07)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app import analytics_events, database, flags
from app.models import ProductEvent
from tests.conftest import register

OPERATOR = "operator@alfa.test"


def test_rollout_is_stable_and_proportional(raw_client):
    flags.save("dialog", 30, None)
    current = flags.settings()
    users = [f"user-{i}" for i in range(2000)]
    on = [u for u in users if flags.evaluate(u, None, current)["dialog"]["enabled"]]
    assert 0.25 < len(on) / len(users) < 0.35, "30% раскатки — около 30% пользователей"
    assert on == [u for u in users if flags.evaluate(u, None, current)["dialog"]["enabled"]], "тот же человек — тот же ответ"
    flags.save("dialog", 0, ["U_1"])
    assert flags.evaluate("user-1", "U_1")["dialog"]["enabled"], "компания пилота включена принудительно"
    assert not flags.evaluate("user-1", "U_2")["dialog"]["enabled"]


def test_pilot_companies_from_env(raw_client, monkeypatch):
    flags.save("bank_offers", 0, None)
    monkeypatch.setenv("PILOT_COMPANIES", "U_7, U_8")
    assert flags.evaluate("x", "U_8")["bank_offers"]["enabled"] and not flags.evaluate("x", "U_9")["bank_offers"]["enabled"]


def test_experiment_variants_split_and_control_when_off(raw_client):
    users = [f"u{i}" for i in range(1000)]
    current = flags.settings()
    share = sum(flags.evaluate(u, None, current)["insight_section_order"]["variant"] == "actions_first" for u in users) / 1000
    assert 0.4 < share < 0.6, "два варианта — примерно поровну"
    flags.save("insight_section_order", 0, None)
    assert {flags.evaluate(u)["insight_section_order"]["variant"] for u in users[:50]} == {"default"}, "выключен — контроль"


def test_events_reject_free_text(client, company):
    cid = company["company_id"]
    ok = client.post("/api/v1/events", json={"kind": "insight_open", "company_id": cid, "props": {"source": "digest"}})
    assert ok.status_code == 202
    for bad in ({"kind": "insight_open", "props": {"source": "Иван Петров"}},
                {"kind": "insight_open", "props": {"email": "a@b.ru"}},
                {"kind": "feedback", "props": {"rating": 1, "section": "a@b.ru"}},
                {"kind": "unknown_event", "props": {}}):
        assert client.post("/api/v1/events", json={"company_id": cid, **bad}).status_code == 400, bad
    with database.session() as db:
        row = db.query(ProductEvent).one()
    assert row.user_hash != client.get("/api/v1/auth/me").json()["user_id"] and len(row.user_hash) == 12
    assert set(row.payload["variants"]) == {"insight_section_order", "digest_format"}


def test_other_company_events_forbidden(client, new_client, company):
    stranger = new_client()
    register(stranger, "stranger@example.com")
    r = stranger.post("/api/v1/events", json={"kind": "feed_view", "company_id": company["company_id"]})
    assert r.status_code == 403


def test_wilson_interval():
    assert analytics_events.wilson(0, 0)["rate"] is None
    w = analytics_events.wilson(8, 10)
    assert w["rate"] == 0.8 and 0.48 < w["low"] < 0.5 and 0.94 < w["high"] < 0.95
    assert analytics_events.wilson(80, 100)["high"] - analytics_events.wilson(80, 100)["low"] < w["high"] - w["low"]


def _event(kind, user, props=None, days_ago=0, variants=None):
    analytics_events.record(kind, user, None, "cfo", props or {})
    if days_ago or variants:
        with database.session() as db:
            row = db.query(ProductEvent).order_by(ProductEvent.id.desc()).first()
            row.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
            if variants:
                row.payload = {**row.payload, "variants": variants}


def test_report_metrics(raw_client, monkeypatch):
    # u1 пришел 10 дней назад и вернулся на 8-й день; u2 пришел 9 дней назад и не вернулся; u3 — новый.
    _event("feed_view", "u1", days_ago=10)
    _event("insight_open", "u1", {"source": "digest"}, days_ago=2)
    _event("question_ask", "u1", {"intent": "quantify"}, days_ago=2)
    _event("feed_view", "u2", days_ago=9)
    _event("feed_view", "u3")
    for i, rating in enumerate((1, 1, 1, -1)):
        _event("feedback", f"f{i}", {"rating": rating, "section": "risks"},
               variants={"insight_section_order": "default" if i < 2 else "actions_first", "digest_format": "list"})
    r = analytics_events.report(28)
    assert r["retention_d7"]["n"] == 2 and r["retention_d7"]["rate"] == 0.5
    assert r["useful"]["rate"] == 0.75 and r["useful"]["n"] == 4 and r["useful"]["low"] < 0.75 < r["useful"]["high"]
    assert r["funnel"][1]["users"] == 1 and r["funnel"][2]["users"] == 1, "открыл из сводки и спросил"
    assert r["wau"] == 6 and r["wau_by_role"] == {"cfo": 6}
    exp = next(e for e in r["experiments"] if e["key"] == "insight_section_order")
    by = {v["variant"]: v for v in exp["variants"]}
    assert by["default"]["useful"]["rate"] == 1.0 and by["actions_first"]["useful"]["rate"] == 0.5


def test_admin_endpoints_operator_only(client, raw_client, new_client, monkeypatch):
    assert client.get("/api/v1/admin/product").status_code == 403
    assert client.get("/api/v1/flags").json()["flags"]["dialog"]["enabled"] in (True, False)
    monkeypatch.setenv("OPERATOR_EMAILS", OPERATOR)
    op = new_client()
    register(op, OPERATOR)
    assert op.put("/api/v1/admin/flags/digest_format", json={"percent": 50}).json()["percent"] == 50
    assert op.put("/api/v1/admin/flags/nope", json={"percent": 5}).status_code == 400
    assert op.get("/api/v1/admin/product", params={"days": 28}).json()["days"] == 28


def test_compact_digest_variant(client, company):
    from tests.test_notify import _moment, _rows, _user
    from app.notifications import service
    flags.save("digest_format", 100, None)
    user_id = _user(client)
    variant = flags.evaluate(user_id, company["company_id"])["digest_format"]["variant"]
    service.tick(_moment(user_id, company["company_id"]))
    digest = _rows(kind="digest", channel="inapp")[0]
    assert digest.payload["format"] == variant
    assert len(digest.payload["items"]) <= (3 if variant == "compact" else 5)


def test_bank_offers_flag_hides_offers(client, company):
    from tests.test_manager import _insight_with_offer
    found = _insight_with_offer(client, company["company_id"])
    if found is None:
        pytest.skip("в ленте компании нет события с потребностью")
    flags.save("bank_offers", 0, None)
    assert client.get(f"/api/v1/insights/{found[0]['insight_id']}/offers").json()["offers"] == [], "флаг выключен — предложений нет"
