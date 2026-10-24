"""Расписание воркера: плановые задачи ставятся в очередь один раз за интервал.

Ключ задачи — вид и номер интервала (dedupe_key), поэтому несколько воркеров или перезапуск
не ставят одну и ту же плановую задачу дважды.
"""

import time
from collections.abc import Callable

from app import config
from app.worker import queue

MINUTE = 60


def plan() -> list[tuple[str, int, Callable[[], bool]]]:
    """(вид задачи, интервал в секундах, включена ли)."""
    minutes = config.rss_refresh_minutes()
    return [
        ("news_cycle", max(minutes, 1) * MINUTE, lambda: minutes > 0),
        ("news_reclassify", 10 * MINUTE, lambda: True),
        ("warm_feeds", 15 * MINUTE, config.warm_feeds_on_start),
        ("llm_sweep", 5 * MINUTE, lambda: True),
        ("jobs_cleanup", 24 * 60 * MINUTE, lambda: True),
    ]


def tick(now: float | None = None) -> list[str]:
    """Ставит в очередь плановые задачи текущего интервала. Возвращает виды поставленных задач."""
    now = time.time() if now is None else now
    queued = []
    for kind, every, enabled in plan():
        if enabled() and queue.enqueue(kind, dedupe_key=f"{kind}:{int(now // every)}") is not None:
            queued.append(kind)
    return queued
