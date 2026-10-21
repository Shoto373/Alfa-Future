"""Карточки, обратная связь и метрики качества (JSON/JSONL в RUNTIME_DIR)."""

import json
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone

from app import config
from app.agent import llm

_lock = threading.Lock()


def _dir(name: str):
    path = config.runtime_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(company_id: str, role: str, news_id: str) -> str:
    return f"{company_id}__{role}__{news_id}".replace("/", "_")


def save_insight(insight: dict) -> None:
    with _lock:
        (_dir("insights") / f"{insight['insight_id']}.json").write_text(json.dumps(insight, ensure_ascii=False), encoding="utf-8")
        index = _index()
        index[_key(insight["company_id"], insight["role"], insight["news_id"])] = insight["insight_id"]
        (_dir("insights") / "_index.json").write_text(json.dumps(index), encoding="utf-8")


def _index() -> dict:
    path = _dir("insights") / "_index.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


def get_insight(insight_id: str) -> dict | None:
    if not insight_id.replace("-", "").isalnum():
        return None
    path = _dir("insights") / f"{insight_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def cached_insight(company_id: str, role: str, news_id: str) -> dict | None:
    iid = _index().get(_key(company_id, role, news_id))
    return get_insight(iid) if iid else None


def _append(name: str, record: dict) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")} | record
    with _lock:
        with (config.runtime_dir() / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read(name: str) -> list[dict]:
    path = config.runtime_dir() / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add_feedback(fb: dict) -> None:
    _append("feedback.jsonl", fb)


def log_event(kind: str, **data) -> None:
    _append("events.jsonl", {"kind": kind} | data)


def metrics() -> dict:
    insights = [json.loads(p.read_text(encoding="utf-8")) for p in _dir("insights").glob("ins-*.json")]
    feedback = _read("feedback.jsonl")
    events = _read("events.jsonl")

    checks: dict[str, list[bool]] = defaultdict(list)
    first_pass, claims_total, claims_linked, latency = 0, 0, 0, []
    modes = Counter()
    for ins in insights:
        modes[ins["mode"]] += 1
        first_pass += int(ins["quality"]["attempts"] == 1 and ins["quality"]["passed"])
        for c in ins["quality"]["checks"]:
            checks[c["name"]].append(c["passed"])
        for sec in ("why_important", "risks", "opportunities", "actions"):
            for cl in ins[sec]:
                claims_total += 1
                claims_linked += int(bool(cl["source_ids"]))
        latency.append(sum(s["duration_ms"] for s in ins["trace"]))

    ratings = Counter(f["rating"] for f in feedback)
    by_section = defaultdict(Counter)
    for f in feedback:
        by_section[f.get("section") or "card"][f["rating"]] += 1
    feed_views = sum(1 for e in events if e["kind"] == "feed_view")
    opens = sum(1 for e in events if e["kind"] == "insight_open")
    n = len(insights) or 1
    return {
        "content": {
            "insights": len(insights),
            "first_pass_rate": round(first_pass / n, 3),
            "claims_with_sources": round(claims_linked / (claims_total or 1), 3),
            "checks_pass_rate": {k: round(sum(v) / len(v), 3) for k, v in checks.items()},
        },
        "personalization": {
            "feed_views": feed_views,
            "insight_opens": opens,
            "open_rate": round(opens / feed_views, 3) if feed_views else None,
            "useful_rate": round(ratings[1] / (ratings[1] + ratings[-1]), 3) if feedback else None,
            "feedback": {"up": ratings[1], "down": ratings[-1]},
            "by_section": {k: {"up": v[1], "down": v[-1]} for k, v in by_section.items()},
        },
        "ai": {
            "modes": dict(modes),
            "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else None,
            "llm_usage": llm.usage(),
            "llm_connected": llm.available(),
        },
        "recent_feedback": [f for f in feedback[-10:] if f.get("comment")],
    }
