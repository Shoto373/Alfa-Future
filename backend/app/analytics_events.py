"""Продуктовая аналитика (SPR4-07): события воронки и отчет пилота — без внешних систем и без персональных данных.

Событие — вид, псевдоним пользователя (тот же, что в логах), компания, роль и свойства-перечисления.
Свойства проверяются по белому списку: только короткие коды (буквы, цифры, «_-:»), числа и да/нет —
текст новости, вопроса или email в событие попасть не может. В каждое событие записываются варианты
экспериментов пользователя: отчет по варианту строится без отдельной таблицы назначений.

Метрики пилота: WAU руководителей, доля «полезно» с 95% доверительным интервалом (Уилсон), возвраты
на 7-й день, воронка «сводка → разбор → вопрос» и сравнение вариантов экспериментов.
"""

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import database, flags
from app.models import Delivery, ProductEvent
from app.observability import user_hash

KINDS: dict[str, set[str]] = {
    "feed_view": {"topic"},
    "insight_open": {"source", "cached", "mode"},
    "section_expand": {"section"},
    "source_click": {"kind"},
    "question_ask": {"intent", "suggested"},
    "feedback": {"rating", "section"},
    "offer_click": {"offer_id", "step"},
}
SOURCES = {"feed", "digest", "alert", "direct", "rail", "home", "counterparties"}
CODE = re.compile(r"^[a-z0-9_:\-]{1,40}$")
Z95 = 1.96


class EventError(ValueError):
    pass


def _clean(kind: str, props: dict) -> dict:
    if kind not in KINDS:
        raise EventError(f"Неизвестное событие: {kind}")
    out = {}
    for key, value in props.items():
        if key not in KINDS[kind]:
            raise EventError(f"Свойство {key} не разрешено для {kind}")
        if isinstance(value, bool) or (isinstance(value, int) and -10 <= value <= 10):
            out[key] = value
        elif isinstance(value, str) and CODE.match(value):
            out[key] = value
        else:
            raise EventError(f"Значение {key} — только код из букв, цифр и «_-:» (без текста и персональных данных)")
    if kind == "insight_open" and out.get("source", "direct") not in SOURCES:
        raise EventError("Неизвестный источник перехода")
    return out


def record(kind: str, user_id: str, company_id: str | None, role: str | None, props: dict) -> None:
    payload = {"props": _clean(kind, props), "variants": flags.variants(user_id, company_id)}
    with database.session() as db:
        db.add(ProductEvent(kind=kind, user_hash=user_hash(user_id), company_id=company_id, role=role, payload=payload))


# --- отчет ---

def wilson(successes: int, n: int) -> dict:
    """Доля и 95% доверительный интервал Уилсона: честный интервал и для малых выборок пилота."""
    if n == 0:
        return {"rate": None, "low": None, "high": None, "n": 0}
    p = successes / n
    center = (p + Z95 ** 2 / (2 * n)) / (1 + Z95 ** 2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / (1 + Z95 ** 2 / n)
    return {"rate": round(p, 3), "low": round(max(0.0, center - half), 3), "high": round(min(1.0, center + half), 3), "n": n}


def _events(since: datetime) -> list[ProductEvent]:
    with database.session() as db:
        return list(db.scalars(select(ProductEvent).where(ProductEvent.created_at >= since).order_by(ProductEvent.id)))


def _wau(events: list[ProductEvent], now: datetime, weeks: int) -> list[dict]:
    out = []
    for w in range(weeks - 1, -1, -1):
        end = now - timedelta(days=7 * w)
        users = {e.user_hash for e in events if end - timedelta(days=7) <= e.created_at < end}
        out.append({"week_end": end.date().isoformat(), "users": len(users)})
    return out


def _retention(events: list[ProductEvent], now: datetime) -> dict:
    """Возврат на 7-й день: пользователь, впервые пришедший 7+ дней назад, вернулся в дни 7–13 после первого визита."""
    first: dict[str, datetime] = {}
    days: dict[str, set[int]] = defaultdict(set)
    for e in events:
        first.setdefault(e.user_hash, e.created_at)
    for e in events:
        days[e.user_hash].add((e.created_at - first[e.user_hash]).days)
    cohort = [u for u, t in first.items() if t <= now - timedelta(days=7)]
    returned = sum(1 for u in cohort if days[u] & set(range(7, 14)))
    return wilson(returned, len(cohort))


def _funnel(events: list[ProductEvent], since: datetime) -> list[dict]:
    with database.session() as db:
        digest_users = {user_hash(u) for u in db.scalars(select(Delivery.user_id).where(
            Delivery.kind == "digest", Delivery.channel == "inapp", Delivery.created_at >= since).distinct())}
    opened = {e.user_hash for e in events if e.kind == "insight_open" and e.payload["props"].get("source") == "digest"}
    asked = {e.user_hash for e in events if e.kind == "question_ask"} & opened
    return [{"step": "digest", "label": "Получили сводку", "users": len(digest_users)},
            {"step": "insight", "label": "Открыли разбор из сводки", "users": len(opened)},
            {"step": "question", "label": "Задали вопрос", "users": len(asked)}]


def _useful(events: list[ProductEvent]) -> dict:
    ratings = [e.payload["props"].get("rating") for e in events if e.kind == "feedback"]
    return wilson(sum(1 for r in ratings if r == 1), sum(1 for r in ratings if r in (1, -1)))


def _experiments(events: list[ProductEvent]) -> list[dict]:
    out = []
    for key, flag in flags.FLAGS.items():
        if not flag.get("variants"):
            continue
        rows = []
        for variant in flag["variants"]:
            mine = [e for e in events if e.payload.get("variants", {}).get(key) == variant]
            rows.append({"variant": variant, "users": len({e.user_hash for e in mine}),
                         "opens": sum(1 for e in mine if e.kind == "insight_open"), "useful": _useful(mine)})
        out.append({"key": key, "description": flag["description"], "variants": rows})
    return out


def report(days: int = 28, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    events = _events(since)
    week = [e for e in events if e.created_at >= now - timedelta(days=7)]
    return {
        "days": days,
        "wau": len({e.user_hash for e in week}),
        "wau_by_role": {r: len({e.user_hash for e in week if e.role == r}) for r in sorted({e.role for e in week if e.role})},
        "wau_weeks": _wau(events, now, min(4, max(1, days // 7))),
        "useful": _useful(events),
        "retention_d7": _retention(events, now),
        "funnel": _funnel(events, since),
        "events": {k: sum(1 for e in events if e.kind == k) for k in KINDS},
        "experiments": _experiments(events),
    }
