"""Векторное хранилище: PostgreSQL + pgvector (таблица vector_items).

Коллекции:
- cache  — любой текст, который уже считала модель (item_id = хэш текста). После
  рестарта векторы берутся отсюда, модель не пересчитывает их заново;
- news   — заголовки новостей с датой и темами: поиск предыдущих событий сюжета;
- thesis — тезисы аналитики банка с темами и отраслями: смысловая часть RAG.

Поиск ближайших — `nearest()`: косинусное расстояние pgvector по HNSW-индексу
с фильтрами по payload. Хранилище — ускоритель и общий источник векторов для
процессов; любой сбой БД здесь не ломает анализ: вызывающий код откатывается
на векторы в памяти или на словари.
"""

import hashlib
import logging

import numpy as np
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.exc import SQLAlchemyError

from app import config, database, embeddings
from app.models import VECTOR_DIM, VectorItem

logger = logging.getLogger("app.vectors")

CACHE, NEWS, THESIS = "cache", "news", "thesis"
CHUNK = 500  # строк в одном INSERT


def text_hash(text_: str) -> str:
    return hashlib.sha1(text_.encode()).hexdigest()


def enabled() -> bool:
    return config.embeddings_settings()["persist"]


def _fits(vec) -> bool:
    return getattr(vec, "shape", (len(vec),))[-1] == VECTOR_DIM


def load(collection: str, model: str, ids: list[str] | None = None) -> dict[str, tuple[str, np.ndarray, dict]]:
    """item_id -> (text_hash, вектор, payload); ids=None — вся коллекция модели."""
    if not enabled():
        return {}
    stmt = select(VectorItem.item_id, VectorItem.text_hash, VectorItem.embedding, VectorItem.payload).where(
        VectorItem.collection == collection, VectorItem.model == model)
    out: dict[str, tuple[str, np.ndarray, dict]] = {}
    try:
        with database.session() as db:
            if ids is None:
                rows = db.execute(stmt).all()
            else:
                rows = [r for i in range(0, len(ids), CHUNK)
                        for r in db.execute(stmt.where(VectorItem.item_id.in_(ids[i:i + CHUNK]))).all()]
    except SQLAlchemyError:
        logger.exception("vector store read failed collection=%s", collection)
        return {}
    for item_id, digest, vec, payload in rows:
        out[item_id] = (digest, np.asarray(vec, dtype=np.float32), payload)
    return out


def save(collection: str, model: str, rows: list[tuple[str, str, np.ndarray, dict]]) -> None:
    """Upsert (item_id, text_hash, вектор, payload). Векторы другой размерности не сохраняются."""
    rows = [r for r in rows if _fits(r[2])]
    if not enabled() or not rows:
        return
    try:
        with database.session() as db:
            for i in range(0, len(rows), CHUNK):
                stmt = insert(VectorItem).values([
                    {"collection": collection, "model": model, "item_id": item_id, "text_hash": digest,
                     "embedding": np.asarray(vec, dtype=np.float32), "payload": payload}
                    for item_id, digest, vec, payload in rows[i:i + CHUNK]])
                db.execute(stmt.on_conflict_do_update(
                    index_elements=[VectorItem.collection, VectorItem.model, VectorItem.item_id],
                    set_={"text_hash": stmt.excluded.text_hash, "embedding": stmt.excluded.embedding,
                          "payload": stmt.excluded.payload, "updated_at": func.now()}))
    except SQLAlchemyError:
        logger.exception("vector store write failed collection=%s", collection)


def update_payloads(collection: str, model: str, payloads: dict[str, dict]) -> None:
    if not enabled() or not payloads:
        return
    try:
        with database.session() as db:
            for item_id, payload in payloads.items():
                db.execute(VectorItem.__table__.update().where(
                    VectorItem.collection == collection, VectorItem.model == model, VectorItem.item_id == item_id)
                    .values(payload=payload, updated_at=func.now()))
    except SQLAlchemyError:
        logger.exception("vector store payload update failed collection=%s", collection)


def prune(collection: str, model: str, keep: set[str]) -> None:
    """Удаляет элементы коллекции, которых больше нет в источнике (например, тезис убран из базы знаний)."""
    if not enabled():
        return
    try:
        with database.session() as db:
            existing = set(db.scalars(select(VectorItem.item_id).where(
                VectorItem.collection == collection, VectorItem.model == model)))
            gone = sorted(existing - keep)
            for i in range(0, len(gone), CHUNK):
                db.execute(delete(VectorItem).where(VectorItem.collection == collection, VectorItem.model == model,
                                                    VectorItem.item_id.in_(gone[i:i + CHUNK])))
    except SQLAlchemyError:
        logger.exception("vector store prune failed collection=%s", collection)


def sync(collection: str, items: list[tuple[str, str, dict]], prune_missing: bool = False) -> dict[str, np.ndarray] | None:
    """Приводит коллекцию к списку (item_id, текст, payload) и возвращает item_id -> вектор.

    Модель считает только новые и изменившиеся тексты; payload обновляется отдельно.
    None — модель недоступна.
    """
    model = embeddings.model_name()
    if model is None:
        return None
    existing = load(collection, model, None if prune_missing else [i for i, _, _ in items])
    out: dict[str, np.ndarray] = {}
    stale, payloads = [], {}
    for item_id, text_, payload in items:
        row = existing.get(item_id)
        if row is not None and row[0] == text_hash(text_):
            out[item_id] = row[1]
            if row[2] != payload:
                payloads[item_id] = payload
        else:
            stale.append((item_id, text_, payload))
    if stale:
        vecs = embeddings.embed([t for _, t, _ in stale])
        if vecs is None:
            return None
        rows = []
        for (item_id, text_, payload), vec in zip(stale, vecs):
            out[item_id] = np.asarray(vec, dtype=np.float32)
            rows.append((item_id, text_hash(text_), out[item_id], payload))
        save(collection, model, rows)
    update_payloads(collection, model, payloads)
    if prune_missing:
        prune(collection, model, {i for i, _, _ in items})
    return out


def nearest(collection: str, vec, k: int = 10, exclude: list[str] | None = None,
            published_before: str | None = None, topics_any: list[str] | None = None) -> list[tuple[str, float, dict]] | None:
    """Ближайшие по косинусу элементы коллекции: [(item_id, сходство, payload)], None — поиск недоступен."""
    model = embeddings.model_name()
    if model is None or not enabled() or not _fits(vec):
        return None
    query = np.asarray(vec, dtype=np.float32)
    distance = VectorItem.embedding.cosine_distance(query)
    stmt = (select(VectorItem.item_id, (1 - distance).label("sim"), VectorItem.payload)
            .where(VectorItem.collection == collection, VectorItem.model == model)
            .order_by(distance).limit(k))
    if exclude:
        stmt = stmt.where(VectorItem.item_id.notin_(exclude))
    if published_before:
        stmt = stmt.where(VectorItem.payload["published_at"].astext < published_before)
    if topics_any:
        stmt = stmt.where(VectorItem.payload["topics"].has_any(array(topics_any)))
    try:
        with database.session() as db:
            # С фильтрами HNSW продолжает обход, пока не наберет k подходящих строк (pgvector 0.8).
            db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            db.execute(text(f"SET LOCAL hnsw.ef_search = {max(40, 2 * int(k))}"))
            rows = db.execute(stmt).all()
    except SQLAlchemyError:
        logger.exception("vector search failed collection=%s", collection)
        return None
    return [(item_id, float(sim), payload) for item_id, sim, payload in rows]


def stats() -> dict[str, int]:
    """Число векторов по коллекциям текущей модели (для /meta и логов прогрева)."""
    model = embeddings.model_name()
    if model is None or not enabled():
        return {}
    try:
        with database.session() as db:
            rows = db.execute(select(VectorItem.collection, func.count()).where(VectorItem.model == model)
                              .group_by(VectorItem.collection)).all()
    except SQLAlchemyError:
        return {}
    return {c: n for c, n in rows}

