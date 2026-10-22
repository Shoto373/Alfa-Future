"""Persistent insights, answers, feedback and events in PostgreSQL."""

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone

from app import database
from app.agent import llm
from sqlalchemy import select
from app.models import Insight, Feedback, Answer, Event

CACHE_VERSION = "p0-quality-2"


def cache_version() -> str:
    # Source imports update these signatures; old insights remain available by id.
    with database.session() as db:
        profiles = database.state("profiles", db) or {}
        knowledge = database.state("knowledge", db) or ""
        news_version = database.state("news_seed", db) or ""
    return hashlib.sha256(f"{CACHE_VERSION}:{profiles.get('signature')}:{knowledge}:{news_version}".encode()).hexdigest()


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


def cached_insight(company_id: str, role: str, news_id: str) -> dict | None:
    version = cache_version()
    with database.session() as db:
        return db.scalar(select(Insight.payload).where(Insight.company_id == company_id, Insight.role == role,
            Insight.news_id == news_id, Insight.cache_version == version)
            .order_by(Insight.created_at.desc(), Insight.insight_id.desc()).limit(1))


def _append(table: str, record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")} | record
    with database.session() as db:
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


def metrics() -> dict:
    insights = _read("insights")
    feedback = _read("feedback")
    events = _read("events")

    checks: dict[str, list[bool]] = defaultdict(list)
    first_pass, claims_total, claims_linked, latency = 0, 0, 0, []
    modes = Counter()
    for ins in insights:
        modes[ins["mode"]] += 1
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
            "llm_usage": llm.usage(),
            "llm_connected": llm.available(),
        },
        "recent_feedback": [f for f in feedback[-10:] if f.get("comment")],
    }
