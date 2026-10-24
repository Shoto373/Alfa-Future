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
    assert r.json() == {"user_id": r.json()["user_id"], "name": "Иван", "email": "ivan@example.com", "memberships": [],
                        "is_operator": False, "is_manager": False}
    cookie = r.headers["set-cookie"].lower()
    assert "session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # frontend_origin — http
    assert raw_client.get(f"{API}/auth/me").json()["email"] == "ivan@example.com"

    assert raw_client.post(f"{API}/auth/logout").status_code == 204
    assert_error(raw_client.get(f"{API}/auth/me"), 401, "UNAUTHORIZED")

    ok = raw_client.post(f"{API}/auth/login", json={"email": "IVAN@example.com", "password": "correct-horse"})
    assert ok.status_code == 200 and ok.json()["name"] == "Иван"
    assert raw_client.get(f"{API}/auth/me").status_code == 200


def test_session_token_and_password_not_stored_in_clear(raw_client):
    from sqlalchemy import select

    from app import database
    from app.models import AuthSession, AuthUser

    register(raw_client)
    token = raw_client.cookies.get("session")
    with database.session() as db:
        stored = [str(v) for row in db.execute(select(AuthUser.pw_salt, AuthUser.pw_hash, AuthUser.pw_params)).all()
                  for v in row] + list(db.scalars(select(AuthSession.token_hash)))
    blob = " ".join(stored)
    assert token not in blob and "correct-horse" not in blob


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


def test_lookup_hides_financials_and_shows_claimed(client, company, new_client, monkeypatch):
    monkeypatch.setenv("SHOWCASE_PER_SECTOR", "0")  # все компании: проверяются поля и отметка «занята»
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
    assert any(m["is_admin"] for m in client.get(f"{API}/auth/me").json()["memberships"])


def test_pending_invited_admin_does_not_count_as_admin(client, company):
    cid = company["company_id"]
    client.post(f"{API}/companies/{cid}/members", json={"email": "ghost@example.com", "role": "cfo", "is_admin": True})
    own = next(x for x in client.get(f"{API}/companies/{cid}/members").json()["members"] if x["status"] == "active")
    assert_error(client.delete(f"{API}/companies/{cid}/members/{own['member_id']}"), 403, "FORBIDDEN")


def test_non_member_gets_403(client, company, new_client, monkeypatch):
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
    # Сводные данные по всем клиентам (метрики, расходы LLM, аудит, сбор новостей) — только сотрудникам банка.
    service = [("/metrics", "get"), ("/metrics/daily", "get"), ("/audit", "get"), ("/news/refresh", "post")]
    for path, method in service:
        assert_error(getattr(eve, method)(API + path), 403, "FORBIDDEN")
        # Администратор компании — представитель клиента, а не банка: чужие отзывы и расходы ему закрыты.
        assert_error(getattr(client, method)(API + path), 403, "FORBIDDEN")
    monkeypatch.setenv("OPERATOR_EMAILS", "Eve@Example.com")
    assert eve.get(f"{API}/metrics").status_code == 200 and eve.get(f"{API}/audit").status_code == 200
    assert eve.get(f"{API}/metrics/daily").status_code == 200
    assert_error(client.get(f"{API}/metrics"), 403, "FORBIDDEN")
    # /meta открыт без входа, поэтому расходов банка на LLM в нем нет.
    assert "usage" not in eve.get(f"{API}/meta").json()["llm"]


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


# --- SPR2-02: пользователи и сессии в PostgreSQL ---

def test_two_workers_do_not_lose_registrations_or_invites(raw_client, company, new_client):
    """Как при двух воркерах uvicorn: параллельные записи в одну базу не теряются, инварианты держатся."""
    from concurrent.futures import ThreadPoolExecutor

    from app.auth import store

    cid = company["company_id"]
    owner = store.create_user("Основатель", "founder@example.com", "correct-horse")
    store.claim(owner["user_id"], cid, "cfo")
    with ThreadPoolExecutor(10) as pool:
        users = list(pool.map(lambda i: store.create_user(f"U{i}", f"u{i}@example.com", "correct-horse"), range(20)))
        list(pool.map(lambda i: store.add_member(cid, f"invite{i}@example.com", "ceo", False), range(20)))
    assert len({u["user_id"] for u in users}) == 20
    members = store.list_members(cid)
    assert len(members) == 21 and sum(m["status"] == "invited" for m in members) == 20

    # Пять пользователей одновременно регистрируют одну свободную компанию — основатель ровно один.
    free = other_company(company)["company_id"]

    def try_claim(u):
        try:
            store.claim(u["user_id"], free, "ceo")
            return "ok"
        except Exception as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(try_claim, users[:5]))
    assert results.count("ok") == 1
    assert sum(m["is_founder"] for m in store.list_members(free)) == 1


def test_session_expires_without_activity_and_slides_with_it(raw_client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app import database
    from app.auth import security
    from app.models import AuthSession

    register(raw_client)
    token_hash = security.hash_token(raw_client.cookies.get("session"))

    def shift(**values):
        with database.session() as db:
            for key, value in values.items():
                setattr(db.get(AuthSession, token_hash), key, value)

    now = datetime.now(timezone.utc)
    # Активность продлевает: last_seen давно, срок близок — после запроса срок снова ~SESSION_TTL_HOURS.
    shift(last_seen=now - timedelta(hours=1), expires_at=now + timedelta(minutes=1))
    assert raw_client.get(f"{API}/auth/me").status_code == 200
    with database.session() as db:
        assert db.get(AuthSession, token_hash).expires_at > now + timedelta(hours=11)
    # Без активности сессия истекает.
    shift(expires_at=now - timedelta(seconds=1))
    assert_error(raw_client.get(f"{API}/auth/me"), 401, "UNAUTHORIZED")


def test_old_password_hash_is_upgraded_on_login(raw_client, monkeypatch):
    from app.auth import security, store

    register(raw_client, "legacy@example.com")
    raw_client.post(f"{API}/auth/logout")
    monkeypatch.setattr(security, "SCRYPT_PARAMS", {"n": 2 ** 13, "r": 8, "p": 1, "dklen": 32})  # «новые» параметры
    assert raw_client.post(f"{API}/auth/login", json={"email": "legacy@example.com", "password": "correct-horse"}).status_code == 200
    user = store.find_user_by_email("legacy@example.com")
    assert user["pw_params"]["n"] == 2 ** 13, "пароль перехэширован текущими параметрами"
    raw_client.post(f"{API}/auth/logout")
    assert raw_client.post(f"{API}/auth/login", json={"email": "legacy@example.com", "password": "correct-horse"}).status_code == 200


def test_lockout_is_shared_and_counts_per_email(raw_client, new_client):
    register(raw_client, "shared@example.com")
    raw_client.post(f"{API}/auth/logout")
    other = new_client()  # другой клиент (как другой воркер или IP): счетчик общий — по email
    for c in (raw_client, other) * 2 + (raw_client,):
        assert_error(c.post(f"{API}/auth/login", json={"email": "shared@example.com", "password": "bad-password"}),
                     401, "INVALID_CREDENTIALS")
    assert_error(other.post(f"{API}/auth/login", json={"email": "shared@example.com", "password": "correct-horse"}),
                 429, "TOO_MANY_ATTEMPTS")


def test_legacy_json_accounts_move_to_postgres_once(tmp_path, company, new_client):
    """Перенос учетных записей прод-JSON: пароли, членство и живые сессии работают; повтор не дублирует;
    исходные файлы на месте; после переноса JSON больше не читается (удаленный участник не возвращается)."""
    import time

    from app import legacy_import
    from app.auth import security, store

    salt, digest, _ = security.hash_password("old-password")
    token = security.new_token()
    cid = company["company_id"]
    files = {
        "users.json": {"users": {
            "usr-old1": {"user_id": "usr-old1", "name": "Старый", "email": "Old@Example.com", "pw_salt": salt,
                         "pw_hash": digest, "created_at": "2026-10-20T10:00:00+00:00"},
            "usr-old2": {"user_id": "usr-old2", "name": "Дубль", "email": "old@example.com", "pw_salt": salt,
                         "pw_hash": digest, "created_at": "2026-10-21T10:00:00+00:00"}}},
        "memberships.json": {"members": [
            {"member_id": "mem-old1", "company_id": cid, "user_id": "usr-old1", "email": "old@example.com",
             "role": "cfo", "is_admin": True, "founder": True, "created_at": "2026-10-20T10:01:00+00:00"},
            {"member_id": "mem-old2", "company_id": cid, "user_id": None, "email": "invited@example.com",
             "role": "ceo", "is_admin": False, "created_at": "2026-10-20T10:02:00+00:00"}]},
        "sessions.json": {"sessions": {security.hash_token(token): {"user_id": "usr-old1", "expires_at": time.time() + 3600},
                                       "dead": {"user_id": "usr-old1", "expires_at": time.time() - 10}}},
    }
    for name, body in files.items():
        (tmp_path / name).write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")

    from sqlalchemy import delete

    from app import database
    from app.models import AppState

    with database.session() as db:  # как первый запуск на сервере: переноса еще не было
        db.execute(delete(AppState).where(AppState.key == legacy_import.AUTH_MARKER))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert legacy_import.import_auth_once(empty) is None
    assert database.state(legacy_import.AUTH_MARKER) is None, "без users.json отметка не ставится: файлы подложат позже"
    first = legacy_import.import_auth_once(tmp_path)
    assert first == {"users": 1, "memberships": 2, "sessions": 1}, "дубль по регистру слит, мертвая сессия пропущена"
    assert legacy_import.import_auth_once(tmp_path) is None, "повторный запуск ничего не делает"
    assert all((tmp_path / n).exists() for n in files), "исходные файлы не удаляются"

    c = new_client()
    c.cookies.set("session", token)
    me = c.get(f"{API}/auth/me").json()
    assert me["email"] == "old@example.com" and me["memberships"][0]["is_founder"], "живая сессия перенесена"
    c2 = new_client()
    assert c2.post(f"{API}/auth/login", json={"email": "OLD@example.com", "password": "old-password"}).status_code == 200
    # Приглашение привязывается при регистрации, удаленный участник из JSON не возвращается.
    store.remove_member(cid, "mem-old2")
    legacy_import.import_auth_once(tmp_path)
    assert all(m["member_id"] != "mem-old2" for m in store.list_members(cid))


def test_others_cannot_lock_the_owner_out(raw_client):
    """Пять неверных паролей с чужого адреса не запирают владельца; общий потолок — против перебора."""
    from app.auth import security, store

    register(raw_client, "victim@example.com")
    raw_client.post(f"{API}/auth/logout")
    for _ in range(security.MAX_FAILS + 1):
        store.login_attempt("victim@example.com", "203.0.113.7")  # злоумышленник
    assert not store.login_attempt("victim@example.com", "203.0.113.7"), "адрес злоумышленника заблокирован"
    ok = raw_client.post(f"{API}/auth/login", json={"email": "victim@example.com", "password": "correct-horse"})
    assert ok.status_code == 200, "владелец со своего адреса входит"
    for i in range(security.MAX_FAILS_PER_EMAIL):
        store.login_attempt("victim@example.com", f"198.51.100.{i}")  # перебор с множества адресов
    assert not store.login_attempt("victim@example.com", "192.0.2.1"), "общий потолок на email"


def test_parallel_wrong_passwords_cannot_exceed_the_limit(raw_client):
    from concurrent.futures import ThreadPoolExecutor

    from app.auth import security, store

    with ThreadPoolExecutor(20) as pool:
        allowed = list(pool.map(lambda _: store.login_attempt("burst@example.com", "203.0.113.9"), range(20)))
    assert sum(allowed) <= security.MAX_FAILS, "попытка записывается до проверки — параллельные видят друг друга"


def test_client_ip_trusts_proxy_header_only_from_internal_address():
    from types import SimpleNamespace

    from app.auth.deps import client_ip

    def req(host, header=None):
        return SimpleNamespace(client=SimpleNamespace(host=host), headers={"x-real-ip": header} if header else {})

    assert client_ip(req("172.18.0.5", "203.0.113.7")) == "203.0.113.7", "nginx во внутренней сети"
    assert client_ip(req("93.184.216.34", "1.2.3.4")) == "93.184.216.34", "внешний клиент не подделает адрес"
    assert client_ip(req("127.0.0.1")) == "127.0.0.1"


def test_lookup_offers_showcase_companies(client, monkeypatch):
    """Для регистрации — по 1–2 компании каждой отрасли с самыми полными данными, а не весь набор."""
    from app.companies import profiles

    monkeypatch.setenv("SHOWCASE_PER_SECTOR", "1")
    shown = client.get(f"{API}/companies/lookup", params={"limit": 50}).json()
    sectors = [profiles.get(i["company_id"])["sector"] for i in shown["items"]]
    assert shown["total"] >= 1 and len(sectors) == len(set(sectors)), "не больше одной компании на отрасль"
    monkeypatch.setenv("SHOWCASE_PER_SECTOR", "0")
    assert client.get(f"{API}/companies/lookup", params={"limit": 1}).json()["total"] > shown["total"]
