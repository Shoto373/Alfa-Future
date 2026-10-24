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

import logging

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.exc import SQLAlchemyError

from app import database, embeddings, vector_store
from app.models import VectorItem

logger = logging.getLogger("app.vectors")

def sync(collection: str, items: list[tuple[str, str, dict]], prune_missing: bool = False) -> dict[str, np.ndarray] | None:
    """Приводит коллекцию к списку (item_id, текст, payload) и возвращает item_id -> вектор.

    Модель считает только новые и изменившиеся тексты; payload обновляется отдельно.
    None — модель недоступна.
    """
    model = embeddings.model_name()
    if model is None:
        return None
    existing = vector_store.load(collection, model, None if prune_missing else [i for i, _, _ in items])
    out: dict[str, np.ndarray] = {}
    stale, payloads = [], {}
    for item_id, text_, payload in items:
        row = existing.get(item_id)
        if row is not None and row[0] == vector_store.text_hash(text_):
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
            rows.append((item_id, vector_store.text_hash(text_), out[item_id], payload))
        vector_store.save(collection, model, rows)
    vector_store.update_payloads(collection, model, payloads)
    if prune_missing:
        vector_store.prune(collection, model, {i for i, _, _ in items})
    return out


def nearest(collection: str, vec, k: int = 10, exclude: list[str] | None = None,
            published_before: str | None = None, topics_any: list[str] | None = None) -> list[tuple[str, float, dict]] | None:
    """Ближайшие по косинусу элементы коллекции: [(item_id, сходство, payload)], None — поиск недоступен."""
    model = embeddings.model_name()
    if model is None or not vector_store.enabled() or not vector_store.fits(vec):
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
    if model is None or not vector_store.enabled():
        return {}
    try:
        with database.session() as db:
            rows = db.execute(select(VectorItem.collection, func.count()).where(VectorItem.model == model)
                              .group_by(VectorItem.collection)).all()
    except SQLAlchemyError:
        return {}
    return {c: n for c, n in rows}

