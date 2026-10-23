"""Смысловые векторы текстов: локальная multilingual-модель через ONNX (fastembed).

Нужны, чтобы понимать новость по смыслу, а не только по словарю: «мегарегулятор
оставил стоимость заимствований» — это ключевая ставка, хотя слова «ставка» нет.
Модель не генеративная и работает локально, ключ и сеть ей не нужны (модель
скачивается при сборке образа). Если модель недоступна, сервис работает на
словарях, как раньше: embed() возвращает None.

Векторы кэшируются в два уровня: в памяти процесса и в векторном хранилище
(app.vectors, коллекция cache). Модель загружается и прогревается при старте
сервиса (warm), а уже посчитанные векторы читаются из базы одним запросом.
"""

import hashlib
import logging
import threading
from collections import OrderedDict

import numpy as np

from app import config

logger = logging.getLogger("app.embeddings")

_lock = threading.Lock()        # загрузка и вызов модели: одна ONNX-сессия на процесс
_cache_lock = threading.Lock()  # кэш векторов в памяти
_model = None
_model_key: tuple | None = None
_failed: set[tuple] = set()
_cache: "OrderedDict[str, np.ndarray]" = OrderedDict()
CACHE_SIZE = 50_000  # ~75 МБ при размерности 384


def _key() -> tuple | None:
    s = config.embeddings_settings()
    return (s["model"], s["cache_dir"]) if s["enabled"] else None


def signature() -> str:
    """Меняется при включении/смене модели — по нему новости переклассифицируются."""
    key = _key()
    return f"emb:{key[0]}" if key and key not in _failed else "emb:off"


def model_name() -> str | None:
    """Имя модели, если она включена и загружается; ключ векторов в хранилище."""
    with _lock:
        return _model_key[0] if _load() is not None and _model_key else None


def _load():
    global _model, _model_key
    key = _key()
    if key is None or key in _failed:
        return None
    if _model is not None and _model_key == key:
        return _model
    try:
        from fastembed import TextEmbedding
        _model = TextEmbedding(key[0], cache_dir=key[1])
        if _model_key != key:
            with _cache_lock:
                _cache.clear()  # векторы другой модели несовместимы
        _model_key = key
        logger.info("embeddings model loaded: %s", key[0])
        return _model
    except Exception:  # нет пакета, модели или памяти — работаем на словарях
        logger.exception("embeddings model unavailable, falling back to keyword matching")
        _failed.add(key)
        return None


def available() -> bool:
    with _lock:
        return _load() is not None


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _remember(items: dict[str, np.ndarray]) -> None:
    with _cache_lock:
        for k, v in items.items():
            _cache[k] = v
            _cache.move_to_end(k)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def warm() -> bool:
    """Загрузка модели, пробный вызов (инициализация ONNX) и чтение посчитанных векторов из базы."""
    from app import vectors

    model = model_name()
    if model is None:
        return False
    with _lock:
        list(_model.embed(["прогрев модели"]))
    stored = vectors.load(vectors.CACHE, model)
    _remember({k: v for k, (_, v, _) in list(stored.items())[-CACHE_SIZE:]})
    logger.info("embeddings warm: model=%s cached_vectors=%d", model, len(stored))
    return True


def _normalize(matrix) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(norms == 0, 1.0, norms)


def embed(texts: list[str]) -> np.ndarray | None:
    """Нормированные векторы (матрица n × d) для списка текстов или None, если модель недоступна."""
    from app import vectors

    with _lock:
        model = _load()
        name = _model_key[0] if model is not None and _model_key else None
    if model is None or name is None:
        return None
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    keys = [_hash(t) for t in texts]
    with _cache_lock:
        found = {k: _cache[k] for k in keys if k in _cache}
    missing = {k: t for k, t in zip(keys, texts) if k not in found}
    if missing:
        stored = vectors.load(vectors.CACHE, name, list(missing))
        fresh = {k: v for k, (_, v, _) in stored.items()}
        todo = {k: t for k, t in missing.items() if k not in fresh}
        if todo:
            batch = config.embeddings_settings()["batch_size"]
            try:
                with _lock:
                    computed = _normalize(list(model.embed(list(todo.values()), batch_size=batch)))
            except Exception:
                logger.exception("embedding failed")
                return None
            computed_map = dict(zip(todo, computed))
            fresh.update(computed_map)
            vectors.save(vectors.CACHE, name, [(k, k, v, {}) for k, v in computed_map.items()])
        _remember(fresh)
        found.update(fresh)
    return np.stack([found[k] for k in keys])


def as_matrix(vectors) -> np.ndarray:
    """Матрица из результата embed (или из списков векторов в тестах)."""
    return np.asarray(vectors, dtype=np.float32)


def cosine(a, b) -> float:
    return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))


def reset() -> None:
    """Для тестов: забыть загруженную модель, сбои и кэш."""
    global _model, _model_key
    with _lock:
        _model, _model_key = None, None
        _failed.clear()
    with _cache_lock:
        _cache.clear()
