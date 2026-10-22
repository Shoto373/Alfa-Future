"""Журнал обращений агента к инструментам в PostgreSQL.

Пишутся имя инструмента, аргументы без чувствительных полей, статус,
длительность и request_id. Тексты профилей и ответы модели не пишутся.
"""

import time
from datetime import datetime, timezone

from app import database
from sqlalchemy import select
from app.models import ToolAudit

SENSITIVE = {"api_key", "authorization", "text", "question"}


def _safe(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if k in SENSITIVE:
            out[k] = f"<{len(str(v))} chars>"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v if not isinstance(v, str) else v[:120]
        elif isinstance(v, list):
            out[k] = [str(x)[:40] for x in v[:10]]
        else:
            out[k] = type(v).__name__
    return out


def log(request_id: str, tool: str, args: dict, status: str, duration_ms: float, detail: str = "") -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "request_id": request_id, "tool": tool, "args": _safe(args), "status": status,
        "duration_ms": round(duration_ms, 1), "detail": detail[:200],
    }
    with database.session() as db:
        db.add(ToolAudit(request_id=request_id, payload=record))


def tail(limit: int = 100) -> list[dict]:
    with database.session() as db:
        rows = list(db.scalars(select(ToolAudit.payload).order_by(ToolAudit.id.desc()).limit(limit)))
    return list(reversed(rows))


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.start) * 1000
        return False
