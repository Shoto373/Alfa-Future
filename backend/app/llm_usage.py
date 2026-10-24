"""Дневной учет и бюджет LLM с резервированием (слой core: не зависит от агента).

Перед вызовом модели reserve() одним атомарным UPDATE … RETURNING прибавляет к строке дня
оценку вызова (токены запроса + max_tokens по цене модели) — только если потрачено + уже
зарезервировано + новый резерв укладываются в дневные лимиты токенов и стоимости. Параллельные
вызовы ждут блокировку той же строки и проверяют условие на свежих значениях, поэтому вместе
превысить лимит не могут. После ответа commit() списывает факт и снимает резерв, при ошибке —
release(). Резервы старше RESERVATION_TTL (процесс упал посреди вызова) снимаются sweep().

Бюджет общий на весь сервис, поэтому вызов в контексте компании (for_company) резервируется и в ее
доле LLM_COMPANY_SHARE: одна компания не израсходует день за всех. При пересечении 50/80/100%
лимита команда сразу получает оповещение (app/notify.py), а сотрудник банка может выключить AI
(set_paused) без удаления ключа с сервера.
"""

import contextlib
import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app import config, database, notify
from app.models import AppState, LLMReservation, LLMUsage, LLMUsageCompany, LLMUsageModel

logger = logging.getLogger("app.llm_usage")

RESERVATION_TTL = timedelta(minutes=10)
ALERT_THRESHOLDS = (0.5, 0.8, 1.0)
PAUSE_KEY = "llm_paused"
PAUSE_CACHE_SECONDS = 5.0

_company: ContextVar[str | None] = ContextVar("llm_company", default=None)
_pause_memo: tuple[float, bool, tuple | None] = (0.0, False, None)


class BudgetExceeded(Exception):
    """Резерв не помещается в дневной лимит или долю компании: вызов не выполняется, агент откатывается к правилам.

    scope: total — исчерпан общий лимит дня, company — доля компании (у других компаний AI работает)."""

    def __init__(self, message: str, scope: str = "total"):
        super().__init__(message)
        self.scope = scope


@dataclass(frozen=True)
class Reservation:
    id: str
    day: date
    tokens: int
    cost: float
    model: str = ""
    company_id: str | None = None


@contextlib.contextmanager
def for_company(company_id: str | None):
    """Вызовы LLM внутри блока учитываются в доле компании (разбор, вопрос в чате)."""
    token = _company.set(company_id)
    try:
        yield
    finally:
        _company.reset(token)


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
            "limit": s["daily_token_limit"] or None, "cost_limit": s["daily_cost_limit"]}  # None — без лимита токенов


def spent_share() -> float:
    """Доля дневного лимита стоимости, уже потраченная и зарезервированная (0..1+)."""
    u = usage()
    return (u["cost"] + u["reserved_cost"]) / u["cost_limit"] if u["cost_limit"] else 1.0


def _ensure_day(db, day: date) -> None:
    db.execute(insert(LLMUsage).values(day=day).on_conflict_do_nothing(index_elements=[LLMUsage.day]))


def _ensure_company(db, day: date, company_id: str) -> None:
    db.execute(insert(LLMUsageCompany).values(day=day, company_id=company_id)
               .on_conflict_do_nothing(index_elements=[LLMUsageCompany.day, LLMUsageCompany.company_id]))


def _unreserve(db, day: date, tokens: int, cost, company_id: str | None) -> None:
    for table, where in ((LLMUsage, [LLMUsage.day == day]),
                         (LLMUsageCompany, [LLMUsageCompany.day == day, LLMUsageCompany.company_id == company_id])):
        if table is LLMUsageCompany and not company_id:
            continue
        db.execute(update(table).where(*where).values(
            reserved_tokens=func.greatest(table.reserved_tokens - tokens, 0),
            reserved_cost=func.greatest(table.reserved_cost - cost, 0)))


def sweep(db=None) -> int:
    """Снимает резервы старше RESERVATION_TTL. Возвращает их число."""
    if db is None:
        with database.session() as db:
            return sweep(db)
    stale = db.execute(delete(LLMReservation)
                       .where(LLMReservation.created_at < datetime.now(timezone.utc) - RESERVATION_TTL)
                       .returning(LLMReservation.day, LLMReservation.tokens, LLMReservation.cost,
                                  LLMReservation.company_id)).all()
    for day, tokens, cost, company_id in stale:
        _unreserve(db, day, tokens, cost, company_id)
    return len(stale)


class _Rejected(Exception):
    def __init__(self, scope: str):
        self.scope = scope


def reserve(model: str, prompt_chars: int, max_tokens: int) -> Reservation:
    """Резервирует оценку вызова в общем лимите и в доле компании или поднимает BudgetExceeded."""
    s = config.llm_settings()
    tokens, cost = estimate(model, prompt_chars, max_tokens)
    day, company_id = budget_day(), _company.get()
    share = config.llm_line_share(company_id)
    # Лимит токенов не задан (0) — ограничивают только рубли: условие по токенам всегда выполнено.
    token_limit = s["daily_token_limit"] or 10 ** 15
    sweep()  # своей транзакцией: отказ ниже откатил бы и снятие зависших резервов
    try:
        with database.session() as db:
            _ensure_day(db, day)
            # Сначала общий лимит: если исчерпан и он, причина для пользователя — лимит дня, а не доля компании.
            # Порядок блокировок (строка дня, затем компании) тот же, что при списании и снятии резерва.
            fits = db.execute(update(LLMUsage)
                .where(LLMUsage.day == day,
                       LLMUsage.tokens + LLMUsage.reserved_tokens + tokens <= token_limit,
                       LLMUsage.cost + LLMUsage.reserved_cost + cost <= s["daily_cost_limit"])
                .values(reserved_tokens=LLMUsage.reserved_tokens + tokens, reserved_cost=LLMUsage.reserved_cost + cost)
                .returning(LLMUsage.day)).first()
            if not fits:
                raise _Rejected("total")
            if company_id:
                _ensure_company(db, day, company_id)
                fits = db.execute(update(LLMUsageCompany)
                    .where(LLMUsageCompany.day == day, LLMUsageCompany.company_id == company_id,
                           LLMUsageCompany.tokens + LLMUsageCompany.reserved_tokens + tokens <= token_limit * share,
                           LLMUsageCompany.cost + LLMUsageCompany.reserved_cost + cost <= s["daily_cost_limit"] * share)
                    .values(reserved_tokens=LLMUsageCompany.reserved_tokens + tokens,
                            reserved_cost=LLMUsageCompany.reserved_cost + cost)
                    .returning(LLMUsageCompany.day)).first()
                if not fits:
                    raise _Rejected("company")  # откат транзакции снимает и резерв в общем лимите
            res = Reservation(f"rsv-{uuid.uuid4().hex}", day, tokens, cost, model, company_id)
            db.add(LLMReservation(id=res.id, day=day, company_id=company_id, tokens=tokens, cost=cost))
    except _Rejected as rejected:
        _count_rejection(day, company_id)
        if rejected.scope == "total":
            spent = usage(day)
            # «Исчерпан» — только если не помещается даже без идущих запросов: занятость резервами — не повод
            # тратить единственное за день оповещение 100%.
            if spent["cost"] + cost > spent["cost_limit"] or (spent["limit"] and spent["tokens"] + tokens > spent["limit"]):
                _alert(day, 1.0, "дневной лимит исчерпан — вызовы модели отклоняются, разборы строятся правилами")
            raise BudgetExceeded(f"Бюджет LLM: вызов (~{cost:.2f} ₽) не помещается в дневной лимит с учетом идущих запросов")
        raise BudgetExceeded(f"Бюджет LLM: исчерпана дневная доля компании ({share:.0%} лимита)", "company")
    return res


def _count_rejection(day: date, company_id: str | None) -> None:
    # Отдельная транзакция: отказ откатил резерв вместе с созданием строк дня, поэтому строки создаются заново.
    with database.session() as db:
        _ensure_day(db, day)
        db.execute(update(LLMUsage).where(LLMUsage.day == day).values(rejected=LLMUsage.rejected + 1))
        if company_id:
            _count(db, LLMUsageCompany, {"day": day, "company_id": company_id}, rejected=1)


def _settle(db, res: Reservation) -> None:
    """Снимает резерв, если его еще не снял sweep()."""
    gone = db.execute(delete(LLMReservation).where(LLMReservation.id == res.id).returning(LLMReservation.id)).first()
    if gone:
        _unreserve(db, res.day, res.tokens, res.cost, res.company_id)


def _count(db, table, key: dict, **inc) -> None:
    """Счетчики по модели или компании (llm_usage_models, llm_usage_companies)."""
    stmt = insert(table).values(**key, **inc)
    db.execute(stmt.on_conflict_do_update(index_elements=[getattr(table, k) for k in key],
        set_={k: getattr(table, k) + getattr(stmt.excluded, k) for k in inc}))


def commit(res: Reservation, tokens: int, cost: float) -> None:
    """Списывает фактические токены и стоимость вызова и освобождает его резерв."""
    tokens, cost = max(0, tokens), max(0.0, cost)
    with database.session() as db:
        _settle(db, res)
        after = db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(
            tokens=LLMUsage.tokens + tokens, cost=LLMUsage.cost + cost, calls=LLMUsage.calls + 1)
            .returning(LLMUsage.cost)).scalar_one()
        if res.model:
            _count(db, LLMUsageModel, {"day": res.day, "model": res.model}, tokens=tokens, cost=cost, calls=1)
        if res.company_id:
            _count(db, LLMUsageCompany, {"day": res.day, "company_id": res.company_id}, tokens=tokens, cost=cost, calls=1)
    limit = config.llm_settings()["daily_cost_limit"]
    for threshold in ALERT_THRESHOLDS:
        if limit and float(after) - cost < limit * threshold <= float(after):
            _alert(res.day, threshold, f"потрачено {float(after):.2f} из {limit:.0f} ₽")


def release(res: Reservation) -> None:
    """Вызов не состоялся или упал до ответа: резерв снимается, вызов учитывается как ошибка."""
    with database.session() as db:
        _settle(db, res)
        db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(
            calls=LLMUsage.calls + 1, errors=LLMUsage.errors + 1))
        if res.model:
            _count(db, LLMUsageModel, {"day": res.day, "model": res.model}, calls=1, errors=1)


def record_error(res: Reservation) -> None:
    """Ошибка после списания (ответ получен, но не годится): только счетчик ошибок."""
    with database.session() as db:
        db.execute(update(LLMUsage).where(LLMUsage.day == res.day).values(errors=LLMUsage.errors + 1))
        if res.model:
            _count(db, LLMUsageModel, {"day": res.day, "model": res.model}, errors=1)


def _alert(day: date, threshold: float, detail: str) -> None:
    """Оповещение о пороге расхода — один раз за день на порог, даже при нескольких воркерах."""
    key = f"llm_alert:{day.isoformat()}:{round(threshold * 100)}"
    with database.session() as db:
        first = db.execute(insert(AppState).values(key=key, payload={"at": datetime.now(timezone.utc).isoformat()})
                           .on_conflict_do_nothing(index_elements=[AppState.key]).returning(AppState.key)).first()
    if not first:
        return
    text = f"⚠️ <b>Альфа.Пульс: бюджет AI {round(threshold * 100)}%</b> за {day.isoformat()} — {detail}."
    logger.warning("llm budget alert %s%%: %s", round(threshold * 100), detail)
    notify.send_async(text)


def by_model(day: date | None = None) -> list[dict]:
    """Расход за день по моделям: фактическая цена за 1000 токенов рядом с оценкой резерва (config.LLM_PRICES)."""
    with database.session() as db:
        rows = db.scalars(select(LLMUsageModel).where(LLMUsageModel.day == (day or budget_day()))
                          .order_by(LLMUsageModel.cost.desc())).all()
    return [{"model": r.model, "tokens": r.tokens, "cost": round(float(r.cost), 3), "calls": r.calls, "errors": r.errors,
             "price_per_1k": round(float(r.cost) / r.tokens * 1000, 4) if r.tokens else None,
             "estimate_per_1k": config.llm_price_per_1k(r.model)} for r in rows]


def by_company(day: date | None = None, limit: int = 10) -> list[dict]:
    """Компании с наибольшим расходом за день и их отказы по доле — для сотрудников банка."""
    with database.session() as db:
        rows = db.scalars(select(LLMUsageCompany).where(LLMUsageCompany.day == (day or budget_day()))
                          .order_by(LLMUsageCompany.cost.desc()).limit(limit)).all()
    return [{"company_id": r.company_id, "cost": round(float(r.cost), 3), "calls": r.calls,
             "rejected_by_share": r.rejected} for r in rows]


def reserved_active() -> int:
    with database.session() as db:
        return db.scalar(select(func.count()).select_from(LLMReservation)) or 0


def paused() -> bool:
    """AI выключен сотрудником банка (app_state); кэш на несколько секунд — вызывается на каждом разборе.

    Кэш привязан к базе и к записям app_state этого процесса: переключение здесь видно сразу,
    в других воркерах — не позже PAUSE_CACHE_SECONDS."""
    global _pause_memo
    now, scope = time.monotonic(), (config.database_url(), config.database_schema(), database.state_epoch())
    if now - _pause_memo[0] > PAUSE_CACHE_SECONDS or _pause_memo[2] != scope:
        state = database.state(PAUSE_KEY) or {}
        _pause_memo = (now, bool(state.get("paused")), scope)
    return _pause_memo[1]


def pause_state() -> dict:
    return database.state(PAUSE_KEY) or {"paused": False}


def set_paused(value: bool, by: str) -> dict:
    """Выключатель AI для сотрудника банка: ключ остается на сервере, вызовы модели не выполняются."""
    global _pause_memo
    state = {"paused": value, "by": by, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with database.session() as db:
        database.set_state(PAUSE_KEY, state, db)
    _pause_memo = (0.0, False, None)  # следующий paused() перечитает состояние
    logger.warning("llm %s by %s", "paused" if value else "resumed", by)
    return state
