"""Оценка качества разборов: прогон агента на фиксированной выборке «компания — роль — новость».

    python -m app.eval_quality --make-set eval_set.json --size 12     # собрать выборку из текущей БД
    python -m app.eval_quality --set eval_set.json --out report.json  # прогнать агента и посчитать метрики

Выборка берется из ленты привязанных или крупнейших компаний (самые релевантные новости),
чтобы оценивать то, что реально видит пользователь. Разборы не сохраняются в кэш.

Метрики (все 0..1, больше — лучше), итог — Q = 100 × среднее:
- llm_share        доля разборов, где пользователь получил текст модели (а не откат на правила);
- first_pass       доля разборов, прошедших все проверки с первой попытки;
- grounded         доля утверждений с источником, который реально был собран;
- personalized     сколько признаков компании использовано (min(1, признаков / 3));
- bank_coverage    доля разборов, где есть позиция банка;
- depth            насыщенность: min(1, (риски + возможности + действия) / 6);
- pass             доля разборов, прошедших финальные проверки.
Дополнительно: задержка p50/p90, токены на разбор (по журналу LLM).
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from pathlib import Path

ROLES = ["cfo", "ceo", "treasurer", "owner"]
METRICS = ("llm_share", "first_pass", "grounded", "personalized", "bank_coverage", "depth", "pass")


def make_set(size: int, seed: int) -> list[dict]:
    from app import ranking
    from app.companies import profiles
    from app.news import store

    rnd = random.Random(seed)
    companies = profiles._load()["companies"]
    # Разные отрасли: по одной крупнейшей компании на отрасль, затем случайные из них.
    by_sector: dict[str, dict] = {}
    for c in companies:
        by_sector.setdefault(c["sector"], c)
    pool = list(by_sector.values())
    rnd.shuffle(pool)
    items, seen = [], set()
    store.all_items()
    for c in pool:
        role = rnd.choice(ROLES)
        feed = ranking.feed(store.all_items(), c["company_id"], role, None, 10)
        for r in feed[:2]:
            key = (c["company_id"], r["news"]["news_id"])
            if key not in seen:
                seen.add(key)
                items.append({"company_id": c["company_id"], "sector": c["sector"], "role": role,
                              "news_id": r["news"]["news_id"], "title": r["news"]["title"][:120]})
        if len(items) >= size:
            break
    return items[:size]


def _metrics(ins: dict) -> dict:
    claims = [c for sec in ("why_important", "risks", "opportunities", "actions") for c in ins[sec]]
    claims += ins["what_happened"]["facts"] + ins["what_happened"]["assumptions"] + ins["bank_view"]["theses"]
    source_ids = {s["source_id"] for s in ins["sources"]}
    grounded = sum(1 for c in claims if c["source_ids"] and set(c["source_ids"]) <= source_ids) / max(len(claims), 1)
    features = {f for c in claims for f in c.get("features", [])}
    names = [s["name"] for s in ins["trace"]]
    llm_tried = "llm_compose" in names and any(s["name"] == "llm_compose" and s["status"] == "ok" for s in ins["trace"])
    return {
        "mode": ins["mode"],
        "llm_tried": llm_tried,
        "llm_share": float(ins["mode"] == "llm"),
        "first_pass": float(ins["quality"]["attempts"] == 1 and ins["quality"]["passed"]),
        "grounded": grounded,
        "personalized": min(1.0, len(features) / 3),
        "bank_coverage": float(bool(ins["bank_view"]["theses"])),
        "depth": min(1.0, (len(ins["risks"]) + len(ins["opportunities"]) + len(ins["actions"])) / 6),
        "pass": float(ins["quality"]["passed"]),
        "fallback": "safe_fallback" in names,
        "failed_checks": sorted({c["name"] for s in ins["trace"] if s["stage"] == "check" and s.get("output")
                                 for c in s["output"].get("checks", []) if not c["passed"]}),
        "first_errors": next((s["output"].get("claim_errors", {}) for s in ins["trace"]
                              if s["name"] == "self_check_1" and s.get("output")), {}),
        "headline": ins["headline"][:160],
    }


async def run(items: list[dict]) -> dict:
    from app.agent import llm, orchestrator
    from app.companies import profiles
    from app.news import store

    rows = []
    for it in items:
        company, news = profiles.get(it["company_id"]), store.get(it["news_id"])
        if company is None or news is None:
            rows.append({**it, "error": "missing"})
            continue
        before = llm.usage()["tokens"]
        t0 = time.perf_counter()
        try:
            ins = await orchestrator.run(company, it["role"], news, f"req_eval_{uuid.uuid4().hex[:8]}")
            m = _metrics(ins)
        except Exception as exc:  # отказ разбора — тоже результат
            m = {"error": type(exc).__name__, **{k: 0.0 for k in METRICS}}
        m.update(it, seconds=round(time.perf_counter() - t0, 1), tokens=llm.usage()["tokens"] - before)
        rows.append(m)
        print(f"{m.get('mode', 'ERR'):5} {m['seconds']:5.1f}s fp={m.get('first_pass')} fb={m.get('fallback')} "
              f"fail={m.get('failed_checks')} | {it['title'][:60]}", flush=True)
    ok = [r for r in rows if "error" not in r]
    agg = {k: round(statistics.mean(r[k] for r in ok), 3) if ok else 0.0 for k in METRICS}
    secs = sorted(r["seconds"] for r in ok) or [0]
    agg.update(Q=round(100 * statistics.mean(agg[k] for k in METRICS), 1), n=len(rows), errors=len(rows) - len(ok),
               fallbacks=sum(1 for r in ok if r.get("fallback")),
               latency_p50=secs[len(secs) // 2], latency_p90=secs[min(len(secs) - 1, int(len(secs) * 0.9))],
               tokens_per_insight=round(statistics.mean(r["tokens"] for r in ok)) if ok else 0,
               first_errors={k: sum(r.get("first_errors", {}).get(k, 0) for r in ok)
                             for k in sorted({k for r in ok for k in r.get("first_errors", {})})})
    return {"summary": agg, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-set")
    ap.add_argument("--size", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--set")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.make_set:
        items = make_set(a.size, a.seed)
        Path(a.make_set).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"eval set: {len(items)} items -> {a.make_set}")
        return
    items = json.loads(Path(a.set).read_text(encoding="utf-8"))
    report = asyncio.run(run(items))
    print(json.dumps(report["summary"], ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
