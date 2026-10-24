"""Мониторинг контрагентов (SPR4-01): новость о контрагенте компании до второго уровня → алерт с цепочкой.

Организации в новостях — индекс news_entities (SPR3-02); связи — граф платежей (companies.graph).
Задача воркера counterparty_monitor проходит свежие новости для компаний с пользователями и сохраняет
алерт один раз на пару «компания × новость × контрагент». Сила события — по классификации новости.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import database, pipeline
from app.companies import graph
from app.models import CounterpartyAlert, NewsEntity
from app.news import store

WINDOW_DAYS = 14
STRENGTH = {"strong": 1.0, "moderate": 0.7, "weak": 0.4}


def _recent_entities(since: datetime) -> dict[str, set[str]]:
    """company_id → новости последних WINDOW_DAYS дней, где компания названа."""
    fresh = {n["news_id"] for n in store.all_items() if n["published_at"] >= since.isoformat()}
    with database.session() as db:
        rows = db.execute(select(NewsEntity.company_id, NewsEntity.news_id).where(NewsEntity.company_id.is_not(None))).all()
    out: dict[str, set[str]] = {}
    for company_id, news_id in rows:
        if news_id in fresh:
            out.setdefault(company_id, set()).add(news_id)
    return out


def _strength(news: dict) -> float:
    level = (news["classification"].get("magnitude") or {}).get("level")
    return round(STRENGTH.get(level, 0.5) * (0.5 + news["classification"].get("importance", 0.5)), 2)


def scan(now: datetime | None = None) -> int:
    """Новые алерты по всем компаниям с пользователями. Возвращает число новых алертов."""
    now = now or datetime.now(timezone.utc)
    mentioned = _recent_entities(now - timedelta(days=WINDOW_DAYS))
    if not mentioned:
        return 0
    created = 0
    for company_id in sorted({c for c, _ in pipeline.audience()}):
        for n in graph.neighbors(company_id):
            for news_id in mentioned.get(n["company_id"], ()):
                news = store.get(news_id)
                if news is None:
                    continue
                payload = {"chain": n["text"], "relation": n["relation"], "weight": round(n["weight"], 4),
                           "counterparty_name": n["name"], "title": news["title"], "published_at": news["published_at"],
                           "strength": _strength(news)}
                with database.session() as db:
                    new_id = db.execute(insert(CounterpartyAlert).values(
                        company_id=company_id, news_id=news_id, counterparty_id=n["company_id"], level=n["level"],
                        payload=payload).on_conflict_do_nothing(constraint="counterparty_alerts_uq")
                        .returning(CounterpartyAlert.id)).scalar()
                    created += new_id is not None
    return created


def alerts(company_id: str, limit: int = 30) -> list[dict]:
    with database.session() as db:
        rows = db.scalars(select(CounterpartyAlert).where(CounterpartyAlert.company_id == company_id)
                          .order_by(CounterpartyAlert.created_at.desc()).limit(limit))
        return [{"news_id": r.news_id, "counterparty_id": r.counterparty_id, "level": r.level,
                 "created_at": r.created_at.isoformat(), **r.payload} for r in rows]
