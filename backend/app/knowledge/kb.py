"""База знаний Альфа-Банка: тезисы аналитических материалов и поиск по ним.

Поиск — BM25 по тексту тезиса плюс бонусы за совпадение тем и отраслей.
Свежие материалы получают приоритет; устаревшие (stale) — штраф и пометку.
Каждый результат несет doc_id и страницу, чтобы вывод можно было проверить.
"""

import json
import math
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.news.classifier import tokenize

KB_FILE = Path(__file__).with_name("bank_analytics.json")
REFERENCE_DATE = date(2026, 10, 21)


@lru_cache(maxsize=1)
def _kb() -> dict:
    data = json.loads(KB_FILE.read_text(encoding="utf-8"))
    docs = {d["doc_id"]: d for d in data["documents"]}
    theses = []
    for t in data["theses"]:
        doc = docs[t["doc_id"]]
        tokens = [w[:5] for w in tokenize(t["text"])]  # грубый стемминг: первые 5 букв
        theses.append({**t, "doc_title": doc["title"], "doc_date": doc["date"], "stale": bool(doc.get("stale") or t.get("stale")),
                       "_tokens": tokens})
    n = len(theses)
    df = Counter(w for t in theses for w in set(t["_tokens"]))
    idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
    avg = sum(len(t["_tokens"]) for t in theses) / max(n, 1)
    return {"documents": docs, "theses": theses, "products": data["products"], "idf": idf, "avg": avg}


def documents() -> list[dict]:
    return list(_kb()["documents"].values())


def document(doc_id: str) -> dict | None:
    return _kb()["documents"].get(doc_id)


def thesis(thesis_id: str) -> dict | None:
    return next((_public(t) for t in _kb()["theses"] if t["id"] == thesis_id), None)


def products() -> list[dict]:
    return _kb()["products"]


def _public(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}


def _bm25(query: list[str], t: dict, kb: dict, k1: float = 1.4, b: float = 0.7) -> float:
    tf = Counter(t["_tokens"])
    length = len(t["_tokens"])
    score = 0.0
    for w in set(query):
        if w in tf:
            f = tf[w]
            score += kb["idf"].get(w, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * length / kb["avg"]))
    return score


def _recency(doc_date: str) -> float:
    age = (REFERENCE_DATE - date.fromisoformat(doc_date)).days
    return max(0.3, 1.0 - age / 365)


def search(query: str = "", topics: list[str] | None = None, sectors: list[str] | None = None,
           limit: int = 6, include_stale: bool = False) -> list[dict]:
    kb = _kb()
    q = [w[:5] for w in tokenize(query)]
    topics, sectors = set(topics or []), set(sectors or [])
    results = []
    for t in kb["theses"]:
        if t["stale"] and not include_stale:
            continue
        lexical = _bm25(q, t, kb) if q else 0.0
        topic_hit = len(topics & set(t["topics"]))
        sector_hit = len(sectors & set(t["sectors"]))
        score = lexical + 2.5 * topic_hit + 1.5 * sector_hit
        if score <= 0:
            continue
        score *= _recency(t["doc_date"])
        if t["stale"]:
            score *= 0.4
        results.append({**_public(t), "score": round(score, 3), "match": {"topics": sorted(topics & set(t["topics"])),
                                                                          "sectors": sorted(sectors & set(t["sectors"]))}})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def latest_forecasts(topic: str) -> list[dict]:
    """Прогнозы по теме во всех документах — для проверки противоречий между материалами."""
    items = [_public(t) for t in _kb()["theses"] if topic in t["topics"] and t.get("stance") == "forecast"]
    return sorted(items, key=lambda t: t["doc_date"], reverse=True)
