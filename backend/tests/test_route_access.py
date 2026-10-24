"""Чужая компания недоступна ни по одному маршруту (SPR3-04): участник компании A не читает и не меняет
данные компании B. Тест сам находит в контракте маршруты, где участвует компания или ее разбор, —
новый маршрут без строки в ROUTES роняет тест, чтобы проверку прав не забыли."""

import json
from pathlib import Path

import pytest

from tests.conftest import register

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]
SCOPED = ("{company_id}", "{insight_id}")
SCOPED_BODIES = {"InsightRequest", "FeedbackRequest", "ScenarioRequest", "NotificationReadRequest"}
# Маршруты, где компания — в query (?company_id=) или в теле запроса.
QUERY_COMPANY = {"/api/v1/feed", "/api/v1/news/{news_id}", "/api/v1/notifications", "/api/v1/notifications/settings",
                 "/api/v1/notifications/test-digest"}
BODY_COMPANY = {"/api/v1/insights", "/api/v1/scenarios", "/api/v1/notifications/read"}

# (метод, путь) -> (тело или None, ожидаемые коды). company_id/insight_id/member_id подставляются компании B.
ROUTES = {
    ("GET", "/api/v1/companies/{company_id}"): (None, {403}),
    ("DELETE", "/api/v1/companies/{company_id}"): (None, {403}),
    ("GET", "/api/v1/companies/{company_id}/ai-settings"): (None, {403}),
    ("PUT", "/api/v1/companies/{company_id}/ai-settings"): ({"enabled": True, "threshold": 85}, {403}),
    ("GET", "/api/v1/companies/{company_id}/extra"): (None, {403}),
    ("PUT", "/api/v1/companies/{company_id}/extra"): ({"notes": "чужие заметки"}, {403}),
    ("POST", "/api/v1/companies/{company_id}/extra/files"): ("file", {403}),
    ("DELETE", "/api/v1/companies/{company_id}/extra/files/{file_id}"): (None, {403}),
    ("GET", "/api/v1/feed"): (None, {403}),
    ("GET", "/api/v1/news/{news_id}"): (None, {403}),
    ("GET", "/api/v1/insights/stream"): (None, {403}),
    ("GET", "/api/v1/companies/{company_id}/counterparties"): (None, {403}),
    ("POST", "/api/v1/scenarios"): ({"scenario": "key_rate", "shock": 1}, {403}),
    ("GET", "/api/v1/notifications"): (None, {403}),
    ("POST", "/api/v1/notifications/read"): ({}, {403}),
    ("GET", "/api/v1/notifications/settings"): (None, {403}),
    ("PUT", "/api/v1/notifications/settings"): ({"threshold": 90}, {403}),
    ("POST", "/api/v1/notifications/test-digest"): (None, {403}),
    ("POST", "/api/v1/insights"): ({"fast": True}, {403}),
    ("GET", "/api/v1/insights/{insight_id}"): (None, {403, 404}),
    ("POST", "/api/v1/insights/{insight_id}/questions"): ({"question": "Что с долгом?"}, {403, 404}),
    ("POST", "/api/v1/feedback"): ({"rating": 1}, {403, 404}),
    ("GET", "/api/v1/companies/{company_id}/members"): (None, {403}),
    ("POST", "/api/v1/companies/{company_id}/members"): ({"email": "spy@example.com", "role": "cfo"}, {403}),
    ("PATCH", "/api/v1/companies/{company_id}/members/{member_id}"): ({"is_admin": True}, {403}),
    ("DELETE", "/api/v1/companies/{company_id}/members/{member_id}"): (None, {403}),
    # Регистрация компании открыта всем, но занятую компанию повторно не занять.
    ("POST", "/api/v1/companies/{company_id}/claim"): ({"role": "cfo"}, {409}),
}


def scoped_routes() -> set[tuple[str, str]]:
    spec = json.loads((ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    found = set()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            params = {p["name"] for p in op.get("parameters", [])}
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            ref = body.get("$ref", "").rsplit("/", 1)[-1]
            if any(s in path for s in SCOPED) or "company_id" in params or ref in SCOPED_BODIES:
                found.add((method.upper(), path))
    return found


@pytest.mark.skipif(not (ROOT / "contracts").exists(), reason="в тестовом образе нет contracts/")
def test_every_company_route_is_checked():
    missing = scoped_routes() - set(ROUTES)
    assert not missing, f"маршруты без проверки доступа к чужой компании: {sorted(missing)}"


@pytest.fixture
def victim(raw_client, new_client, shared_profiles):
    """Компания B с участником, разбором и вторым участником; чужак — администратор своей компании A."""
    from app.companies import profiles

    companies = profiles._load()["companies"]
    owner = new_client()
    register(owner, "victim@example.com")
    b = companies[1]["company_id"]
    assert owner.post(f"{API}/companies/{b}/claim", json={"role": "cfo"}).status_code == 201
    member = owner.post(f"{API}/companies/{b}/members", json={"email": "colleague@example.com", "role": "ceo"}).json()
    news_id = owner.get(f"{API}/feed", params={"company_id": b}).json()["items"][0]["news"]["news_id"]
    insight = owner.post(f"{API}/insights", json={"company_id": b, "news_id": news_id, "fast": True}).json()
    outsider = new_client()
    register(outsider, "outsider@example.com")
    assert outsider.post(f"{API}/companies/{companies[0]['company_id']}/claim", json={"role": "cfo"}).status_code == 201
    return {"company_id": b, "member_id": member["member_id"], "insight_id": insight["insight_id"],
            "news_id": news_id, "outsider": outsider}


@pytest.mark.parametrize("route", sorted(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_outsider_cannot_touch_other_company(victim, route):
    method, path = route
    body, expected = ROUTES[route]
    url = path.format(company_id=victim["company_id"], insight_id=victim["insight_id"],
                      member_id=victim["member_id"], file_id="file-0", news_id=victim["news_id"])
    params = {"company_id": victim["company_id"]} if path in QUERY_COMPANY else None
    if path == "/api/v1/insights/stream":
        params = {"company_id": victim["company_id"], "news_id": victim["news_id"]}
    client = victim["outsider"]
    if body == "file":
        r = client.post(url, params={"name": "data.csv"}, content=b"a;b\n1;2\n")
    elif isinstance(body, dict):
        payload = dict(body)
        if path in BODY_COMPANY:
            payload["company_id"] = victim["company_id"]
        if path == "/api/v1/insights":
            payload["news_id"] = victim["news_id"]
        if path == "/api/v1/feedback":
            payload["insight_id"] = victim["insight_id"]
        r = client.request(method, url, json=payload, params=params)
    else:
        r = client.request(method, url, params=params)
    assert r.status_code in expected, f"{method} {path}: HTTP {r.status_code} {r.text[:200]}"
