"""Доставка сводок и алертов (SPR4-04): журнал deliveries, каналы inapp / email / telegram (заглушка).

Запись создается один раз на пару (ключ, канал) — повторный тик воркера или второй воркер не шлют дубль.
В приложении сообщение доступно сразу; письмо отправляет задача воркера notify_deliver с повторами очереди.
В теме письма нет названия компании и сумм — только вид сообщения и дата: тема видна в списке писем и в логах почты.
"""

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app import config, database
from app.models import Delivery
from app.worker import queue as jobs

logger = logging.getLogger("app.notifications")
CHANNELS = ("inapp", "email", "telegram")
SUBJECT = {"digest": "Альфа.Пульс: утренняя сводка", "alert": "Альфа.Пульс: важное событие"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def link(news_id: str, source: str, delivery_id: int | None = None) -> str:
    """Ссылка на событие с меткой источника перехода (?from=digest|alert) для учета открытий."""
    suffix = f"&d={delivery_id}" if delivery_id else ""
    return f"{config.frontend_origin()}/pulse/n/{quote(news_id, safe='')}?from={source}{suffix}"


def create(user_id: str, company_id: str, kind: str, key: str, channels: list[str], payload: dict) -> list[int]:
    """Записи журнала по включенным каналам; возвращает id новых (уже созданные пропускаются)."""
    created = []
    with database.session() as db:
        for channel in channels:
            status, sent_at = ("sent", _now()) if channel == "inapp" else ("queued", None)
            new_id = db.execute(insert(Delivery).values(
                user_id=user_id, company_id=company_id, kind=kind, channel=channel, key=key, status=status,
                sent_at=sent_at, payload=payload).on_conflict_do_nothing(constraint="deliveries_key_channel_uq")
                .returning(Delivery.id)).scalar()
            if new_id is not None:
                created.append(new_id)
                if channel != "inapp":
                    jobs.enqueue("notify_deliver", {"id": new_id}, dedupe_key=f"notify_deliver:{new_id}", max_attempts=4)
    return created


def alerts_today(user_id: str, company_id: str, now: datetime | None = None) -> int:
    """Алерты за последние сутки (по записям в приложении — одна на алерт при любом наборе каналов)."""
    since = (now or _now()) - timedelta(days=1)
    with database.session() as db:
        return db.scalar(select(func.count(func.distinct(Delivery.key))).where(
            Delivery.user_id == user_id, Delivery.company_id == company_id, Delivery.kind == "alert",
            Delivery.created_at >= since)) or 0


def alerted_stories(user_id: str, company_id: str, now: datetime | None = None) -> set[str]:
    """Сюжеты, о которых уже был алерт за сутки: продолжение того же события не шлется повторно."""
    since = (now or _now()) - timedelta(days=1)
    with database.session() as db:
        rows = db.scalars(select(Delivery.payload["story_id"].astext).where(
            Delivery.user_id == user_id, Delivery.company_id == company_id, Delivery.kind == "alert",
            Delivery.created_at >= since))
        return {r for r in rows if r}


def _body(row: Delivery) -> str:
    p = row.payload
    lines = [p["title"], ""]
    for i, item in enumerate(p["items"], 1):
        lines += [f"{i}. {item['headline']}", f"   {link(item['news_id'], row.kind, row.id)}", ""]
    lines += ["Оценки и разборы — справочная аналитика, не инвестиционная рекомендация.",
              f"Отписаться от писем: {config.public_api_url()}/api/v1/notifications/unsubscribe?token={p['unsubscribe_token']}"]
    return "\n".join(lines)


def _message(row: Delivery, email: str) -> EmailMessage:
    smtp = config.smtp_settings()
    msg = EmailMessage()
    msg["Subject"] = f"{SUBJECT[row.kind]} · {row.created_at.astimezone(timezone.utc):%d.%m}"
    msg["From"], msg["To"] = smtp["sender"], email
    unsubscribe = f"{config.public_api_url()}/api/v1/notifications/unsubscribe?token={row.payload['unsubscribe_token']}"
    msg["List-Unsubscribe"] = f"<{unsubscribe}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(_body(row))
    return msg


def _send_email(row: Delivery) -> str:
    smtp = config.smtp_settings()
    if not smtp["host"]:
        return "skipped"
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=15) as server:
        if smtp["tls"]:
            server.starttls()
        if smtp["user"]:
            server.login(smtp["user"], smtp["password"])
        server.send_message(_message(row, row.payload["email"]))
    return "sent"


def _finish(delivery_id: int, status: str, error: str | None) -> None:
    with database.session() as db:
        db.execute(update(Delivery).where(Delivery.id == delivery_id).values(
            status=status, error=error, attempts=Delivery.attempts + 1, sent_at=_now() if status == "sent" else None))


def deliver(delivery_id: int) -> str:
    """Отправка одной записи журнала. Сбой SMTP — исключение: очередь повторит задачу с задержкой.

    Письмо уходит вне транзакции: медленный почтовый сервер не держит соединение с базой."""
    with database.session() as db:
        row = db.get(Delivery, delivery_id)
    if row is None or row.status in ("sent", "skipped"):
        return row.status if row else "missing"
    try:
        status = _send_email(row) if row.channel == "email" else "skipped"  # telegram — заглушка до подключения бота
    except (OSError, smtplib.SMTPException) as exc:
        _finish(delivery_id, "failed", type(exc).__name__)
        logger.warning("delivery %s failed: %s", delivery_id, type(exc).__name__)
        raise
    _finish(delivery_id, status, None if status == "sent" else f"{row.channel}: канал не настроен")
    return status


def inbox(user_id: str, company_id: str, limit: int = 30) -> dict:
    with database.session() as db:
        rows = db.scalars(select(Delivery).where(Delivery.user_id == user_id, Delivery.company_id == company_id,
                                                 Delivery.channel == "inapp")
                          .order_by(Delivery.created_at.desc(), Delivery.id.desc()).limit(limit)).all()
        items = [{"id": r.id, "kind": r.kind, "title": r.payload["title"], "created_at": r.created_at.isoformat(),
                  "read": r.read_at is not None,
                  "items": [{**{k: i[k] for k in ("news_id", "headline", "score")},
                             "href": f"/pulse/n/{quote(i['news_id'], safe='')}?from={r.kind}&d={r.id}"} for i in r.payload["items"]]}
                 for r in rows]
    return {"items": items, "unread": sum(not i["read"] for i in items)}


def mark_read(user_id: str, company_id: str, ids: list[int] | None) -> int:
    query = update(Delivery).where(Delivery.user_id == user_id, Delivery.company_id == company_id,
                                   Delivery.channel == "inapp", Delivery.read_at.is_(None))
    if ids:
        query = query.where(Delivery.id.in_(ids))
    with database.session() as db:
        return db.execute(query.values(read_at=_now())).rowcount


def opened(user_id: str, delivery_id: int) -> bool:
    """Переход по ссылке из сводки или алерта: отмечает открытие (и прочтение) своей записи."""
    now = _now()
    with database.session() as db:
        row = db.get(Delivery, delivery_id)
        if row is None or row.user_id != user_id:
            return False
        row.opened_at = row.opened_at or now
        row.read_at = row.read_at or now
        return True


def stats(days: int = 7) -> dict:
    """Доставлено и открыто по видам — для отчета и продуктовой аналитики."""
    since = _now() - timedelta(days=days)
    with database.session() as db:
        rows = db.execute(select(Delivery.kind, Delivery.channel, Delivery.status, func.count(),
                                 func.count(Delivery.opened_at))
                          .where(Delivery.created_at >= since).group_by(Delivery.kind, Delivery.channel, Delivery.status)).all()
    return {"days": days, "rows": [{"kind": k, "channel": c, "status": s, "count": n, "opened": o} for k, c, s, n, o in rows]}
