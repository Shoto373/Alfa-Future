"""База знаний Альфа-Банка: тезисы аналитических материалов и поиск по ним.

Поиск гибридный: BM25 по словам тезиса плюс смысловая близость (embedding-модель,
app.embeddings) и бонусы за совпадение тем и отраслей. Смысл помогает найти тезис,
сформулированный другими словами; без модели остается только BM25.
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
import numpy as np

from app import config, database, embeddings, vector_store, vectors
from sqlalchemy import select, func
from app.models import BankDocument, BankThesis, BankProduct

KB_FILE = Path(__file__).with_name("bank_analytics.json")


_signature_memo: tuple[tuple[int, int], str] | None = None


def _signature() -> str:
    """Подпись файла базы знаний; пересчитывается только при изменении файла."""
    global _signature_memo
    st = KB_FILE.stat()
    key = (st.st_mtime_ns, st.st_size)
    if _signature_memo is None or _signature_memo[0] != key:
        _signature_memo = (key, hashlib.sha256(KB_FILE.read_bytes()).hexdigest())
    return _signature_memo[1]


def _kb() -> dict:
    return _index(config.database_url(), config.database_schema(), _signature())


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
                       "_tokens": tokens, "_tf": Counter(tokens), "_token_set": set(tokens)})
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
    tf = t["_tf"]
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


DENSE_WEIGHT = 6.0    # вклад смысловой близости в оценку (сопоставим с BM25 и бонусом темы)
DENSE_FLOOR = 0.30    # ниже этого сходство считается шумом
# Тезис проходит фильтр по смыслу, даже если общих слов мало: среди тезисов нужной темы
# это лучший по смыслу и близкие к нему. Абсолютный порог не годится — у короткого
# заголовка и длинного тезиса сходство в целом ниже (подобрано на тезисах кейса).
DENSE_PASS_MIN = 0.35
DENSE_PASS_GAP = 0.08


@lru_cache(maxsize=4)
def _thesis_vectors(signature: str, model: str) -> tuple[list[str], np.ndarray] | None:
    """Матрица векторов тезисов. Векторы хранятся в коллекции thesis векторного хранилища."""
    theses = _kb()["theses"]
    ids = [t["id"] for t in theses]
    stored = vectors.sync(vector_store.THESIS, [(t["id"], t["text"], {
        "doc_id": t["doc_id"], "topics": t["topics"], "sectors": t["sectors"], "stale": t["stale"]}) for t in theses],
        prune_missing=True)
    if stored is None:  # хранилище недоступно — векторы только в памяти
        found = embeddings.embed([t["text"] for t in theses])
        if found is None:
            return None
        stored = dict(zip(ids, embeddings.as_matrix(found)))
    return ids, np.stack([stored[i] for i in ids]) if ids else np.zeros((0, 0), dtype=np.float32)


def _dense(query: str) -> dict[str, float] | None:
    """Смысловое сходство запроса с каждым тезисом; None — модель недоступна."""
    if not query.strip():
        return None
    model = embeddings.signature()
    if model == "emb:off":
        return None
    index = _thesis_vectors(_signature(), model)
    qv = embeddings.embed([query[:600]]) if index else None
    if qv is None:
        return None
    ids, matrix = index
    return dict(zip(ids, (matrix @ embeddings.as_matrix(qv)[0]).tolist())) if len(ids) else {}


def warm() -> int:
    """Старт сервиса: импорт базы знаний и векторы тезисов."""
    _kb()
    model = embeddings.signature()
    if model != "emb:off":
        _thesis_vectors(_signature(), model)
    return len(_kb()["theses"])


def search(query: str = "", topics: list[str] | None = None, sectors: list[str] | None = None,
           limit: int = 6, include_stale: bool = False) -> list[dict]:
    kb = _kb()
    q = [w[:5] for w in tokenize(query)]
    topics, sectors = set(topics or []), set(sectors or [])
    dense = _dense(query) or {}
    sims = {t["id"]: dense[t["id"]] for t in kb["theses"]
            if t["id"] in dense and (not topics or topics & set(t["topics"]))}
    pass_at = max(DENSE_PASS_MIN, max(sims.values(), default=0.0) - DENSE_PASS_GAP)
    meaningful = {w for w in q if len(w) >= 5 and w not in {"компа", "банка", "альфа", "новос", "данны"}}
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
        sim = sims.get(t["id"], 0.0)
        by_meaning = sim >= pass_at
        if topics and len(q) > 5 and len(meaningful & t["_token_set"]) < 2 and not by_meaning:
            continue
        if not topics and (lexical < 2 or len(meaningful & t["_token_set"]) < 2) and not by_meaning:
            continue
        score = lexical + DENSE_WEIGHT * max(0.0, sim - DENSE_FLOOR) + 2.5 * topic_hit + 1.5 * sector_hit
        if score <= 0:
            continue
        score *= _recency(t["doc_date"])
        if t["stale"]:
            score *= 0.4
        results.append({**_public(t), "score": round(score, 3), "match": {"topics": sorted(topics & set(t["topics"])),
                                                                          "sectors": sorted(sectors & set(t["sectors"])),
                                                                          "semantic": round(sim, 3)}})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def latest_forecasts(topic: str) -> list[dict]:
    """Прогнозы по теме во всех документах — для проверки противоречий между материалами."""
    items = [_public(t) for t in _kb()["theses"] if topic in t["topics"] and t.get("stance") == "forecast"]
    return sorted(items, key=lambda t: t["doc_date"], reverse=True)
