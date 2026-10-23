"""Предрасчет демо-сценария защиты: разборы готовы заранее и открываются из кэша.

    python -m app.precompute_demo --dry-run     # что будет построено и оценка стоимости, без вызовов
    python -m app.precompute_demo               # построить (с LLM, если подключена), напечатать время и стоимость
    python -m app.precompute_demo --max-cost 50  # не больше 50 ₽ на модель, остальное — правилами
    python -m app.precompute_demo --company U_26 --company U_7 --roles cfo,ceo,owner --top 5

По умолчанию — крупнейшие металлург и автодилер активного набора (сценарий из плана защиты),
три роли и пять лучших новостей ленты каждой роли. Идемпотентен: готовый актуальный разбор не
перестраивается (с подключенной LLM — только разбор моделью; разбор на правилах будет улучшен).
Бюджет защищен резервированием (app/llm_usage.py): при исчерпании разбор строится на правилах.
В конце каждый демо-разбор открывается из кэша с замером времени; дольше 2 с или не из кэша — ошибка.
"""

import argparse
import asyncio
import json
import time
import uuid

from app import config, database, llm_usage, ranking, storage
from app.agent import llm
from app.companies import profiles
from app.news import store

DEMO_SECTORS = ("metallurgy", "auto")
DEMO_ROLES = ("cfo", "ceo", "owner")
TOKENS_PER_INSIGHT = 15_000  # план, черновик, коррекция и смысловая проверка — по замерам eval_quality
CACHE_OPEN_LIMIT_S = 2.0  # критерий готовности: демо открывается из кэша не дольше 2 с


def demo_companies(ids: list[str] | None = None) -> list[dict]:
    if ids:
        found = [profiles.get(cid) for cid in ids]
        missing = [cid for cid, c in zip(ids, found) if c is None]
        if missing:
            raise SystemExit(f"Компании не найдены: {', '.join(missing)}")
        return found
    companies = profiles._load()["companies"]
    out = []
    for sector in DEMO_SECTORS:
        best = max((c for c in companies if c["sector"] == sector), key=lambda c: c.get("revenue") or 0, default=None)
        if best:
            out.append(best)
    return out


def plan(companies: list[dict], roles: list[str], top: int) -> list[dict]:
    """Пары «компания — роль — новость» и признак, нужен ли разбор (нет актуального кэша)."""
    use_llm = llm.available()
    items = []
    for company in companies:
        for role in roles:
            for r in ranking.company_feed(company["company_id"], role, 500)[:top]:
                cached = storage.cached_insight(company["company_id"], role, r["news"]["news_id"])
                ready = cached is not None and (cached["mode"] == "llm" or not use_llm or storage.llm_attempted(cached))
                items.append({"company_id": company["company_id"], "company": company["display_name"], "role": role,
                              "news_id": r["news"]["news_id"], "title": r["news"]["title"][:90], "ready": ready})
    return items


def check_cache(items: list[dict]) -> dict:
    """Критерий SPR2-03: каждый демо-разбор открывается из кэша не дольше CACHE_OPEN_LIMIT_S."""
    from app.schemas import Insight

    times, missing = [], []
    for it in items:
        t0 = time.perf_counter()
        cached = storage.cached_insight(it["company_id"], it["role"], it["news_id"])
        if cached is None:
            missing.append(it["news_id"])
            continue
        Insight.model_validate(cached)  # как ответ API
        times.append(time.perf_counter() - t0)
    times.sort()
    worst = times[-1] if times else 0.0
    return {"opened": len(times), "not_cached": len(missing), "p95_ms": round(times[int(0.95 * (len(times) - 1))] * 1000, 1) if times else None,
            "max_ms": round(worst * 1000, 1), "ok": not missing and worst <= CACHE_OPEN_LIMIT_S}


def per_insight_cost() -> float:
    """Оценка сверху стоимости одного разбора моделью (по цене модели черновика)."""
    model = config.llm_settings()["models"]["compose"]
    return round(TOKENS_PER_INSIGHT / 1000 * config.llm_price_per_1k(model), 2)


async def build(items: list[dict], max_cost: float | None = None) -> dict:
    """Строит недостающие разборы. max_cost, ₽ — сколько можно потратить на модель: когда следующий
    разбор может выйти за предел, остальные строятся правилами (бюджет живой демонстрации не трогается)."""
    from app.agent import orchestrator

    before, started = llm_usage.usage(), time.perf_counter()
    built, capped = [], False
    for it in items:
        if it["ready"]:
            continue
        spent = llm_usage.usage()["cost"] - before["cost"]
        capped = capped or (max_cost is not None and spent + per_insight_cost() > max_cost)
        t0 = time.perf_counter()
        ins = await orchestrator.run(profiles.get(it["company_id"]), it["role"], store.get(it["news_id"]),
                                     f"req_demo_{uuid.uuid4().hex[:12]}", use_llm=False if capped else None)
        storage.save_insight(ins)
        built.append({**it, "mode": ins["mode"], "effect": ins.get("effect"), "seconds": round(time.perf_counter() - t0, 1)})
        print(f"{ins['mode']:5} {built[-1]['seconds']:5.1f}s {it['role']:6} {it['company'][:30]:30} {it['title'][:50]}", flush=True)
    after = llm_usage.usage()
    return {"built": len(built), "already_ready": sum(it["ready"] for it in items), "items": built,
            "seconds": round(time.perf_counter() - started, 1), "llm_tokens": after["tokens"] - before["tokens"],
            "llm_cost_rub": round(after["cost"] - before["cost"], 2), "max_cost_reached": capped,
            "rejected_by_budget": after["rejected_by_budget"] - before["rejected_by_budget"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", action="append", help="id компании (можно несколько); по умолчанию металлург и автодилер")
    ap.add_argument("--roles", default=",".join(DEMO_ROLES))
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="только план и оценка стоимости, без разборов")
    ap.add_argument("--max-cost", type=float, help="не тратить на модель больше, ₽; остальное — правилами")
    a = ap.parse_args()
    database.migrate()
    store.all_items()
    items = plan(demo_companies(a.company), [r.strip() for r in a.roles.split(",") if r.strip()], a.top)
    todo = [it for it in items if not it["ready"]]
    estimate = round(len(todo) * per_insight_cost(), 2) if llm.available() else 0.0
    print(f"Демо: {len(items)} разборов, готово {len(items) - len(todo)}, построить {len(todo)}; "
          f"LLM {'подключена' if llm.available() else 'не подключена — правила'}, оценка сверху ≈ {estimate} ₽", flush=True)
    if a.dry_run:
        print(json.dumps({"planned": todo, "estimate_rub": estimate}, ensure_ascii=False, indent=2))
        return
    report = asyncio.run(build(items, a.max_cost))
    report["cache_open"] = check_cache(items)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["cache_open"]["ok"]:
        raise SystemExit(f"Демо открывается из кэша медленнее {CACHE_OPEN_LIMIT_S} с или не из кэша")


if __name__ == "__main__":
    main()
