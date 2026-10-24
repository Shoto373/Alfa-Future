"""Общий кэш: память процесса и Redis (если задан REDIS_URL).

Значения — JSON. Ключ всегда включает версию данных (ревизию новостей, подпись
профилей), поэтому устаревшее значение не читается, а просто истекает по TTL.
Redis общий для процессов и переживает рестарт backend; без Redis или при его
сбое кэш работает только в памяти — это ускоритель, а не источник данных.
"""

import json
import logging
import threading
import time

import redis

from app import config

logger = logging.getLogger("app.cache")

PREFIX = "alfa:"
LOCAL_SIZE = 2048
RETRY_SECONDS = 30.0  # после сбоя Redis не опрашивается это время
LOCAL_FROM_REDIS_SECONDS = 15  # значение из Redis держится в памяти процесса

_lock = threading.Lock()
_local: dict[str, tuple[float, object]] = {}
_client = None
_client_url: str | None = None
_down_until = 0.0


def _redis():
    global _client, _client_url, _down_until
    url = config.redis_url()
    if not url or time.monotonic() < _down_until:
        return None
    if _client is None or _client_url != url:
        _client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, health_check_interval=30)
        _client_url = url
    return _client


def _failed(exc: Exception) -> None:
    global _down_until
    _down_until = time.monotonic() + RETRY_SECONDS
    logger.warning("redis unavailable, using in-process cache for %.0fs: %s", RETRY_SECONDS, exc)


def get(key: str):
    now = time.monotonic()
    with _lock:
        hit = _local.get(key)
        if hit and hit[0] > now:
            return hit[1]
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(PREFIX + key)
    except Exception as exc:  # redis.RedisError, OSError
        _failed(exc)
        return None
    if raw is None:
        return None
    value = json.loads(raw)
    _put_local(key, value, LOCAL_FROM_REDIS_SECONDS)
    return value


def _put_local(key: str, value, ttl: float) -> None:
    with _lock:
        if len(_local) >= LOCAL_SIZE:
            now = time.monotonic()
            for k in [k for k, (exp, _) in _local.items() if exp <= now] or list(_local)[: LOCAL_SIZE // 4]:
                _local.pop(k, None)
        _local[key] = (time.monotonic() + ttl, value)


def set(key: str, value, ttl: int) -> None:  # noqa: A001 - имя по смыслу API кэша
    _put_local(key, value, ttl)
    client = _redis()
    if client is None:
        return
    try:
        client.set(PREFIX + key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), ex=ttl)
    except Exception as exc:
        _failed(exc)


def incr(key: str, ttl: int) -> int:
    """Счетчик с истечением (ограничение частоты): общий для процессов через Redis, без Redis — в памяти процесса."""
    client = _redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(PREFIX + key)
            pipe.expire(PREFIX + key, ttl, nx=True)
            return int(pipe.execute()[0])
        except Exception as exc:
            _failed(exc)
    now = time.monotonic()
    with _lock:
        expires, count = _local.get(key, (0.0, 0))
        if expires <= now:
            expires, count = now + ttl, 0
        _local[key] = (expires, count + 1)
        return count + 1


def ping() -> bool | None:
    """True/False — Redis отвечает или нет, None — Redis не настроен."""
    if not config.redis_url():
        return None
    client = _redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception as exc:
        _failed(exc)
        return False


def clear() -> None:
    """Для тестов: очистить кэш процесса и забыть клиента Redis."""
    global _client, _client_url, _down_until
    with _lock:
        _local.clear()
    _client, _client_url, _down_until = None, None, 0.0
