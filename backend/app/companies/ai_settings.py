"""Настройка компании: готовить ли AI-разборы важных новостей заранее и с какой важности.

Конвейер (app/pipeline.py) строит AI-версию разбора для новостей ленты компании с оценкой не ниже порога —
пользователь открывает уже готовый разбор вместо минуты ожидания. Выключено — модель вызывается только
по открытию разбора. Хранится в app_state, меняет администратор компании.
"""

from datetime import datetime, timezone

from app import database

KEY = "company_ai:"
THRESHOLD_MIN, THRESHOLD_MAX = 40, 95
DEFAULT = {"enabled": True, "threshold": 85}  # только самые важные события


def get(company_id: str) -> dict:
    saved = database.state(KEY + company_id) or {}
    return {"enabled": bool(saved.get("enabled", DEFAULT["enabled"])),
            "threshold": int(saved.get("threshold", DEFAULT["threshold"])),
            "updated_at": saved.get("updated_at")}


def save(company_id: str, enabled: bool, threshold: int, user_id: str) -> dict:
    threshold = max(THRESHOLD_MIN, min(THRESHOLD_MAX, int(threshold)))
    with database.session() as db:
        database.set_state(KEY + company_id, {"enabled": enabled, "threshold": threshold, "updated_by": user_id,
                                              "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, db)
    return get(company_id)
