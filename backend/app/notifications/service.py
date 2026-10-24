"""Тик рассылки (SPR4-04): задача воркера notify_tick раз в 5 минут решает, кому что отправить.

Сводка — раз в день после времени сводки пользователя (в его часовом поясе) и не позже чем через
DIGEST_LATE (rules) часов: запущенный вечером сервис не пришлет «утреннюю» сводку в 20:00.
Алерты — вне тихих часов, не больше alerts_per_day в сутки, один на сюжет.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app import database
from app.companies import profiles
from app.models import Delivery
from app.notifications import delivery, rules, settings as subscriptions

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")


def _channels(member: dict) -> list[str]:
    on = member["settings"]["channels"]
    return [c for c in delivery.CHANNELS if on.get(c) and (c != "email" or member["email"])]


def _payload(member: dict, title: str, items: list[dict], **extra) -> dict:
    return {"title": title, "items": items, "email": member["email"],
            "unsubscribe_token": member["settings"]["unsubscribe_token"], **extra}


def _company_name(company_id: str) -> str:
    return (profiles.get(company_id) or {}).get("display_name") or "вашей компании"


def _exists(key: str) -> bool:
    with database.session() as db:
        return db.scalar(select(Delivery.id).where(Delivery.key == key).limit(1)) is not None


def digest_for(member: dict, now: datetime, key: str) -> list[int]:
    items = rules.digest_items(member["company_id"], member["role"], member["settings"])
    if not items:
        return []
    day = rules.local(now, member["settings"])
    title = f"Сводка на {day.day} {MONTHS[day.month - 1]}: {len(items)} события для {_company_name(member['company_id'])}"
    return delivery.create(member["user_id"], member["company_id"], "digest", key, _channels(member),
                           _payload(member, title, items))


def alerts_for(member: dict, now: datetime) -> list[int]:
    s, user_id, company_id = member["settings"], member["user_id"], member["company_id"]
    if rules.quiet(s, now):
        return []
    budget = s["alerts_per_day"] - delivery.alerts_today(user_id, company_id, now)
    if budget <= 0:
        return []
    done = delivery.alerted_stories(user_id, company_id, now)
    created = []
    for item in rules.alert_items(company_id, member["role"], s, now):
        if budget <= 0:
            break
        if item["story_id"] in done:
            continue
        prefix = "Событие у контрагента" if item["source"] == "counterparty" else "Важное событие"
        created += delivery.create(user_id, company_id, "alert", f"alert:{user_id}:{company_id}:{item['story_id']}",
                                   _channels(member), _payload(member, f"{prefix}: {item['title']}", [item],
                                                               story_id=item["story_id"]))
        done.add(item["story_id"])
        budget -= 1
    return created


def tick(now: datetime | None = None) -> dict:
    """Один проход по всем подписчикам. Возвращает число новых записей журнала по видам."""
    now = now or datetime.now(timezone.utc)
    counts = {"digest": 0, "alert": 0}
    for member in subscriptions.audience():
        key = rules.digest_key(member["user_id"], member["company_id"], now, member["settings"])
        if key and not _exists(key):
            counts["digest"] += len(digest_for(member, now, key))
        counts["alert"] += len(alerts_for(member, now))
    return counts


def test_digest(user: dict, company_id: str, role: str) -> dict:
    """«Отправить тестовую сводку»: сводка сейчас, вне расписания, по каналам пользователя."""
    now = datetime.now(timezone.utc)
    member = {"user_id": user["user_id"], "email": user["email"], "company_id": company_id, "role": role,
              "settings": subscriptions.get(user["user_id"], company_id)}
    ids = digest_for(member, now, f"test:{user['user_id']}:{company_id}:{now.timestamp():.3f}")
    return {"created": len(ids), "channels": _channels(member) if ids else []}
