"""Вход через корпоративный IdP по OIDC (SPR3-04): Authorization Code + PKCE (S256).

Провайдер — любой стандартный OIDC (локально Keycloak из compose, в пилоте — Альфа-ID): OIDC_ISSUER,
OIDC_CLIENT_ID, OIDC_CLIENT_SECRET (секрет — из файла, config.secret), OIDC_REDIRECT_URI. Если backend
ходит к IdP по внутреннему адресу (контейнеры), OIDC_INTERNAL_ISSUER — его база для обратного канала.

ID-токен приходит напрямую из token endpoint по обратному каналу, поэтому, по OIDC Core 3.1.3.7, подпись
не проверяется отдельно: проверяются iss, aud, exp и nonce. Состояние входа (state, verifier PKCE, nonce)
хранится на сервере, одноразово и 10 минут. Компании и роли берутся из claim OIDC_COMPANIES_CLAIM
(«company_id:role»): IdP — источник членства, права по-прежнему проверяются на сервере в каждом запросе.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete

from app import config, database
from app.auth import store
from app.companies import profiles
from app.models import AppState

STATE_PREFIX = "oidc:"
STATE_TTL_SECONDS = 600
TIMEOUT = 10.0
ROLES = {"owner", "ceo", "cfo", "accountant", "treasurer", "clevel"}


class OIDCError(Exception):
    """Вход через IdP не удался: пользователь возвращается на экран входа с сообщением."""


def enabled() -> bool:
    return bool(config.oidc_settings()["issuer"])


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _internal(url: str) -> str:
    """Адрес IdP для обратного канала: публичная база заменяется внутренней (контейнеры)."""
    s = config.oidc_settings()
    return s["internal_issuer"] + url[len(s["issuer"]):] if s["internal_issuer"] and url.startswith(s["issuer"]) else url


def discovery() -> dict:
    s = config.oidc_settings()
    response = httpx.get(_internal(s["issuer"]) + "/.well-known/openid-configuration", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _state_key(state: str) -> str:
    return STATE_PREFIX + hashlib.sha256(state.encode()).hexdigest()


def start(next_path: str = "/") -> str:
    """Адрес авторизации IdP с PKCE; state, verifier и nonce сохраняются на сервере."""
    s = config.oidc_settings()
    state, verifier, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(48), secrets.token_urlsafe(16)
    with database.session() as db:
        database.set_state(_state_key(state), {"verifier": verifier, "nonce": nonce, "at": time.time(),
                                               "next": next_path if next_path.startswith("/") else "/"}, db)
    query = {"response_type": "code", "client_id": s["client_id"], "redirect_uri": s["redirect_uri"],
             "scope": "openid email profile", "state": state, "nonce": nonce,
             "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    return discovery()["authorization_endpoint"] + "?" + urlencode(query)


def _pop_state(state: str) -> dict:
    with database.session() as db:
        saved = db.get(AppState, _state_key(state))
        payload = dict(saved.payload) if saved else None
        db.execute(delete(AppState).where(AppState.key == _state_key(state)))  # одноразово
    if not payload or time.time() - payload["at"] > STATE_TTL_SECONDS:
        raise OIDCError("Сеанс входа устарел — начните вход заново")
    return payload


def _claims(id_token: str) -> dict:
    try:
        body = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError) as exc:
        raise OIDCError("IdP вернул некорректный ID-токен") from exc


def _validate(claims: dict, nonce: str) -> None:
    s = config.oidc_settings()
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if claims.get("iss") != s["issuer"] or s["client_id"] not in audiences:
        raise OIDCError("ID-токен выдан не для этого сервиса")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < time.time():
        raise OIDCError("ID-токен просрочен")
    if claims.get("nonce") != nonce:
        raise OIDCError("ID-токен не относится к этому входу")
    if not claims.get("email"):
        raise OIDCError("IdP не передал email пользователя")


def exchange(code: str, state: str) -> tuple[dict, str]:
    """Код авторизации → проверенные claims и путь возврата."""
    s = config.oidc_settings()
    saved = _pop_state(state)
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": s["redirect_uri"],
            "client_id": s["client_id"], "code_verifier": saved["verifier"]}
    if s["client_secret"]:
        data["client_secret"] = s["client_secret"]
    try:
        response = httpx.post(_internal(discovery()["token_endpoint"]), data=data, timeout=TIMEOUT)
        response.raise_for_status()
        claims = _claims(response.json()["id_token"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise OIDCError("IdP не подтвердил вход") from exc
    _validate(claims, saved["nonce"])
    return claims, saved["next"]


def _assignments(claims: dict) -> list[tuple[str, str]]:
    """Компании и роли из claim: «U_26:cfo» или {"company_id": …, "role": …}; неизвестные пропускаются."""
    raw = claims.get(config.oidc_settings()["companies_claim"]) or []
    out = []
    for item in raw if isinstance(raw, list) else [raw]:
        cid, role = (item.get("company_id"), item.get("role")) if isinstance(item, dict) else (str(item).partition(":")[::2])
        if cid and role in ROLES and profiles.get(cid) is not None:
            out.append((cid, role))
    return out


def sync_user(claims: dict) -> dict:
    """Пользователь и членство из claims IdP: новый пользователь создается без пароля (только вход через IdP)."""
    email = claims["email"].strip().lower()
    user = store.find_user_by_email(email)
    if user is None:
        name = claims.get("name") or claims.get("preferred_username") or email.split("@")[0]
        user = store.create_user(name[:80], email, secrets.token_urlsafe(32))  # пароль никому не известен
    for cid, role in _assignments(claims):
        members = {m["email"]: m for m in store.list_members(cid)}
        mine = members.get(email)
        if mine is None:
            if not any(m["is_admin"] for m in members.values()):
                store.claim(user["user_id"], cid, role)
            else:
                store.add_member(cid, email, role, is_admin=False)
        elif mine["role"] != role:
            store.update_member(cid, mine["member_id"], role, None)
    return store.find_user_by_email(email)
