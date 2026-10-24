"""Готовые учетные записи для локальной проверки: жюри входит и сразу видит ленту своей компании.

Только при DEMO_ACCOUNTS=1 — его задает локальный compose.yaml; в production (docker-compose.yml)
переменной нет, и учетные записи с известным паролем там не появляются.

    demo@alfa.test      — финансовый директор и основатель крупнейшей свободной металлургической компании набора;
    demo-ceo@alfa.test  — генеральный директор той же компании: сравнение персонализации по ролям;
    operator@alfa.test  — сотрудник банка (OPERATOR_EMAILS): метрики, расходы, аудит, выключатель AI.

Пароль у всех — DEMO_PASSWORD. Идемпотентно: существующие записи и привязки не меняются,
поэтому пароль, уже измененный вручную, сохраняется. Разборы для них строит фоновый конвейер.
"""

import logging

from sqlalchemy import func, select

from app import config, database
from app.errors import ApiError
from app.auth import store
from app.companies import profiles

logger = logging.getLogger("app.demo_accounts")

LOCK_ID = 72810408
DEMO_SECTOR = "metallurgy"
ACCOUNTS = (
    ("demo@alfa.test", "Демо — финансовый директор", "cfo"),
    ("demo-ceo@alfa.test", "Демо — генеральный директор", "ceo"),
    ("operator@alfa.test", "Демо — сотрудник банка", None),
)


def candidates() -> list[dict]:
    """Металлурги набора по убыванию выручки: первая свободная (или уже демо) компания — демо."""
    companies = [c for c in profiles._load()["companies"] if c["sector"] == DEMO_SECTOR]
    return sorted(companies, key=lambda c: -(c.get("revenue") or 0))


def _pick(founder: str) -> dict | None:
    for c in candidates():
        emails = {m["email"] for m in store.list_members(c["company_id"])}
        if not emails or founder in emails:
            return c
    return None


def ensure() -> dict | None:
    """Создает недостающие демо-записи; None — демо-записи выключены."""
    if not config.demo_accounts():
        return None
    password = config.demo_password()
    created = []
    with database.session() as db:  # несколько воркеров стартуют одновременно — создает один
        db.execute(select(func.pg_advisory_xact_lock(LOCK_ID)))
        for email, name, _ in ACCOUNTS:
            if store.find_user_by_email(email) is None:
                store.create_user(name, email, password)
                created.append(email)
        founder, _, role = ACCOUNTS[0]
        company = _pick(founder)  # компании настоящих пользователей не трогаем
        if company is not None:
            cid = company["company_id"]
            members = {m["email"] for m in store.list_members(cid)}
            if not members:
                store.claim(store.find_user_by_email(founder)["user_id"], cid, role)
            email, _, role = ACCOUNTS[1]
            if email not in members:
                try:
                    store.add_member(cid, email, role, is_admin=False)
                except ApiError as exc:
                    logger.warning("demo member not added: %s", exc)
    return {"created": created, "company_id": company["company_id"] if company else None}
