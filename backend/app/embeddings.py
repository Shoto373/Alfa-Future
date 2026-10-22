"""Смысловые векторы текстов: локальная multilingual-модель через ONNX (fastembed).

Нужны, чтобы понимать новость по смыслу, а не только по словарю: «мегарегулятор
оставил стоимость заимствований» — это ключевая ставка, хотя слова «ставка» нет.
Модель не генеративная и работает локально, ключ и сеть ей не нужны (модель
скачивается при сборке образа). Если модель недоступна, сервис работает на
словарях, как раньше: embed() возвращает None.
"""

import hashlib
import logging
import threading
from collections import OrderedDict

from app import config

logger = logging.getLogger("app.embeddings")

_lock = threading.Lock()
_model = None
_model_key: tuple | None = None
_failed: set[tuple] = set()
_cache: "OrderedDict[str, list[float]]" = OrderedDict()
CACHE_SIZE = 4096


def _key() -> tuple | None:
    s = config.embeddings_settings()
    return (s["model"], s["cache_dir"]) if s["enabled"] else None


def signature() -> str:
    """Меняется при включении/смене модели — по нему новости переклассифицируются."""
    key = _key()
    return f"emb:{key[0]}" if key and key not in _failed else "emb:off"


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


def _normalize(vec) -> list[float]:
    values = [float(x) for x in vec]  # numpy float32 не сериализуется в JSON
    norm = sum(x * x for x in values) ** 0.5 or 1.0
    return [x / norm for x in values]


def embed(texts: list[str]) -> list[list[float]] | None:
    """Нормированные векторы для списка текстов или None, если модель недоступна."""
    with _lock:
        model = _load()
        if model is None:
            return None
        keys = [hashlib.sha1(f"{_model_key[0]}|{t}".encode()).hexdigest() for t in texts]
        missing = {k: t for k, t in zip(keys, texts) if k not in _cache}
        if missing:
            try:
                vectors = list(model.embed(list(missing.values())))
            except Exception:
                logger.exception("embedding failed")
                return None
            for k, v in zip(missing, vectors):
                _cache[k] = _normalize(v)
                if len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
        for k in keys:
            _cache.move_to_end(k)
        return [_cache[k] for k in keys]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def reset() -> None:
    """Для тестов: забыть загруженную модель, сбои и кэш."""
    global _model, _model_key
    with _lock:
        _model, _model_key = None, None
        _failed.clear()
        _cache.clear()
