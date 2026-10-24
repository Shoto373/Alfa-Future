"""Ограничение частоты запросов (SPR3-04): фиксированное окно в Redis, общее для всех экземпляров API.

Лимиты на пользователя и на адрес для дорогих запросов (разбор, вопрос, добавление новости). Превышение —
429 TOO_MANY_REQUESTS с заголовком Retry-After. Без Redis лимит считается в памяти каждого экземпляра.
"""

import hashlib
import time

from app import cache, config
from app.errors import ApiError

WINDOW_SECONDS = 60


def _key(scope: str, who: str, slot: int) -> str:
    return f"rl:{scope}:{hashlib.sha256(who.encode()).hexdigest()[:16]}:{slot}"  # без email и адресов в ключах


def check(scope: str, user_id: str, ip: str) -> None:
    """Учитывает запрос; превышение лимита на пользователя или на адрес — ApiError TOO_MANY_REQUESTS."""
    per_user, per_ip = config.rate_limits(scope)
    now = time.time()
    slot = int(now // WINDOW_SECONDS)
    retry_after = int(WINDOW_SECONDS - now % WINDOW_SECONDS) + 1
    for who, limit in ((f"user:{user_id}", per_user), (f"ip:{ip}", per_ip)):
        if limit > 0 and cache.incr(_key(scope, who, slot), WINDOW_SECONDS + 5) > limit:
            raise ApiError("TOO_MANY_REQUESTS", headers={"Retry-After": str(retry_after)})
