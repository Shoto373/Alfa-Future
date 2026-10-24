"""Хранение векторов в PostgreSQL + pgvector (таблица vector_items): чтение, запись, очистка коллекций.

Нижний слой без зависимости от модели эмбеддингов: им пользуются и embeddings (кэш посчитанных векторов),
и vectors (синхронизация коллекций и поиск ближайших). Сбой базы не ломает анализ — функции возвращают пусто.
"""

import hashlib
import logging

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app import config, database
from app.models import VECTOR_DIM, VectorItem

logger = logging.getLogger("app.vectors")

CACHE, NEWS, THESIS = "cache", "news", "thesis"
CHUNK = 500  # строк в одном INSERT


def text_hash(text_: str) -> str:
    return hashlib.sha1(text_.encode()).hexdigest()


def enabled() -> bool:
    return config.embeddings_settings()["persist"]


def fits(vec) -> bool:
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
    rows = [r for r in rows if fits(r[2])]
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
