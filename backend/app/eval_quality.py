"""Оценка качества разборов: прогон агента на фиксированной выборке «компания — роль — новость».

    python -m app.eval_quality --set tests/golden --mode rules --out q.json --md q.md   # golden set (SPR2-04)
    python -m app.eval_quality --make-set eval_set.json --size 12     # собрать выборку из текущей БД
    python -m app.eval_quality --set eval_set.json --out report.json  # прогнать агента и посчитать метрики

Golden set (tests/golden/cases.json): 30 синтетических пар с ожиданиями, записанными до прогона —
тема, знак эффекта, тема обязательного тезиса банка, запрещенные утверждения. Метрики golden set:
first_pass_rate, pass_rate, sourced_rate, topic_match, sign_match, bank_coverage, forbidden_ok,
причины провала первой попытки по коду проверки, задержка p50/p95, токены и стоимость LLM.
Порог для режима правил проверяет tests/test_golden_quality.py.

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
import copy
import json
import random
import statistics
import time
import uuid
from collections import Counter
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


GOLDEN_FORBIDDEN = ("гарантир", "999")  # запрещено в любом разборе: обещания банка и выдуманные числа


def load_golden(path: str | Path) -> list[dict]:
    p = Path(path)
    return json.loads((p / "cases.json" if p.is_dir() else p).read_text(encoding="utf-8"))["items"]


def golden_company(base: dict, spec: dict) -> dict:
    """Синтетическая компания из шаблона кейса: отрасль, продукты, страны ВЭД (как в tests/test_scenarios.py)."""
    from app.companies import profiles
    from app.companies.sectors import SECTOR_NAMES

    c = copy.deepcopy(base)
    c.update(sector=spec["sector"], revenue=20e9, workers_fns=None, fts_flag=bool(spec.get("countries")),
             fts_countries=spec.get("countries", []))
    c["sector_name"] = SECTOR_NAMES.get(c["sector"], c["sector"])
    c["products"] = dict.fromkeys(c["products"], False) | spec.get("products", {})
    c["market"] = {"okved_rank": None, "okved_peers": None, "okved_share": None, "sector_share": None}
    for side in ("suppliers", "customers"):
        c[side] = {"counterparties": 0, "total_amount": 0, "top1_share": None, "by_sector": [], "top": [],
                   "intra_group_share": None}
    profiles._cache["by_id"][c["company_id"]] = c
    profiles.exposures.cache_clear()
    return c


def observed_effect(ins: dict) -> str:
    """Знак влияния по разделам разбора; оговорки «Возможный риск — …» / «Возможность — …» знак не задают."""
    if not ins["risks"] and not ins["opportunities"]:
        return "none"
    firm_risk = any(not c["text"].startswith("Возможный риск —") for c in ins["risks"])
    firm_opp = any(not c["text"].startswith("Возможность —") for c in ins["opportunities"])
    return "mixed" if firm_risk and firm_opp else "neg" if firm_risk else "pos" if firm_opp else "unclear"


def golden_metrics(case: dict, news: dict, ins: dict) -> dict:
    from app.knowledge import kb

    exp = case["expect"]
    claims = [c for sec in ("why_important", "risks", "opportunities", "actions") for c in ins[sec]]
    claims += ins["what_happened"]["facts"] + ins["what_happened"]["assumptions"] + ins["bank_view"]["theses"]
    known = {s["source_id"] for s in ins["sources"]}
    topics = [t["topic"] for t in news["classification"]["topics"]]
    first = next((s["output"] for s in ins["trace"] if s["name"] == "self_check_1" and s.get("output")), {})
    first_failed = sorted(c["name"] for c in first.get("checks", []) if not c["passed"])
    bank_topics = {t for c in ins["bank_view"]["theses"] for sid in c["source_ids"] if sid.startswith("bank:")
                   for t in (kb.thesis(sid[5:]) or {}).get("topics", [])}
    text = json.dumps({k: ins[k] for k in ("headline", "what_happened", "why_important", "risks", "opportunities",
                                           "actions", "bank_view")}, ensure_ascii=False).lower()
    forbidden = [f for f in list(exp["forbidden"]) + list(GOLDEN_FORBIDDEN) if f.lower() in text]
    effect = observed_effect(ins)
    return {
        "first_pass": ins["quality"]["attempts"] == 1 and ins["quality"]["passed"] and not first_failed,
        "passed": ins["quality"]["passed"],
        "first_failed": first_failed,
        "claims": len(claims),
        "sourced": sum(1 for c in claims if c["source_ids"] and set(c["source_ids"]) <= known),
        "topics": topics,
        "topic_match": set(exp["topics"]) <= set(topics) and (bool(topics) or not exp["topics"]),
        "effect": effect,
        "sign_match": effect == exp["effect"],
        "bank_ok": None if not exp["bank_topic"] else exp["bank_topic"] in bank_topics,
        "forbidden_found": forbidden,
        "mode": ins["mode"],
    }


def _pct(values: list[float], q: float) -> float:
    s = sorted(values) or [0.0]
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


async def run_golden(cases: list[dict], mode: str = "rules") -> dict:
    """Прогон golden set; mode: rules — без модели, llm — с моделью (нужен ключ), auto — как в сервисе."""
    from app.agent import llm, orchestrator
    from app.companies import profiles
    from app.news import store

    use_llm = {"rules": False, "llm": True, "auto": None}[mode]
    base = profiles._load()["companies"][0]
    rows = []
    for case in cases:
        company = golden_company(base, case["company"])
        news = store.make_item(case["title"], case["text"], "Golden set")
        before = llm.usage()
        t0 = time.perf_counter()
        try:
            ins = await orchestrator.run(company, case["role"], news, f"req_golden_{uuid.uuid4().hex[:8]}", use_llm=use_llm)
            row = golden_metrics(case, news, ins)
        except Exception as exc:  # отказ разбора — провал кейса, а не прогона
            row = {"error": type(exc).__name__, "first_pass": False, "passed": False, "first_failed": [], "claims": 0,
                   "sourced": 0, "topic_match": False, "sign_match": False, "bank_ok": False if case["expect"]["bank_topic"] else None,
                   "forbidden_found": [], "effect": "error"}
        after = llm.usage()
        row.update(id=case["id"], expected_effect=case["expect"]["effect"], seconds=round(time.perf_counter() - t0, 2),
                   tokens=after["tokens"] - before["tokens"], cost=round(after["cost"] - before["cost"], 3))
        rows.append(row)
    n = len(rows)
    bank = [r["bank_ok"] for r in rows if r["bank_ok"] is not None]
    secs = [r["seconds"] for r in rows]
    summary = {
        "mode": mode, "n": n, "errors": sum(1 for r in rows if "error" in r),
        "first_pass_rate": round(sum(r["first_pass"] for r in rows) / n, 3),
        "pass_rate": round(sum(r["passed"] for r in rows) / n, 3),
        "sourced_rate": round(sum(r["sourced"] for r in rows) / max(sum(r["claims"] for r in rows), 1), 3),
        "topic_match": round(sum(r["topic_match"] for r in rows) / n, 3),
        "sign_match": round(sum(r["sign_match"] for r in rows) / n, 3),
        "bank_coverage": round(sum(bank) / len(bank), 3) if bank else None,
        "forbidden_ok": round(sum(not r["forbidden_found"] for r in rows) / n, 3),
        "first_fail_reasons": dict(Counter(c for r in rows for c in r["first_failed"]).most_common()),
        "latency_p50": _pct(secs, 0.5), "latency_p95": _pct(secs, 0.95),
        "tokens": sum(r["tokens"] for r in rows), "cost_rub": round(sum(r["cost"] for r in rows), 2),
    }
    return {"summary": summary, "rows": rows}


def golden_markdown(report: dict) -> str:
    s = report["summary"]
    pct = lambda x: "—" if x is None else f"{x * 100:.0f}%"
    lines = [f"Режим: **{s['mode']}**, кейсов: {s['n']}, ошибок разбора: {s['errors']}", "",
             "| Метрика | Значение |", "|---|---|",
             f"| Прошли проверки с первой попытки (first_pass_rate) | {pct(s['first_pass_rate'])} |",
             f"| Прошли финальные проверки | {pct(s['pass_rate'])} |",
             f"| Выводы с источником | {pct(s['sourced_rate'])} |",
             f"| Тема найдена | {pct(s['topic_match'])} |",
             f"| Знак эффекта совпал | {pct(s['sign_match'])} |",
             f"| Тезис банка по теме | {pct(s['bank_coverage'])} |",
             f"| Без запрещенных утверждений | {pct(s['forbidden_ok'])} |",
             f"| Задержка p50 / p95, с | {s['latency_p50']} / {s['latency_p95']} |",
             f"| Токены / стоимость LLM, ₽ | {s['tokens']} / {s['cost_rub']} |", "",
             "Причины провала первой попытки: " + (", ".join(f"{k} — {v}" for k, v in s["first_fail_reasons"].items()) or "нет"),
             "", "| Кейс | 1-я попытка | Эффект: ожидался → получен | Тезис банка | Замечания |", "|---|---|---|---|---|"]
    for r in report["rows"]:
        notes = r.get("error") or ", ".join(r["first_failed"] + [f"запрещено: {f}" for f in r["forbidden_found"]]
                                            + ([] if r["topic_match"] else ["тема не найдена"]))
        bank = "—" if r["bank_ok"] is None else "да" if r["bank_ok"] else "нет"
        lines.append(f"| {r['id']} | {'да' if r['first_pass'] else 'нет'} | {r['expected_effect']} → {r['effect']} | {bank} | {notes} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-set")
    ap.add_argument("--size", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--set")
    ap.add_argument("--mode", choices=["rules", "llm", "auto"], default="auto",
                    help="golden set: rules — без модели, llm — с моделью, auto — как в сервисе")
    ap.add_argument("--out")
    ap.add_argument("--md", help="golden set: markdown-таблица отчета")
    a = ap.parse_args()
    if a.make_set:
        items = make_set(a.size, a.seed)
        Path(a.make_set).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"eval set: {len(items)} items -> {a.make_set}")
        return
    raw = Path(a.set)
    if raw.is_dir() or "items" in json.loads(raw.read_text(encoding="utf-8")):
        report = asyncio.run(run_golden(load_golden(raw), a.mode))
        md = golden_markdown(report)
        print(md)
        if a.md:
            Path(a.md).write_text(md, encoding="utf-8")
    else:
        report = asyncio.run(run(json.loads(raw.read_text(encoding="utf-8"))))
    print(json.dumps(report["summary"], ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
