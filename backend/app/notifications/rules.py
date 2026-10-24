"""Что и когда присылать (SPR4-04): утренняя сводка и мгновенные алерты — без модели.

Сводка — 3–5 главных событий ленты с заголовком разбора (если разбор уже готов) или новости.
Алерт — событие с оценкой не ниже порога пользователя или событие у контрагента. Антиспам: не больше
alerts_per_day алертов в сутки, один алерт на сюжет (несколько заметок об одном событии — одно сообщение),
в тихие часы алерты не отправляются (важное попадет в утреннюю сводку).
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import monitoring, ranking, storage
from app.news import store

DIGEST_MIN, DIGEST_MAX = 3, 5
DIGEST_LATE = timedelta(hours=4)       # позже — сводку за этот день не шлем
ALERT_WINDOW = timedelta(hours=24)       # алерт — только о свежем событии
COUNTERPARTY_MIN_STRENGTH = 0.5


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def _clock(text: str) -> time:
    hours, minutes = (int(x) for x in text.split(":"))
    return time(hours, minutes)


def local(now: datetime, settings: dict) -> datetime:
    return now.astimezone(zone(settings["timezone"]))


def quiet(settings: dict, now: datetime) -> bool:
    """Тихие часы в часовом поясе пользователя; интервал может переходить через полночь (22:00–08:00)."""
    t = local(now, settings).time()
    start, end = _clock(settings["quiet_from"]), _clock(settings["quiet_to"])
    if start == end:
        return False
    return start <= t < end if start < end else (t >= start or t < end)


def digest_key(user_id: str, company_id: str, now: datetime, settings: dict) -> str | None:
    """Ключ сегодняшней сводки, если ее время наступило (None — еще рано или сводки выключены)."""
    if not settings["digest"]:
        return None
    today = local(now, settings)
    start = datetime.combine(today.date(), _clock(settings["digest_time"]), today.tzinfo)
    if not start <= today < start + DIGEST_LATE:
        return None
    return f"digest:{user_id}:{company_id}:{today.date().isoformat()}"


def _topics_ok(news: dict, topics: list[str]) -> bool:
    return not topics or any(t["topic"] in topics for t in news["classification"]["topics"])


def _story(news_id: str, known: str | None = None) -> str:
    """Сюжет события: заметки об одном событии из разных источников дают один алерт."""
    return known or (store.get(news_id) or {}).get("story_id") or news_id


def _item(row: dict, insight: dict | None, source: str) -> dict:
    news = row["news"]
    return {"news_id": news["news_id"], "title": news["title"], "score": row["relevance"]["score"],
            "headline": (insight or {}).get("headline") or news["title"], "story_id": _story(news["news_id"], row.get("story_id")),
            "insight_id": (insight or {}).get("insight_id"), "source": source}


def digest_items(company_id: str, role: str, settings: dict) -> list[dict]:
    """3–5 событий для сводки; меньше трех значимых — сводки нет (пустое письмо хуже, чем никакого)."""
    # Порог релевантности уже применен лентой (MIN_FEED_SCORE): в сводку — ее верх по темам пользователя.
    rows = [r for r in ranking.company_feed(company_id, role) if _topics_ok(r["news"], settings["topics"])][:DIGEST_MAX]
    if len(rows) < DIGEST_MIN:
        return []
    insights = storage.cached_insights(company_id, role, [r["news"]["news_id"] for r in rows])
    return [_item(r, insights.get(r["news"]["news_id"]), "feed") for r in rows]


def _fresh(published_at: str, now: datetime) -> bool:
    return published_at >= (now - ALERT_WINDOW).isoformat()


def alert_items(company_id: str, role: str, settings: dict, now: datetime) -> list[dict]:
    """Кандидаты в алерты, по одному на сюжет, самые сильные первыми."""
    rows = [r for r in ranking.company_feed(company_id, role)
            if r["relevance"]["score"] >= settings["threshold"] and _topics_ok(r["news"], settings["topics"])
            and _fresh(r["news"]["published_at"], now)]
    insights = storage.cached_insights(company_id, role, [r["news"]["news_id"] for r in rows])
    items = [_item(r, insights.get(r["news"]["news_id"]), "feed") for r in rows]
    if settings["counterparties"]:
        for a in monitoring.alerts(company_id):
            if a["strength"] >= COUNTERPARTY_MIN_STRENGTH and _fresh(a["published_at"], now):
                items.append({"news_id": a["news_id"], "title": a["title"], "score": round(a["strength"] * 100),
                              "headline": f"{a['title']} — {a['chain']}", "story_id": _story(a["news_id"]),
                              "insight_id": None, "source": "counterparty"})
    out, seen = [], set()
    for item in sorted(items, key=lambda i: i["score"], reverse=True):
        if item["story_id"] not in seen:
            seen.add(item["story_id"])
            out.append(item)
    return out
