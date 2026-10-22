"""Аутентификация, членство в компаниях и права."""

import json

from tests.conftest import register
from tests.test_api import ORIGIN, assert_error

API = "/api/v1"


def claim(c, company_id, role="cfo"):
    return c.post(f"{API}/companies/{company_id}/claim", json={"role": role})


def other_company(company):
    from app.companies import profiles

    return next(c for c in profiles._load()["companies"] if c["company_id"] != company["company_id"])


def test_register_login_logout_me(raw_client):
    r = raw_client.post(f"{API}/auth/register", json={"name": " Иван ", "email": "  Ivan@Example.COM ", "password": "correct-horse"})
    assert r.status_code == 201
    assert r.json() == {"user_id": r.json()["user_id"], "name": "Иван", "email": "ivan@example.com", "memberships": []}
    cookie = r.headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # frontend_origin — http
    assert raw_client.get(f"{API}/auth/me").json()["email"] == "ivan@example.com"

    assert raw_client.post(f"{API}/auth/logout").status_code == 204
    assert_error(raw_client.get(f"{API}/auth/me"), 401, "UNAUTHORIZED")

    ok = raw_client.post(f"{API}/auth/login", json={"email": "IVAN@example.com", "password": "correct-horse"})
    assert ok.status_code == 200 and ok.json()["name"] == "Иван"
    assert raw_client.get(f"{API}/auth/me").status_code == 200


def test_session_token_and_password_not_stored_in_clear(raw_client, isolated_runtime):
    register(raw_client)
    token = raw_client.cookies.get("session")
    files = "".join((isolated_runtime / n).read_text(encoding="utf-8") for n in ("users.json", "sessions.json"))
    assert token not in files and "correct-horse" not in files


def test_validation_and_duplicate_email(raw_client):
    for body in ({"name": "", "email": "a@b.co", "password": "12345678"},
                 {"name": "A", "email": "not-an-email", "password": "12345678"},
                 {"name": "A", "email": "a@b.co", "password": "short"},
                 {"name": "A", "email": "a@b.co", "password": "x" * 129}):
        assert_error(raw_client.post(f"{API}/auth/register", json=body), 400, "INVALID_REQUEST")
    register(raw_client, "dup@example.com")
    r = raw_client.post(f"{API}/auth/register", json={"name": "B", "email": "DUP@example.com", "password": "another-pass"})
    assert_error(r, 409, "EMAIL_TAKEN")


def test_wrong_password_hides_email_existence(raw_client):
    register(raw_client, "real@example.com")
    raw_client.post(f"{API}/auth/logout")
    a = raw_client.post(f"{API}/auth/login", json={"email": "real@example.com", "password": "wrong-password"})
    b = raw_client.post(f"{API}/auth/login", json={"email": "ghost@example.com", "password": "wrong-password"})
    assert_error(a, 401, "INVALID_CREDENTIALS")
    assert_error(b, 401, "INVALID_CREDENTIALS")
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_lockout_after_five_failures(raw_client):
    register(raw_client, "lock@example.com")
    raw_client.post(f"{API}/auth/logout")
    for _ in range(5):
        assert_error(raw_client.post(f"{API}/auth/login", json={"email": "lock@example.com", "password": "bad-password"}), 401, "INVALID_CREDENTIALS")
    # Даже верный пароль блокируется на время блокировки.
    assert_error(raw_client.post(f"{API}/auth/login", json={"email": "lock@example.com", "password": "correct-horse"}), 429, "TOO_MANY_ATTEMPTS")


def test_endpoints_require_session(raw_client, company):
    cid = company["company_id"]
    for method, path in [("get", "/companies"), ("get", "/companies/lookup"), ("get", f"/companies/{cid}"), ("get", f"/feed?company_id={cid}"),
                         ("get", "/news/seed-rate-hold"), ("get", "/analytics"), ("get", "/metrics"), ("get", "/audit"),
                         ("get", f"/companies/{cid}/members"), ("get", "/insights/ins-x")]:
        assert_error(getattr(raw_client, method)(API + path), 401, "UNAUTHORIZED")
    for path in ("/news", "/news/refresh", "/insights", "/feedback", f"/companies/{cid}/claim", f"/companies/{cid}/members"):
        assert raw_client.post(API + path, json={}).status_code == 401
    assert raw_client.get(f"{API}/meta").status_code == 200


def test_lookup_hides_financials_and_shows_claimed(client, company, new_client):
    body = client.get(f"{API}/companies/lookup", params={"q": company["company_id"]}).json()
    item = body["items"][0]
    assert set(item) == {"company_id", "display_name", "sector_name", "region", "claimed"} and item["claimed"] is True
    other = other_company(company)
    items = client.get(f"{API}/companies/lookup", params={"q": other["company_id"], "limit": 1}).json()["items"]
    assert items[0]["claimed"] is False and body["total"] >= 1


def test_claim_twice_and_limit(client, company, new_client):
    assert_error(claim(client, company["company_id"]), 409, "COMPANY_CLAIMED")
    second = new_client()
    register(second, "second@example.com")
    assert_error(claim(second, company["company_id"], "ceo"), 409, "COMPANY_CLAIMED")
    assert_error(claim(second, "U_nope"), 404, "COMPANY_NOT_FOUND")
    assert_error(second.post(f"{API}/companies/{company['company_id']}/claim", json={"role": "intern"}), 400, "INVALID_REQUEST")

    from app.companies import profiles
    others = [c["company_id"] for c in profiles._load()["companies"] if c["company_id"] != company["company_id"]][:5]
    assert [claim(second, cid).status_code for cid in others] == [201] * 5
    assert_error(claim(second, _free(others, company)), 409, "TOO_MANY_COMPANIES")
    assert len(second.get(f"{API}/auth/me").json()["memberships"]) == 5


def _free(used, company):
    from app.companies import profiles
    return next(c["company_id"] for c in profiles._load()["companies"] if c["company_id"] not in used and c["company_id"] != company["company_id"])


def test_invite_existing_and_pending_then_register(client, company, new_client):
    cid = company["company_id"]
    bob = new_client()
    register(bob, "bob@example.com", "Боб")
    r = client.post(f"{API}/companies/{cid}/members", json={"email": "BOB@example.com", "role": "ceo"})
    assert r.status_code == 201
    m = r.json()
    assert m["status"] == "active" and m["name"] == "Боб" and m["role"] == "ceo" and m["is_admin"] is False
    assert_error(client.post(f"{API}/companies/{cid}/members", json={"email": "bob@example.com", "role": "ceo"}), 409, "MEMBER_EXISTS")

    inv = client.post(f"{API}/companies/{cid}/members", json={"email": "new@example.com", "role": "accountant"}).json()
    assert inv["status"] == "invited" and inv["user_id"] is None and inv["name"] is None
    newbie = new_client()
    user = register(newbie, "new@example.com")
    assert user["memberships"][0]["company_id"] == cid and user["memberships"][0]["role"] == "accountant"

    # Роль меняет администратор; участник видит свои права в /auth/me.
    p = client.patch(f"{API}/companies/{cid}/members/{m['member_id']}", json={"role": "treasurer", "is_admin": True})
    assert p.status_code == 200 and p.json()["role"] == "treasurer" and p.json()["is_admin"] is True
    me = bob.get(f"{API}/auth/me").json()["memberships"][0]
    assert me["role"] == "treasurer" and me["is_admin"] is True
    listing = bob.get(f"{API}/companies/{cid}/members").json()["members"]
    assert {x["email"] for x in listing} == {"owner@example.com", "bob@example.com", "new@example.com"}
    assert client.delete(f"{API}/companies/{cid}/members/{inv['member_id']}").status_code == 204
    assert_error(client.delete(f"{API}/companies/{cid}/members/{inv['member_id']}"), 404, "MEMBER_NOT_FOUND")


def test_member_cannot_manage(client, company, new_client):
    cid = company["company_id"]
    bob = new_client()
    register(bob, "bob@example.com")
    bm = client.post(f"{API}/companies/{cid}/members", json={"email": "bob@example.com", "role": "ceo"}).json()
    owner = next(x for x in bob.get(f"{API}/companies/{cid}/members").json()["members"] if x["email"] == "owner@example.com")
    assert_error(bob.post(f"{API}/companies/{cid}/members", json={"email": "x@example.com", "role": "ceo"}), 403, "FORBIDDEN")
    assert_error(bob.patch(f"{API}/companies/{cid}/members/{owner['member_id']}", json={"role": "ceo"}), 403, "FORBIDDEN")
    assert_error(bob.delete(f"{API}/companies/{cid}/members/{owner['member_id']}"), 403, "FORBIDDEN")
    # Свою роль участник тоже не меняет.
    assert_error(bob.patch(f"{API}/companies/{cid}/members/{bm['member_id']}", json={"role": "owner"}), 403, "FORBIDDEN")
    # Выйти из компании может.
    assert bob.delete(f"{API}/companies/{cid}/members/{bm['member_id']}").status_code == 204
    assert_error(bob.get(f"{API}/companies/{cid}/members"), 403, "FORBIDDEN")


def test_cannot_change_own_role_and_last_admin(client, company, new_client):
    cid = company["company_id"]
    me = client.get(f"{API}/auth/me").json()
    own = next(x for x in client.get(f"{API}/companies/{cid}/members").json()["members"] if x["user_id"] == me["user_id"])
    assert_error(client.patch(f"{API}/companies/{cid}/members/{own['member_id']}", json={"role": "ceo"}), 403, "FORBIDDEN")
    assert_error(client.patch(f"{API}/companies/{cid}/members/{own['member_id']}", json={"is_admin": False}), 403, "FORBIDDEN")
    # Основатель не может выйти: только расформировать компанию.
    assert_error(client.delete(f"{API}/companies/{cid}/members/{own['member_id']}"), 403, "FORBIDDEN")

    bob = new_client()
    register(bob, "bob@example.com")
    bm = client.post(f"{API}/companies/{cid}/members", json={"email": "bob@example.com", "role": "cfo", "is_admin": True}).json()
    # Второй администратор не может ни понизить, ни удалить основателя, ни расформировать компанию.
    assert_error(bob.patch(f"{API}/companies/{cid}/members/{own['member_id']}", json={"is_admin": False}), 403, "FORBIDDEN")
    assert_error(bob.delete(f"{API}/companies/{cid}/members/{own['member_id']}"), 403, "FORBIDDEN")
    assert_error(bob.delete(f"{API}/companies/{cid}"), 403, "FORBIDDEN")
    # Сам он выйти может: основатель остаётся администратором.
    assert bob.delete(f"{API}/companies/{cid}/members/{bm['member_id']}").status_code == 204
    assert client.get(f"{API}/metrics").status_code == 200


def test_pending_invited_admin_does_not_count_as_admin(client, company):
    cid = company["company_id"]
    client.post(f"{API}/companies/{cid}/members", json={"email": "ghost@example.com", "role": "cfo", "is_admin": True})
    own = next(x for x in client.get(f"{API}/companies/{cid}/members").json()["members"] if x["status"] == "active")
    assert_error(client.delete(f"{API}/companies/{cid}/members/{own['member_id']}"), 403, "FORBIDDEN")


def test_non_member_gets_403(client, company, new_client):
    cid = company["company_id"]
    ins = client.post(f"{API}/insights", json={"company_id": cid, "news_id": "seed-rate-hold"}).json()
    eve = new_client()
    register(eve, "eve@example.com")
    assert_error(eve.get(f"{API}/feed", params={"company_id": cid}), 403, "FORBIDDEN")
    assert_error(eve.post(f"{API}/insights", json={"company_id": cid, "news_id": "seed-rate-hold"}), 403, "FORBIDDEN")
    assert_error(eve.get(f"{API}/insights/{ins['insight_id']}"), 403, "FORBIDDEN")
    assert_error(eve.post(f"{API}/insights/{ins['insight_id']}/questions", json={"question": "Что дальше?"}), 403, "FORBIDDEN")
    assert_error(eve.post(f"{API}/feedback", json={"insight_id": ins["insight_id"], "rating": 1}), 403, "FORBIDDEN")
    assert_error(eve.get(f"{API}/companies/{cid}"), 403, "FORBIDDEN")
    assert_error(eve.get(f"{API}/companies/{cid}/members"), 403, "FORBIDDEN")
    assert eve.get(f"{API}/companies").json() == {"total": 0, "items": []}
    # Не администратор: метрики, аудит и обновление новостей закрыты.
    for path, method in [("/metrics", "get"), ("/audit", "get"), ("/news/refresh", "post")]:
        assert_error(getattr(eve, method)(API + path), 403, "FORBIDDEN")
    assert client.get(f"{API}/metrics").status_code == 200


def test_role_comes_from_membership(client, company, new_client):
    cid = company["company_id"]  # у администратора роль cfo
    ins = client.post(f"{API}/insights", json={"company_id": cid, "news_id": "seed-rate-hold"}).json()
    assert ins["role"] == "cfo"
    assert client.get(f"{API}/feed", params={"company_id": cid, "role": "owner"}).json()["role"] == "cfo"
    # Клиентскую роль в теле запрос не принимает.
    assert_error(client.post(f"{API}/insights", json={"company_id": cid, "news_id": "seed-rate-hold", "role": "owner"}), 400, "INVALID_REQUEST")
    bob = new_client()
    register(bob, "bob@example.com")
    client.post(f"{API}/companies/{cid}/members", json={"email": "bob@example.com", "role": "owner"})
    assert bob.post(f"{API}/insights", json={"company_id": cid, "news_id": "seed-rate-hold"}).json()["role"] == "owner"
    assert bob.get(f"{API}/feed", params={"company_id": cid}).json()["role"] == "owner"


def test_foreign_origin_rejected_on_unsafe_methods(client, company):
    r = client.post(f"{API}/auth/logout", headers={"Origin": "http://evil.example"})
    assert_error(r, 403, "FORBIDDEN")
    assert client.post(f"{API}/auth/logout", headers={"Origin": ORIGIN}).status_code == 204


def test_request_body_limit_still_applies_to_auth(raw_client):
    body = json.dumps({"name": "A", "email": "a@b.co", "password": "x" * 70000}).encode()
    r = raw_client.post(f"{API}/auth/register", content=body, headers={"Content-Type": "application/json"})
    assert_error(r, 413, "REQUEST_TOO_LARGE")


def test_disband_company(client, company, new_client):
    cid = company["company_id"]
    bob = new_client()
    register(bob, "bob@example.com")
    client.post(f"{API}/companies/{cid}/members", json={"email": "bob@example.com", "role": "ceo"})
    client.post(f"{API}/companies/{cid}/members", json={"email": "pending@example.com", "role": "cfo"})
    # Не администратор расформировать не может.
    assert_error(bob.delete(f"{API}/companies/{cid}"), 403, "FORBIDDEN")
    assert client.delete(f"{API}/companies/{cid}").status_code == 204
    # Доступ у всех пропал, компания снова свободна для регистрации.
    assert_error(client.get(f"{API}/companies/{cid}/members"), 403, "FORBIDDEN")
    assert_error(bob.get(f"{API}/feed", params={"company_id": cid}), 403, "FORBIDDEN")
    assert client.get(f"{API}/auth/me").json()["memberships"] == []
    assert claim(bob, cid, "ceo").status_code == 201
