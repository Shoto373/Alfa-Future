"""Реестр источников и сбор новостей (SPR3-02).

Источники описаны в конфигурации (config.news_sources): вес доверия, лицензия, частота опроса.
Сбор одинаков для всех: уже известные записи пропускаются до классификации, новые дополняются
(полный текст, если лицензия позволяет), классифицируются и сохраняются; ошибка одного источника
не прерывает сбор. Счетчики, ошибки и задержки по источнику — в app_state (метрики и /meta).
"""

import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from app import config, database
from app.news import semantic, store
from app.news.parser import FetchError
from app.news.sources.base import Adapter
from app.news.sources.licensed import LicensedFeedAdapter
from app.news.sources.manual import ManualAdapter
from app.news.sources.rss import RssAdapter

logger = logging.getLogger("app.news.sources")

STATS_KEY = "news_sources"
KINDS: dict[str, type[Adapter]] = {"rss": RssAdapter, "licensed": LicensedFeedAdapter, "manual": ManualAdapter}
ITEM_KIND = {"rss": "rss", "licensed": "external", "manual": "external"}
# Повторно забираем записи за сутки до последнего успешного опроса: ленты публикуют задним числом.
SINCE_OVERLAP = timedelta(days=1)
SOURCE_ERRORS = (FetchError, httpx.HTTPError, ET.ParseError, OSError, ValueError, KeyError)


def adapters() -> list[Adapter]:
    out = []
    for s in config.news_sources():
        known = {"id", "kind", "name", "url", "trust", "license", "interval_minutes"}
        out.append(KINDS[s["kind"]](id=s["id"], name=s["name"], kind=s["kind"], url=s.get("url", ""),
                                    trust=float(s["trust"]), license=s["license"],
                                    interval_minutes=int(s["interval_minutes"]),
                                    extra={k: v for k, v in s.items() if k not in known}))
    return out


def stats() -> dict:
    """Состояние источников: последний опрос, ошибка, задержка, счетчики за все время."""
    return database.state(STATS_KEY) or {}


def _due(stat: dict, adapter: Adapter, now: datetime) -> bool:
    try:
        last = datetime.fromisoformat(stat["last_attempt"])
    except (KeyError, TypeError, ValueError):
        return True
    return now - last >= timedelta(minutes=adapter.interval_minutes) - timedelta(seconds=30)


def _since(stat: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(stat["last_ok"]) - SINCE_OVERLAP
    except (KeyError, TypeError, ValueError):
        return None


def _lag_seconds(item: dict) -> float | None:
    """Время от публикации до появления в ленте (news_lag_seconds)."""
    try:
        published = datetime.fromisoformat(item["published_at"])
        added = datetime.fromisoformat(item["added_at"])
    except (KeyError, ValueError):
        return None
    published = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
    return max(0.0, (added - published).total_seconds())


def _ingest(adapter: Adapter, since: datetime | None, entry: dict) -> None:
    raws = adapter.fetch(since)
    entry["fetched"] = len(raws)
    fresh = [r for r in raws if not store.known(r.title, r.text)]
    entry["duplicates"] += len(raws) - len(fresh)
    # Дополнение (полный текст статьи) — параллельно и только для новых записей.
    with ThreadPoolExecutor(max_workers=6) as pool:
        enriched = list(pool.map(adapter.enrich, fresh))
    entry["full_text"] += sum(e is not r for e, r in zip(enriched, fresh))
    semantic.prime([store.clean(r.title, r.text) for r in enriched])
    for raw in enriched:
        item = store.make_item(raw.title, raw.text, adapter.name, raw.url, raw.published_at,
                               ITEM_KIND[adapter.kind], llm=True)
        item.update(source_id=adapter.id, trust=adapter.trust, license=adapter.license)
        if not item["classification"]["topics"]:
            entry["skipped"] += 1  # не относится к бизнес-темам таксономии
            continue
        saved, created = store.add(item)
        entry["added" if created else "duplicates"] += 1
        lag = _lag_seconds(saved) if created else None
        if lag is not None:
            entry["lag_seconds"] = max(entry.get("lag_seconds") or 0.0, lag)


def collect(force: bool = False, now: datetime | None = None) -> dict:
    """Опрос источников, у которых подошел срок (force — всех). Отчет совместим с прежним parser.refresh."""
    now = now or datetime.now(timezone.utc)
    saved = stats()
    report = {"added": 0, "duplicates": 0, "skipped": 0, "full_text": 0, "sources": []}
    for adapter in adapters():
        stat = dict(saved.get(adapter.id) or {})
        if not force and not _due(stat, adapter, now):
            continue
        entry = {"id": adapter.id, "name": adapter.name, "kind": adapter.kind, "url": adapter.url, "fetched": 0,
                 "added": 0, "duplicates": 0, "skipped": 0, "full_text": 0, "error": None}
        try:
            _ingest(adapter, _since(stat), entry)
        except SOURCE_ERRORS as exc:
            entry["error"] = str(exc)[:200] or type(exc).__name__
            logger.warning("news source %s failed: %s", adapter.name, type(exc).__name__)
        health = adapter.health()
        stat.update(name=adapter.name, kind=adapter.kind, trust=adapter.trust, license=adapter.license,
                    last_attempt=now.isoformat(timespec="seconds"), last_error=entry["error"],
                    latency_ms=health["latency_ms"], fetched=entry["fetched"],
                    added_total=stat.get("added_total", 0) + entry["added"],
                    errors_total=stat.get("errors_total", 0) + (entry["error"] is not None),
                    lag_seconds=entry.get("lag_seconds", stat.get("lag_seconds")))
        if entry["error"] is None:
            stat["last_ok"] = health["last_ok"]
        saved[adapter.id] = stat
        for key in ("added", "duplicates", "skipped", "full_text"):
            report[key] += entry[key]
        report["sources"].append(entry)
    with database.session() as db:
        database.set_state(STATS_KEY, {**(database.state(STATS_KEY, db) or {}), **saved}, db)
    return report
