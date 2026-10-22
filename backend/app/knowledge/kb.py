"""База знаний Альфа-Банка: тезисы аналитических материалов и поиск по ним.

Поиск — BM25 по тексту тезиса плюс бонусы за совпадение тем и отраслей.
Свежие материалы получают приоритет; устаревшие (stale) — штраф и пометку.
Каждый результат несет doc_id и страницу, чтобы вывод можно было проверить.
"""

import json
import hashlib
import math
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.news.classifier import tokenize
from app import config, database
from sqlalchemy import select, func
from app.models import BankDocument, BankThesis, BankProduct

KB_FILE = Path(__file__).with_name("bank_analytics.json")


def _kb() -> dict:
    return _index(config.database_url(), config.database_schema(), hashlib.sha256(KB_FILE.read_bytes()).hexdigest())


@lru_cache(maxsize=2)
def _index(url: str, schema: str, signature: str) -> dict:
    source = json.loads(KB_FILE.read_text(encoding="utf-8"))
    with database.session() as db:
        db.execute(select(func.pg_advisory_xact_lock(72810404)))
        if database.state("knowledge", db) != signature:
            for d in source["documents"]:
                db.merge(BankDocument(doc_id=d["doc_id"], payload=d))
            db.flush()  # Documents precede thesis foreign keys.
            for t in source["theses"]:
                db.merge(BankThesis(thesis_id=t["id"], doc_id=t["doc_id"], page=t["page"], payload=t))
            for p in source["products"]:
                db.merge(BankProduct(product_id=p["id"], payload=p))
            db.flush()
            database.set_state("knowledge", signature, db)
        data = {"documents": list(db.scalars(select(BankDocument.payload).order_by(BankDocument.doc_id))),
                "theses": list(db.scalars(select(BankThesis.payload).order_by(BankThesis.thesis_id))),
                "products": list(db.scalars(select(BankProduct.payload).order_by(BankProduct.product_id)))}
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
    parsed = date.fromisoformat(doc_date + "-01" if len(doc_date) == 7 else doc_date)
    age = max(0, (date.today() - parsed).days)
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
        # Sector overlap alone does not make a bank thesis relevant to an event.
        if topics and not topic_hit:
            continue
        meaningful = {w for w in q if len(w) >= 5 and w not in {"компа", "банка", "альфа", "новос", "данны"}}
        if topics and len(q) > 5 and len(meaningful & set(t["_tokens"])) < 2:
            continue
        if not topics and (lexical < 2 or len(meaningful & set(t["_tokens"])) < 2):
            continue
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
