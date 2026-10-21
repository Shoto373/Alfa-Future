"""Журнал обращений агента к инструментам (JSONL в RUNTIME_DIR/audit.jsonl).

Пишутся имя инструмента, аргументы без чувствительных полей, статус,
длительность и request_id. Тексты профилей и ответы модели не пишутся.
"""

import json
import threading
import time
from datetime import datetime, timezone

from app import config

_lock = threading.Lock()
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
    with _lock:
        with (config.runtime_dir() / "audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def tail(limit: int = 100) -> list[dict]:
    path = config.runtime_dir() / "audit.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]


class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = (time.perf_counter() - self.start) * 1000
        return False
