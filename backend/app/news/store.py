"""Хранилище новостей: демо-лента, RSS и добавленные пользователем материалы.

Каждая новость классифицируется при добавлении. Дубликаты (почти одинаковый
текст из разных источников) объединяются: остается одна запись со списком
источников. Хранение — JSON в RUNTIME_DIR, без внешней БД.
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app.news.classifier import classify, tokenize

SEED_FILE = Path(__file__).with_name("seed_news.json")
DUPLICATE_THRESHOLD = 0.55

_lock = threading.Lock()
_items: dict[str, dict] | None = None


def _store_path() -> Path:
    return config.runtime_dir() / "news.json"


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
    title, text = title.strip(), text.strip()
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
    }


def _load() -> dict[str, dict]:
    global _items
    if _items is not None:
        return _items
    items: dict[str, dict] = {}
    path = _store_path()
    if path.exists():
        try:
            for it in json.loads(path.read_text(encoding="utf-8")):
                items[it["news_id"]] = it
        except (OSError, ValueError, KeyError):
            items = {}
    if not any(i["kind"] == "seed" for i in items.values()):
        seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        for s in seed["items"]:
            it = make_item(s["title"], s["text"], s["source"], None, s["published_at"], "seed", s["news_id"])
            items[it["news_id"]] = it
    _items = items
    _save()
    return _items


def _save() -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(list((_items or {}).values()), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def reset_cache() -> None:
    global _items
    with _lock:
        _items = None


def all_items() -> list[dict]:
    with _lock:
        return sorted(_load().values(), key=lambda i: i["published_at"], reverse=True)


def get(news_id: str) -> dict | None:
    with _lock:
        return _load().get(news_id)


def add(item: dict) -> tuple[dict, bool]:
    """Добавляет новость. Возвращает (запись, создана_ли_новая). Дубликат приклеивается к оригиналу."""
    with _lock:
        items = _load()
        if item["news_id"] in items:
            return items[item["news_id"]], False
        probe = f"{item['title']} {item['text'][:600]}"
        for existing in items.values():
            if similarity(probe, f"{existing['title']} {existing['text'][:600]}") >= DUPLICATE_THRESHOLD:
                existing["duplicates"].append({"source": item["source"], "url": item["url"], "title": item["title"]})
                _save()
                return existing, False
        items[item["news_id"]] = item
        _save()
        return item, True
