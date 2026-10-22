"""Хранилище новостей: демо-лента, RSS и добавленные пользователем материалы.

Каждая новость классифицируется при добавлении. Дубликаты (почти одинаковый
текст из разных источников) объединяются: остается одна запись со списком
источников. Записи и изменения хранятся транзакционно в PostgreSQL.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import database
from sqlalchemy import select, func
from app.models import News
from app.news.classifier import classify, tokenize

SEED_FILE = Path(__file__).with_name("seed_news.json")
DUPLICATE_THRESHOLD = 0.55

_lock = threading.Lock()


def _shingles(text: str, n: int = 3) -> set[str]:
    words = tokenize(text)
    return {" ".join(words[i:i + n]) for i in range(max(len(words) - n + 1, 1))}


def similarity(a: str, b: str) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def make_item(title: str, text: str, source: str, url: str | None = None,
              published_at: str | None = None, kind: str = "external", news_id: str | None = None) -> dict:
    from app.agent.evidence import safe_text
    original = (title.strip(), text.strip())
    title, text = safe_text(original[0]), safe_text(original[1])
    digest = hashlib.sha1(f"{title}|{text[:400]}".encode()).hexdigest()[:12]
    cls = classify(title, text)
    return {
        "news_id": news_id or f"n-{digest}",
        "title": title,
        "text": text,
        "lead": (cls.key_sentences[0] if cls.key_sentences else text[:280]),
        "source": source,
        "url": url,
        "kind": kind,  # seed | rss | user | external
        "published_at": published_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "classification": cls.as_dict(),
        "duplicates": [],
        "content_filtered": original != (title, text),
    }


def _load(db=None) -> dict[str, dict]:
    if db is None:
        with database.session() as db:
            return _load(db)
    db.execute(select(func.pg_advisory_xact_lock(72810403)))
    version = hashlib.sha256(SEED_FILE.read_bytes() + Path(__file__).with_name("classifier.py").read_bytes()
                             + Path(__file__).with_name("taxonomy.py").read_bytes()).hexdigest()
    if database.state("news_seed", db) != version:
        for s in json.loads(SEED_FILE.read_text(encoding="utf-8"))["items"]:
            it = make_item(s["title"], s["text"], s["source"], None, s["published_at"], "seed", s["news_id"])
            previous = db.get(News, it["news_id"])
            if previous:
                it["duplicates"] = previous.payload.get("duplicates") or []
                previous.payload = it
                previous.published_at = datetime.fromisoformat(it["published_at"])
            else:
                db.add(News(news_id=it["news_id"], published_at=datetime.fromisoformat(it["published_at"]),
                              kind=it["kind"], payload=it))
        db.flush()
        # Reclassify all previously stored records when the classifier changes.
        for record in db.scalars(select(News)):
            previous = record.payload
            updated = make_item(previous["title"], previous["text"], previous["source"], previous.get("url"),
                                previous["published_at"], previous["kind"], previous["news_id"])
            updated.update(added_at=previous["added_at"], duplicates=previous.get("duplicates") or [],
                           content_filtered=previous.get("content_filtered", False) or updated["content_filtered"])
            record.payload = updated
        db.flush()
        database.set_state("news_seed", version, db)
    return {p["news_id"]: p for p in db.scalars(select(News.payload))}


def reset_cache() -> None:
    """Compatibility hook: news reads always use committed PostgreSQL records."""


def all_items() -> list[dict]:
    with _lock:
        return sorted(_load().values(), key=lambda i: i["published_at"], reverse=True)


def get(news_id: str) -> dict | None:
    with _lock:
        return _load().get(news_id)


def add(item: dict) -> tuple[dict, bool]:
    """Добавляет новость. Возвращает (запись, создана_ли_новая). Дубликат приклеивается к оригиналу."""
    with _lock, database.session() as db:
        items = _load(db)
        if item["news_id"] in items:
            return items[item["news_id"]], False
        probe = f"{item['title']} {item['text'][:600]}"
        for existing in items.values():
            if similarity(probe, f"{existing['title']} {existing['text'][:600]}") >= DUPLICATE_THRESHOLD:
                existing = {**existing, "duplicates": existing["duplicates"] + [
                    {"source": item["source"], "url": item["url"], "title": item["title"]}]}
                db.get(News, existing["news_id"]).payload = existing
                return existing, False
        db.add(News(news_id=item["news_id"], published_at=datetime.fromisoformat(item["published_at"]),
                      kind=item["kind"], payload=item))
        return item, True
