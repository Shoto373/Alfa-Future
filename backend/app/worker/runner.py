"""Цикл воркера: расписание → задача из очереди → выполнение → отметка; пульс в app_state для /meta."""

import logging
import os
import signal
import socket
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app import database, warmup
from app.models import AppState
from app.worker import queue, schedule
from app.worker.tasks import HANDLERS

logger = logging.getLogger("app.worker")

STATE_PREFIX = "worker:"   # пульс каждого воркера — своя запись app_state (по имени хоста)
POLL_SECONDS = 2.0          # пауза, когда очередь пуста
TICK_SECONDS = 15.0         # как часто сверяться с расписанием плановых задач
HEARTBEAT_SECONDS = 30.0    # пульс — отдельным потоком: долгая задача не делает воркер «мертвым»
ALIVE_SECONDS = 120.0


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.stop = threading.Event()
        self.last: dict | None = None

    def handle_signals(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop.set())

    def heartbeat(self) -> None:
        state = {"id": self.id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "last_job": self.last}
        try:
            with database.session() as db:
                database.set_state(STATE_PREFIX + socket.gethostname(), state, db)
        except Exception:  # пульс — для наблюдения, не повод останавливать задачи
            logger.exception("worker heartbeat failed")

    def _pulse(self) -> None:
        while not self.stop.wait(HEARTBEAT_SECONDS):
            self.heartbeat()

    def run_one(self) -> bool:
        """Взять и выполнить одну задачу. False — очередь пуста."""
        job = queue.claim(self.id)
        if job is None:
            return False
        if self.stop.is_set():  # остановка пришла между выборкой и стартом — задача возвращается в очередь
            queue.release(job["id"])
            return False
        started = time.perf_counter()
        handler = HANDLERS.get(job["kind"])
        try:
            if handler is None:
                raise LookupError(f"нет обработчика задачи {job['kind']}")
            result = handler(job["payload"])
            queue.complete(job["id"])
            status = "done"
        except Exception as exc:
            logger.exception("job failed id=%s kind=%s attempt=%s", job["id"], job["kind"], job["attempts"])
            status, result = queue.fail(job["id"], f"{type(exc).__name__}: {exc}"), None
        self.last = {"id": job["id"], "kind": job["kind"], "status": status,
                     "duration": round(time.perf_counter() - started, 1)}
        logger.info("job id=%s kind=%s status=%s result=%s", job["id"], job["kind"], status, result)
        return True

    def run(self, warm: bool = True) -> None:
        logger.info("worker %s starting", self.id)
        if warm:
            database.migrate()
            warmup.run(role="worker")
        self.heartbeat()
        threading.Thread(target=self._pulse, name="worker-heartbeat", daemon=True).start()
        ticked = 0.0
        while not self.stop.is_set():
            try:
                if time.monotonic() - ticked >= TICK_SECONDS:
                    schedule.tick()
                    ticked = time.monotonic()
                busy = self.run_one()
            except Exception:  # база недоступна — пауза и новая попытка, процесс не падает
                logger.exception("worker loop error")
                busy = False
            if not busy:
                self.stop.wait(POLL_SECONDS)
        self.heartbeat()
        logger.info("worker %s stopped", self.id)


def status() -> dict | None:
    """Самый свежий пульс среди воркеров (для /meta): id, время, последняя задача, число воркеров."""
    with database.session() as db:
        beats = list(db.scalars(select(AppState.payload).where(AppState.key.startswith(STATE_PREFIX))))
    if not beats:
        return None
    return max(beats, key=lambda b: b.get("at") or "") | {"workers": len(beats)}


def healthy() -> bool:
    """Проверка здоровья контейнера: пульс этого хоста не старше ALIVE_SECONDS."""
    beat = database.state(STATE_PREFIX + socket.gethostname()) or {}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat["at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    return age < ALIVE_SECONDS
