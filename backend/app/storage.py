"""Persistent insights, answers, feedback and events in PostgreSQL."""

import hashlib
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app import config, database, llm, llm_usage, ranking
from sqlalchemy import func, select
from app.companies import extra as company_extra
from app.models import AppState, Insight, Feedback, Answer, Event

# Меняется, когда правила меняют содержание карточек: старые перестают быть актуальным кэшем.
# quality-3: знак эффекта (направление курса, санкций, форм глаголов, «укрепление рубля» не про ставку) и поле effect.
CACHE_VERSION = "p0-quality-3"


VERSION_TTL = 5.0  # секунд; подписи источников меняются только при импорте
_version_memo: tuple[float, tuple, str] | None = None


def cache_version() -> str:
    # Source imports update these signatures; old insights remain available by id.
    global _version_memo
    scope = (config.database_url(), config.database_schema(), database.state_epoch())
    now = time.monotonic()
    if _version_memo and _version_memo[1] == scope and now - _version_memo[0] < VERSION_TTL:
        return _version_memo[2]
    with database.session() as db:
        rows = dict(db.execute(select(AppState.key, AppState.payload)
                               .where(AppState.key.in_(("profiles", "knowledge", "news_seed")))).all())
    profiles, knowledge, news_version = rows.get("profiles") or {}, rows.get("knowledge") or "", rows.get("news_seed") or ""
    version = hashlib.sha256(f"{CACHE_VERSION}:{profiles.get('signature')}:{knowledge}:{news_version}".encode()).hexdigest()
    _version_memo = (now, scope, version)
    return version


def reset_cache() -> None:
    global _version_memo
    _version_memo = None


def save_insight(insight: dict) -> None:
    version = cache_version()
    with database.session() as db:
        db.add(Insight(insight_id=insight["insight_id"], company_id=insight["company_id"],
                         news_id=insight["news_id"], role=insight["role"],
                         created_at=datetime.fromisoformat(insight["created_at"]), cache_version=version, payload=insight))


def get_insight(insight_id: str) -> dict | None:
    if not insight_id.replace("-", "").isalnum():
        return None
    with database.session() as db:
        row = db.get(Insight, insight_id)
        return row.payload if row else None


def _newest_first() -> tuple:
    # created_at хранится с точностью до секунды: при равном времени версия модели важнее быстрой на правилах.
    return (Insight.created_at.desc(), (Insight.payload["mode"].astext == "llm").desc(), Insight.insight_id.desc())


def _fresh(company_id: str) -> tuple:
    """Карточки, собранные до изменения сведений от компании, устарели."""
    since = company_extra.updated_at(company_id)
    return (Insight.created_at > since,) if since else ()


def cached_insight(company_id: str, role: str, news_id: str) -> dict | None:
    version = cache_version()
    with database.session() as db:
        return db.scalar(select(Insight.payload).where(Insight.company_id == company_id, Insight.role == role,
            Insight.news_id == news_id, Insight.cache_version == version, *_fresh(company_id))
            .order_by(*_newest_first()).limit(1))


def cached_insights(company_id: str, role: str, news_ids: list[str]) -> dict[str, dict]:
    """news_id -> последняя актуальная карточка (целиком); один запрос на список новостей."""
    if not news_ids:
        return {}
    version = cache_version()
    with database.session() as db:
        rows = db.execute(select(Insight.news_id, Insight.payload)
            .where(Insight.company_id == company_id, Insight.role == role, Insight.cache_version == version,
                   Insight.news_id.in_(news_ids), *_fresh(company_id))
            .order_by(Insight.news_id, *_newest_first())
            .distinct(Insight.news_id)).all()
    return dict(rows)


def llm_attempted(insight: dict) -> bool:
    """Модель уже отвечала для этой карточки, но ее черновик не прошел проверки — повтор даст то же самое.

    Такую карточку пересчитывает только «Пересчитать» (force_refresh), а не каждое открытие или конвейер.
    """
    return any(s.get("name") == "llm_compose" and s.get("status") == "ok" for s in insight.get("trace", []))


def cached_insight_refs(company_id: str, role: str, news_ids: list[str]) -> dict[str, tuple[str, str | None]]:
    """news_id -> (id, знак эффекта) последней актуальной карточки; один запрос на всю ленту (индекс insights_lookup_idx)."""
    if not news_ids:
        return {}
    version = cache_version()
    with database.session() as db:
        rows = db.execute(select(Insight.news_id, Insight.insight_id, Insight.payload["effect"].astext)
            .where(Insight.company_id == company_id, Insight.role == role, Insight.cache_version == version,
                   Insight.news_id.in_(news_ids), *_fresh(company_id))
            .order_by(Insight.news_id, *_newest_first())
            .distinct(Insight.news_id)).all()
    return {news_id: (insight_id, effect) for news_id, insight_id, effect in rows}


def _append(table: str, record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")} | record
    with database.session() as db:
        if table == "feedback":
            ranking.forget_feedback()  # новая оценка сразу меняет ленту
        if table in ("feedback", "answers"):
            model = Feedback if table == "feedback" else Answer
            db.add(model(insight_id=record["insight_id"], payload=record))
        elif table == "events":
            db.add(Event(kind=record["kind"], payload=record))
        else:
            raise ValueError("Unknown event table")


def _read(table: str) -> list[dict]:
    models = {"feedback": Feedback, "events": Event, "insights": Insight, "answers": Answer}
    if table not in models:
        raise ValueError("Unknown table")
    model = models[table]
    with database.session() as db:
        return list(db.scalars(select(model.payload).order_by(model.created_at)))


def add_feedback(fb: dict) -> None:
    _append("feedback", fb)


def save_answer(answer: dict) -> None:
    _append("answers", answer)


def log_event(kind: str, **data) -> None:
    _append("events", {"kind": kind} | data)


def count_events(kind: str, within_seconds: int, **match) -> int:
    """События вида kind за последние within_seconds с совпадающими полями (лимиты частоты запросов)."""
    since = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
    query = select(func.count()).select_from(Event).where(Event.kind == kind, Event.created_at >= since)
    for key, value in match.items():
        query = query.where(Event.payload[key].astext == str(value))
    with database.session() as db:
        return db.scalar(query) or 0


def metrics() -> dict:
    insights = _read("insights")
    feedback = _read("feedback")
    events = _read("events")

    checks: dict[str, list[bool]] = defaultdict(list)
    first_pass, claims_total, claims_linked, latency = 0, 0, 0, []
    modes = Counter()
    llm_tried = llm_fallback = 0
    for ins in insights:
        modes[ins["mode"]] += 1
        # Откат к правилам: модель вызывалась (шаг llm_compose в трассе), а итоговый разбор — на правилах.
        if any(s["name"] == "llm_compose" for s in ins["trace"]):
            llm_tried += 1
            llm_fallback += ins["mode"] == "rules"
        first_pass += int(ins["quality"]["attempts"] == 1 and ins["quality"]["passed"])
        for c in ins["quality"]["checks"]:
            checks[c["name"]].append(c["passed"])
        for sec in ("why_important", "risks", "opportunities", "actions"):
            for cl in ins[sec]:
                claims_total += 1
                claims_linked += int(bool(cl["source_ids"]))
        total = next((s.get("output", {}).get("total_duration_ms") for s in ins["trace"]
                      if s["stage"] == "finalize" and s.get("output")), None)
        latency.append(total if total is not None else sum(s["duration_ms"] for s in ins["trace"]))

    ratings = Counter(f["rating"] for f in feedback)
    by_section = defaultdict(Counter)
    for f in feedback:
        by_section[f.get("section") or "card"][f["rating"]] += 1
    usage = llm_usage.usage()
    feed_views = sum(1 for e in events if e["kind"] == "feed_view")
    opens = sum(1 for e in events if e["kind"] == "insight_open")
    n = len(insights) or 1
    return {
        "content": {
            "insights": len(insights),
            "first_pass_rate": round(first_pass / n, 3),
            "claims_with_sources": round(claims_linked / (claims_total or 1), 3),
            "checks_pass_rate": {k: round(sum(v) / len(v), 3) for k, v in checks.items()},
        },
        "personalization": {
            "feed_views": feed_views,
            "insight_opens": opens,
            "open_rate": round(opens / feed_views, 3) if feed_views else None,
            "useful_rate": round(ratings[1] / (ratings[1] + ratings[-1]), 3) if feedback else None,
            "feedback": {"up": ratings[1], "down": ratings[-1]},
            "by_section": {k: {"up": v[1], "down": v[-1]} for k, v in by_section.items()},
        },
        "ai": {
            "modes": dict(modes),
            "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else None,
            "llm_usage": usage,
            "llm_connected": llm.available(),
            "reserved_cost": usage["reserved_cost"],
            "rejected_by_budget": usage["rejected_by_budget"],
            "llm_by_model": llm_usage.by_model(),
            "llm_by_company": llm_usage.by_company(),
            "llm_paused": llm_usage.pause_state(),
            "fallback_rate": round(llm_fallback / llm_tried, 3) if llm_tried else None,
        },
        "recent_feedback": [f for f in feedback[-10:] if f.get("comment")],
    }
