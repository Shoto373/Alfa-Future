"""Безопасность (SPR3-04): вход через OIDC с PKCE, лимиты частоты, заголовки безопасности, секреты из файлов,
ключ LLM не попадает в журналы и трассу."""

import base64
import hashlib
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import config, llm
from app.auth import oidc, store

API = "/api/v1"
ISSUER = "http://idp.test/realms/alfa"


def _jwt(claims: dict) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{part({'alg': 'RS256'})}.{part(claims)}.signature"


@pytest.fixture
def idp(monkeypatch, company):
    """Подставной IdP: discovery и token endpoint; ID-токен с компанией пользователя в claim alfa_companies."""
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "alfa-pulse")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/oidc/callback")
    seen = {"claims": {}, "token_requests": []}

    def get(url, timeout):
        assert url == ISSUER + "/.well-known/openid-configuration"
        return httpx.Response(200, request=httpx.Request("GET", url), json={
            "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
            "token_endpoint": ISSUER + "/protocol/openid-connect/token"})

    def post(url, data, timeout):
        seen["token_requests"].append(data)
        claims = {"iss": ISSUER, "aud": "alfa-pulse", "exp": time.time() + 300, "nonce": seen["nonce"],
                  "email": "Pilot@Alfa.test", "name": "Пилот", "alfa_companies": [f"{company['company_id']}:cfo"]}
        claims |= seen["claims"]
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id_token": _jwt(claims)})

    monkeypatch.setattr(oidc.httpx, "get", get)
    monkeypatch.setattr(oidc.httpx, "post", post)
    return seen


def _start(raw_client, idp) -> dict:
    r = raw_client.get(f"{API}/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 302
    query = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    idp["nonce"] = query["nonce"]
    return query


def test_oidc_login_with_pkce_creates_user_and_membership(raw_client, idp, company):
    query = _start(raw_client, idp)
    assert query["code_challenge_method"] == "S256" and query["client_id"] == "alfa-pulse"
    r = raw_client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "http://localhost:3000/"
    verifier = idp["token_requests"][0]["code_verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == query["code_challenge"], "token endpoint получил verifier к этому challenge"
    me = raw_client.get(f"{API}/auth/me").json()
    assert me["email"] == "pilot@alfa.test"
    assert [(m["company_id"], m["role"]) for m in me["memberships"]] == [(company["company_id"], "cfo")]


def test_oidc_state_is_single_use(raw_client, idp):
    query = _start(raw_client, idp)
    raw_client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    again = raw_client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    assert "/login?error=" in again.headers["location"], "повтор того же state отклоняется"


@pytest.mark.parametrize("bad", [{"iss": "http://evil.test"}, {"aud": "other-client"}, {"exp": 1}, {"nonce": "forged"}])
def test_oidc_rejects_foreign_or_expired_tokens(raw_client, idp, bad):
    query = _start(raw_client, idp)
    idp["claims"] = bad
    r = raw_client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    assert "/login?error=" in r.headers["location"]
    assert store.find_user_by_email("pilot@alfa.test") is None


def test_oidc_role_and_membership_follow_idp(raw_client, idp, company, new_client):
    query = _start(raw_client, idp)
    raw_client.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    second = new_client()
    query = _start(second, idp)
    idp["claims"] = {"email": "ceo@alfa.test", "alfa_companies": [f"{company['company_id']}:ceo", "U_nonexistent:cfo", "x:hacker"]}
    second.get(f"{API}/auth/oidc/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    me = second.get(f"{API}/auth/me").json()
    assert [(m["company_id"], m["role"], m["is_admin"]) for m in me["memberships"]] == [(company["company_id"], "ceo", False)], \
        "вторая роль — участник без прав администратора; несуществующие компании и роли пропускаются"


def test_password_login_can_be_disabled(raw_client, monkeypatch):
    monkeypatch.setenv("AUTH_PASSWORD_ENABLED", "0")
    r = raw_client.post(f"{API}/auth/register", json={"name": "Иван", "email": "x@example.com", "password": "correct-horse"})
    assert r.status_code == 403
    assert raw_client.get(f"{API}/auth/methods").json() == {"password": False, "oidc": False}


def test_rate_limit_returns_429_with_retry_after(client, company, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_INSIGHTS", "2,0")
    news_id = client.get(f"{API}/feed", params={"company_id": company["company_id"]}).json()["items"][0]["news"]["news_id"]
    body = {"company_id": company["company_id"], "news_id": news_id, "fast": True}
    codes = [client.post(f"{API}/insights", json=body) for _ in range(3)]
    assert [r.status_code for r in codes[:2]] == [200, 200]
    assert codes[2].status_code == 429 and codes[2].json()["error"]["code"] == "TOO_MANY_REQUESTS"
    assert 1 <= int(codes[2].headers["retry-after"]) <= 61


def test_api_responses_carry_security_headers(raw_client):
    r = raw_client.get(f"{API}/meta")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert "content-security-policy" not in raw_client.get("/docs").headers, "документации API нужны свои скрипты"


def test_session_cookie_is_httponly_lax_and_secure_on_https(raw_client, monkeypatch):
    r = raw_client.post(f"{API}/auth/register", json={"name": "Иван", "email": "c@example.com", "password": "correct-horse"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://pointers-team.online")
    r = raw_client.post(f"{API}/auth/register", json={"name": "Иван", "email": "d@example.com", "password": "correct-horse"})
    assert "secure" in r.headers["set-cookie"].lower()


def test_secrets_are_read_from_files(tmp_path, monkeypatch):
    path = tmp_path / "llm_key"
    path.write_text("sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(path))
    assert config.llm_settings()["api_key"] == "sk-from-file", "файл важнее переменной окружения"


def test_llm_key_never_reaches_logs_or_trace(raw_client, company, monkeypatch, caplog):
    import asyncio

    from app.agent import orchestrator
    from app.news import store as news

    key = "sk-SECRET-should-never-be-logged"
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", key)
    monkeypatch.setattr(llm, "_down_until", 0.0)

    def failing(url, json, timeout, headers):
        raise httpx.ConnectError(f"cannot connect, auth header {headers.get('Authorization')}", request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", failing)
    caplog.set_level(logging.DEBUG)
    insight = asyncio.run(orchestrator.run(company, "cfo", news.all_items()[0], "req_secret"))
    assert key not in json.dumps(insight, ensure_ascii=False), "ключ не попадает в трассу и разбор"
    assert key not in caplog.text, "ключ не попадает в журналы"
