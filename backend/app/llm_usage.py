"""Дневной учет и бюджет LLM с резервированием (слой core: не зависит от агента).

Перед вызовом модели reserve() одним атомарным UPDATE … RETURNING прибавляет к строке дня
оценку вызова (токены запроса + max_tokens по цене модели) — только если потрачено + уже
зарезервировано + новый резерв укладываются в дневные лимиты токенов и стоимости. Параллельные
вызовы ждут блокировку той же строки и проверяют условие на свежих значениях, поэтому вместе
превысить лимит не могут. После ответа commit() списывает факт и снимает резерв, при ошибке —
release(). Резервы старше RESERVATION_TTL (процесс упал посреди вызова) снимаются sweep().
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app import config, database
from app.models import LLMReservation, LLMUsage, LLMUsageModel

RESERVATION_TTL = timedelta(minutes=10)


class BudgetExceeded(Exception):
    """Резерв не помещается в дневной лимит: вызов не выполняется, агент откатывается к правилам."""


@dataclass(frozen=True)
class Reservation:
    id: str
    day: date
    tokens: int
    cost: float
    model: str = ""


def budget_day() -> date:
    """Бюджет шлюза обнуляется в 03:00 по Москве, то есть в полночь UTC."""
    return datetime.now(timezone.utc).date()


def estimate(model: str, prompt_chars: int, max_tokens: int) -> tuple[int, float]:
    """Оценка сверху: токены запроса (~3 символа на токен) + максимум ответа, по цене модели."""
    tokens = prompt_chars // 3 + max_tokens
    return tokens, round(tokens / 1000 * config.llm_price_per_1k(model), 4)


def cost_of(model: str, tokens: int, reported: float | None) -> float:
    """Факт стоимости: usage.cost шлюза, а если его нет — по цене модели (иначе лимит в рублях не работает)."""
    return float(reported) if reported else round(tokens / 1000 * config.llm_price_per_1k(model), 4)


def usage(day: date | None = None) -> dict:
    """Учет дня бюджета (по умолчанию — текущего)."""
    day = day or budget_day()
    with database.session() as db:
        row = db.get(LLMUsage, day)
    s = config.llm_settings()
    get = lambda name: getattr(row, name) if row else 0
    return {"date": day.isoformat(), "tokens": get("tokens"), "cost": round(float(get("cost")), 3),
            "calls": get("calls"), "errors": get("errors"), "reserved_tokens": get("reserved_tokens"),
            "reserved_cost": round(float(get("reserved_cost")), 3), "rejected_by_budget": get("rejected"),
            "limit": s["daily_token_limit"], "cost_limit": s["daily_cost_limit"]}


def _ensure_day(db, day: date) -> None:
    db.execute(insert(LLMUsage).values(day=day).on_conflict_do_nothing(index_elements=[LLMUsage.day]))


def _unreserve(db, day: date, tokens: int, cost) -> None:
    db.execute(update(LLMUsage).where(LLMUsage.day == day).values(
        reserved_tokens=func.greatest(LLMUsage.reserved_tokens - tokens, 0),
        reserved_cost=func.greatest(LLMUsage.reserved_cost - cost, 0)))


def sweep(db=None) -> int:
    """Снимает резервы старше RESERVATION_TTL. Возвращает их число."""
    if db is None:
        with database.session() as db:
            return sweep(db)
    stale = db.execute(delete(LLMReservation)
                       .where(LLMReservation.created_at < datetime.now(timezone.utc) - RESERVATION_TTL)
                       .returning(LLMReservation.day, LLMReservation.tokens, LLMReservation.cost)).all()
    for day, tokens, cost in stale:
        _unreserve(db, day, tokens, cost)
    return len(stale)


def reserve(model: str, prompt_chars: int, max_tokens: int) -> Reservation:
    """Резервирует оценку вызова или поднимает BudgetExceeded (отказ учитывается в rejected)."""
    s = config.llm_settings()
    tokens, cost = estimate(model, prompt_chars, max_tokens)
    day = budget_day()
    with database.session() as db:
        sweep(db)
        _ensure_day(db, day)
        ok = db.execute(update(LLMUsage)
            .where(LLMUsage.day == day,
                   LLMUsage.tokens + LLMUsage.reserved_tokens + tokens <= s["daily_token_limit"],
                   LLMUsage.cost + LLMUsage.reserved_cost + cost <= s["daily_cost_limit"])
            .values(reserved_tokens=LLMUsage.reserved_tokens + tokens, reserved_cost=LLMUsage.reserved_cost + cost)
            .returning(LLMUsage.day)).first()
        if ok:
            res = Reservation(f"rsv-{uuid.uuid4().hex}", day, tokens, cost, model)
            db.add(LLMReservation(id=res.id, day=day, tokens=tokens, cost=cost))
        else:
            db.execute(update(LLMUsage).where(LLMUsage.day == day).values(rejected=LLMUsage.rejected + 1))
    if not ok:
        raise BudgetExceeded(f"Бюджет LLM: вызов (~{cost:.2f} ₽) не помещается в дневной лимит с учетом идущих запросов")
    return res


def _settle(db, res: Reservation) -> None:
    """Снимает резерв, если его еще не снял sweep()."""
    gone = db.execute(delete(LLMReservation).where(LLMReservation.id == res.id).returning(LLMReservation.id)).first()
    if gone:
        _unreserve(db, res.day, res.tokens, res.cost)


def _count_model(db, res: Reservation, **inc) -> None:
    """Те же счетчики по модели вызова (llm_usage_models)."""
    if not res.model:
        return
    stmt = insert(LLMUsageModel).values(day=res.day, model=res.model, **inc)
    db.execute(stmt.on_conflict_do_update(index_elements=[LLMUsageModel.day, LLMUsageModel.model],
        set_={k: getattr(LLMUsageModel, k) + getattr(stmt.excluded, k) for k in inc}))


def commit(res: Reservation, tokens: int, cost: float) -> None:
    """Списывает фактические токены и стоимость вызова и освобождает его резерв."""
    tokens, cost = max(0, tokens), max(0.0, cost)
    with database.session() as db:
        _settle(db, res)
        db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(
            tokens=LLMUsage.tokens + tokens, cost=LLMUsage.cost + cost, calls=LLMUsage.calls + 1))
        _count_model(db, res, tokens=tokens, cost=cost, calls=1)


def release(res: Reservation) -> None:
    """Вызов не состоялся или упал до ответа: резерв снимается, вызов учитывается как ошибка."""
    with database.session() as db:
        _settle(db, res)
        db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(
            calls=LLMUsage.calls + 1, errors=LLMUsage.errors + 1))
        _count_model(db, res, calls=1, errors=1)


def record_error(res: Reservation) -> None:
    """Ошибка после списания (ответ получен, но не годится): только счетчик ошибок."""
    with database.session() as db:
        db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(errors=LLMUsage.errors + 1))
        _count_model(db, res, errors=1)


def by_model(day: date | None = None) -> list[dict]:
    """Расход за день по моделям: фактическая цена за 1000 токенов рядом с оценкой резерва (config.LLM_PRICES)."""
    with database.session() as db:
        rows = db.scalars(select(LLMUsageModel).where(LLMUsageModel.day == (day or budget_day()))
                          .order_by(LLMUsageModel.cost.desc())).all()
    return [{"model": r.model, "tokens": r.tokens, "cost": round(float(r.cost), 3), "calls": r.calls, "errors": r.errors,
             "price_per_1k": round(float(r.cost) / r.tokens * 1000, 4) if r.tokens else None,
             "estimate_per_1k": config.llm_price_per_1k(r.model)} for r in rows]


def reserved_active() -> int:
    with database.session() as db:
        return db.scalar(select(func.count()).select_from(LLMReservation)) or 0
