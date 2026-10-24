"""Заявки «обсудить с менеджером» и клиенты менеджеров (SPR4-06).

Заявка создается только с явного согласия пользователя: в ней контекст разбора (новость, вывод,
предложение) и текст согласия. Наружу заявки не уходят: менеджер видит их в кабинете, выгрузка — CSV.
Менеджер — сотрудник банка, за которым закреплены компании (manager_clients); чужих клиентов он не видит.
"""

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app import database
from app.models import Lead, ManagerClient

STATUSES = ("new", "in_progress", "done", "declined")
FORMULA_START = ("=", "+", "-", "@", chr(9), chr(13))  # с этих символов Excel начинает формулу
CONSENT_TEXT = ("Согласен передать менеджеру Альфа-Банка эту новость, вывод разбора и выбранное предложение, "
                "чтобы он связался со мной")


def companies_of(email: str) -> set[str]:
    with database.session() as db:
        return set(db.scalars(select(ManagerClient.company_id).where(ManagerClient.email == email.lower())))


def managers_of(company_id: str) -> list[str]:
    with database.session() as db:
        return list(db.scalars(select(ManagerClient.email).where(ManagerClient.company_id == company_id)
                               .order_by(ManagerClient.email)))


def assign(email: str, company_id: str) -> None:
    with database.session() as db:
        db.execute(insert(ManagerClient).values(email=email.lower(), company_id=company_id).on_conflict_do_nothing())


def unassign(email: str, company_id: str) -> None:
    with database.session() as db:
        db.execute(delete(ManagerClient).where(ManagerClient.email == email.lower(), ManagerClient.company_id == company_id))


def _view(row: Lead) -> dict:
    return {"id": row.id, "company_id": row.company_id, "insight_id": row.insight_id, "offer_id": row.offer_id,
            "status": row.status, "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
            **{k: row.payload.get(k) for k in ("company_name", "contact_name", "role", "news_title", "headline",
                                               "offer_title", "need", "reason", "comment")}}


def create(user: dict, role: str, insight: dict, offer: dict, company_name: str, comment: str | None) -> tuple[dict, bool]:
    """Заявка по согласию; повтор той же заявки возвращает существующую (created=False)."""
    payload = {"company_name": company_name, "contact_name": user["name"], "contact_email": user["email"], "role": role,
               "news_title": insight["title"], "headline": insight["headline"], "offer_title": offer["title"],
               "need": offer["need"], "reason": offer["reason"], "comment": comment, "consent": CONSENT_TEXT}
    with database.session() as db:
        new_id = db.execute(insert(Lead).values(
            company_id=insight["company_id"], user_id=user["user_id"], insight_id=insight["insight_id"],
            offer_id=offer["offer_id"], consent_at=datetime.now(timezone.utc), payload=payload)
            .on_conflict_do_nothing(constraint="leads_user_insight_offer_uq").returning(Lead.id)).scalar()
        row = db.get(Lead, new_id) if new_id else db.scalar(select(Lead).where(
            Lead.user_id == user["user_id"], Lead.insight_id == insight["insight_id"], Lead.offer_id == offer["offer_id"]))
        return _view(row), new_id is not None


def of_companies(company_ids: set[str], with_contact: bool = True) -> list[dict]:
    if not company_ids:
        return []
    with database.session() as db:
        rows = db.scalars(select(Lead).where(Lead.company_id.in_(company_ids)).order_by(Lead.created_at.desc(), Lead.id.desc()))
        return [{**_view(r), **({"contact_email": r.payload["contact_email"]} if with_contact else {})} for r in rows]


def of_user(user_id: str, insight_id: str) -> list[dict]:
    with database.session() as db:
        rows = db.scalars(select(Lead).where(Lead.user_id == user_id, Lead.insight_id == insight_id))
        return [_view(r) for r in rows]


def set_status(lead_id: int, status: str, allowed: set[str]) -> dict | None:
    """Смена статуса менеджером; заявка чужого клиента — None (для API неотличима от несуществующей)."""
    with database.session() as db:
        row = db.get(Lead, lead_id)
        if row is None or row.company_id not in allowed:
            return None
        row.status = status
        db.flush()
        return _view(row)


def _cell(value) -> str:
    """Ячейка CSV без формул: текст новости или комментарий, начинающийся с «=», Excel не выполнит."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in FORMULA_START else text


def to_csv(items: list[dict]) -> str:
    cols = ["id", "created_at", "status", "company_name", "contact_name", "contact_email", "role", "offer_title", "need",
            "news_title", "headline", "comment"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", delimiter=";")
    writer.writeheader()
    writer.writerows({k: _cell(v) for k, v in item.items()} for item in items)
    return buf.getvalue()


def crm_stub(lead_id: int) -> str:
    """Вебхук в CRM банка — заглушка (SPR4-06): заявка не уходит наружу, в ней отмечается, что ее подхватила бы CRM.
    Настоящая интеграция заменит эту функцию; формат — тот же, что в выгрузке CSV."""
    with database.session() as db:
        row = db.get(Lead, lead_id)
        if row is None:
            return "missing"
        row.payload = {**row.payload, "crm": {"status": "stub", "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
        return "stub"
