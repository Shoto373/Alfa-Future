"""Подписки пользователя на компанию (SPR4-04): что присылать, когда и куда.

Настройки хранятся в subscriptions.payload; отсутствующие поля берутся из DEFAULTS. Токен отписки —
случайный, по нему письмо отключается в один клик без входа.
"""

import secrets

from sqlalchemy import select

from app import database
from app.auth import store as auth_store
from app.models import Subscription

DEFAULTS = {
    "digest": True, "digest_time": "08:30", "timezone": "Europe/Moscow",
    "threshold": 75, "topics": [], "counterparties": True,
    "quiet_from": "22:00", "quiet_to": "08:00", "alerts_per_day": 3,
    "channels": {"inapp": True, "email": True, "telegram": False},
}


def _merge(payload: dict | None) -> dict:
    payload = payload or {}
    return {**DEFAULTS, **payload, "channels": {**DEFAULTS["channels"], **(payload.get("channels") or {})}}


def _row(db, user_id: str, company_id: str) -> Subscription:
    row = db.get(Subscription, (user_id, company_id))
    if row is None:
        row = Subscription(user_id=user_id, company_id=company_id, unsubscribe_token=secrets.token_urlsafe(24), payload={})
        db.add(row)
        db.flush()
    return row


def get(user_id: str, company_id: str) -> dict:
    with database.session() as db:
        row = _row(db, user_id, company_id)
        return {**_merge(row.payload), "unsubscribe_token": row.unsubscribe_token}


def save(user_id: str, company_id: str, changes: dict) -> dict:
    with database.session() as db:
        row = _row(db, user_id, company_id)
        payload = _merge(row.payload)
        payload.update({k: v for k, v in changes.items() if k in DEFAULTS and k != "channels"})
        if "channels" in changes:
            payload["channels"] = {**payload["channels"], **changes["channels"]}
        row.payload = payload
    return get(user_id, company_id)


def unsubscribe_email(token: str) -> bool:
    """Отписка из письма в один клик: выключает только почту, сводки в приложении остаются."""
    with database.session() as db:
        row = db.scalar(select(Subscription).where(Subscription.unsubscribe_token == token))
        if row is None:
            return False
        payload = _merge(row.payload)
        payload["channels"] = {**payload["channels"], "email": False}
        row.payload = payload
        return True


def audience() -> list[dict]:
    """Все пользователи компаний с их ролью и настройками (подписка по умолчанию — для каждого участника)."""
    out = []
    for company_id in sorted(auth_store.claimed_ids()):
        for m in auth_store.list_members(company_id):
            if not m.get("user_id"):
                continue
            user = auth_store.get_user(m["user_id"])
            if user is None:
                continue
            out.append({"user_id": m["user_id"], "email": user["email"], "company_id": company_id, "role": m["role"],
                        "settings": get(m["user_id"], company_id)})
    return out
