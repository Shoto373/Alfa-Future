"""Очередь задач воркера в PostgreSQL (таблица jobs) — без отдельного брокера.

Задачу берет ровно один воркер: SELECT … FOR UPDATE SKIP LOCKED. Взятая задача держит аренду
(locked_until); если воркер упал, после окончания аренды задачу берет другой. Упавшая задача
повторяется с экспоненциальной задержкой; после max_attempts — status=dead (dead-letter), с текстом ошибки.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app import database
from app.models import Job

LEASE = timedelta(minutes=30)          # дольше самого долгого цикла конвейера
RETRY_BASE_SECONDS = 30                # повтор через 30 с, 60 с, 2 мин, 4 мин…
KEEP_FINISHED = timedelta(days=7)      # выполненные и мертвые задачи хранятся неделю для разбора
URGENT = ("domain_config_preview",)    # человек ждет результат на экране: берутся раньше плановых циклов


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(kind: str, payload: dict | None = None, run_at: datetime | None = None, dedupe_key: str | None = None,
            max_attempts: int = 5) -> int | None:
    """Ставит задачу; None — задача с тем же dedupe_key уже есть (плановая задача не дублируется)."""
    values = {"kind": kind, "payload": payload or {}, "run_at": run_at or _now(), "dedupe_key": dedupe_key,
              "max_attempts": max_attempts}
    with database.session() as db:
        return db.execute(insert(Job).values(**values).on_conflict_do_nothing(index_elements=["dedupe_key"])
                          .returning(Job.id)).scalar()


def claim(worker_id: str) -> dict | None:
    """Берет готовую задачу (или задачу с истекшей арендой упавшего воркера) и продлевает аренду."""
    now = _now()
    with database.session() as db:
        job = db.scalars(select(Job).where(or_(
            (Job.status == "queued") & (Job.run_at <= now),
            (Job.status == "running") & (Job.locked_until < now),
        )).order_by(Job.kind.not_in(URGENT), Job.run_at, Job.id).limit(1).with_for_update(skip_locked=True)).first()
        if job is None:
            return None
        job.status, job.locked_by, job.locked_until = "running", worker_id, now + LEASE
        job.attempts += 1
        db.flush()
        return {"id": job.id, "kind": job.kind, "payload": dict(job.payload), "attempts": job.attempts,
                "max_attempts": job.max_attempts}


def complete(job_id: int) -> None:
    with database.session() as db:
        db.execute(update(Job).where(Job.id == job_id).values(
            status="done", finished_at=_now(), locked_by=None, locked_until=None, error=None))


def fail(job_id: int, error: str) -> str:
    """Неудачная попытка: повтор с задержкой или dead-letter. Возвращает новый статус."""
    with database.session() as db:
        job = db.get(Job, job_id, with_for_update=True)
        job.error, job.locked_by, job.locked_until = error[:1000], None, None
        if job.attempts >= job.max_attempts:
            job.status, job.finished_at = "dead", _now()
        else:
            job.status = "queued"
            job.run_at = _now() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** (job.attempts - 1))
        return job.status


def release(job_id: int) -> None:
    """Воркер останавливается, не начав задачу: вернуть ее в очередь без траты попытки."""
    with database.session() as db:
        db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(
            status="queued", locked_by=None, locked_until=None, attempts=Job.attempts - 1))


def cleanup() -> int:
    """Удаляет выполненные и мертвые задачи старше недели. Возвращает число удаленных."""
    with database.session() as db:
        removed = db.execute(delete(Job).where(Job.status.in_(("done", "dead")), Job.finished_at < _now() - KEEP_FINISHED)
                             .returning(Job.id)).all()
    return len(removed)


def stats() -> dict:
    """Очередь для /meta и метрик: задач в ожидании, в работе, мертвых и возраст самой старой готовой."""
    now = _now()
    with database.session() as db:
        rows = db.execute(select(Job.status, Job.run_at).where(Job.status.in_(("queued", "running", "dead")))).all()
    ready = [run_at for status, run_at in rows if status == "queued" and run_at <= now]
    return {"queued": sum(1 for s, _ in rows if s == "queued"), "running": sum(1 for s, _ in rows if s == "running"),
            "dead": sum(1 for s, _ in rows if s == "dead"),
            "oldest_ready_seconds": round((now - min(ready)).total_seconds()) if ready else 0}
