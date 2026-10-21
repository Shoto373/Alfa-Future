"""Агент подготовки персонализированного инсайта.

Цикл:
  1. plan      — определить, какие данные и инструменты нужны (LLM или правила);
  2. tool      — выполнить инструменты, результаты сложить в общий контекст;
  3. compose   — черновик интерпретации (LLM по JSON-схеме или правила);
  4. check     — самопроверка: полнота, источники, цифры, противоречия;
  5. adapt     — при провале: расширить поиск, убрать неподтвержденное,
                 дополнить правилами; затем повторная проверка (до 2 раз);
  6. finalize  — карточка с источниками, признаками и трассой шагов.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from app.agent import composer, llm, prompts, validators
from app.agent.tools import REGISTRY, ToolError, ToolRunner
from app.companies.sectors import SECTOR_NAMES
from app.errors import AnalysisUnavailable
from app.ranking import score
from app.schemas import SCHEMA_VERSION, Insight

logger = logging.getLogger("app.agent")
MAX_ADAPT_ROUNDS = 2
DISCLAIMER = ("Прототип для хакатона. Данные о компаниях обезличены, новости демо-ленты пересказывают материалы кейса. "
              "Материал не является инвестиционной рекомендацией. Выводы с пометкой «AI» сформированы автоматически.")

FEATURE_LABELS = {
    "sector": "Отрасль", "products.loans": "Кредитные продукты", "products.leasing": "Лизинг",
    "products.deposits": "Депозиты", "products.factoring": "Факторинг", "products.guarantees": "Банковские гарантии",
    "workers_fns": "Численность (ФНС)", "fts_countries": "Страны ВЭД (ФТС)", "revenue": "Выручка",
    "suppliers.by_sector": "Отрасли поставщиков", "customers.by_sector": "Отрасли покупателей",
    "suppliers.top1_share": "Концентрация поставщиков", "market": "Место в отрасли (выборка)",
}


class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, stage: str, name: str, detail: str, status: str = "ok", duration_ms: float = 0.0, output=None):
        self.steps.append({"step": len(self.steps) + 1, "stage": stage, "name": name, "detail": detail[:400],
                           "status": status, "duration_ms": round(duration_ms, 1), "output": output})


def _rules_plan(news: dict, company: dict) -> list[dict]:
    topics = [t["topic"] for t in news["classification"]["topics"]]
    query = f"{news['title']} {news['lead']}"
    plan = [
        {"tool": "get_company_profile", "args": {"company_id": company["company_id"]}, "why": "контекст компании"},
        {"tool": "get_exposures", "args": {"company_id": company["company_id"], "topics": topics},
         "why": "через какие признаки событие касается компании"},
        {"tool": "search_bank_analytics", "args": {"query": query, "topics": topics, "sectors": [company["sector"]] + news["classification"]["sectors"]},
         "why": "позиция и прогнозы Альфа-Банка по теме"},
        {"tool": "check_forecast_conflicts", "args": {"topics": topics[:2]}, "why": "сверить прогнозы банка из разных материалов"},
        {"tool": "get_bank_products", "args": {"company_id": company["company_id"], "topics": topics}, "why": "релевантные решения банка"},
    ]
    if {"imports_exports", "fx", "sanctions_geopolitics", "corporate_finance", "fuel_oil"} & set(topics):
        plan.insert(2, {"tool": "get_counterparties", "args": {"company_id": company["company_id"]},
                        "why": "событие может прийти через цепочку поставок"})
    plan.append({"tool": "find_related_news", "args": {"news_id": news["news_id"], "topics": topics}, "why": "связанные события"})
    return plan


def _llm_plan(news: dict, company: dict) -> tuple[list[dict], dict]:
    data, meta = llm.chat_json(prompts.PLAN_SYSTEM, prompts.plan_user(news, company, REGISTRY), "fast", 800)
    steps = []
    for s in data.get("steps", [])[:10]:
        if isinstance(s, dict) and s.get("tool") in REGISTRY and isinstance(s.get("args", {}), dict):
            steps.append({"tool": s["tool"], "args": s.get("args", {}), "why": str(s.get("why", ""))[:200]})
    if not any(s["tool"] == "search_bank_analytics" for s in steps):
        raise llm.LLMError("План не содержит поиска по аналитике банка")
    return steps, meta


def _sources(ctx: dict) -> list[dict]:
    news = ctx["news"]
    out = [{"source_id": f"news:{news['news_id']}", "kind": "news", "title": news["title"], "url": news.get("url"),
            "date": news["published_at"][:10], "excerpt": news["lead"][:300], "doc_id": None, "page": None}]
    for t in ctx["theses"]:
        out.append({"source_id": f"bank:{t['id']}", "kind": "bank_analytics", "title": t["doc_title"], "doc_id": t["doc_id"],
                    "page": t["page"], "date": t["doc_date"], "excerpt": t["text"][:300], "url": None})
    c = ctx["company"]
    out.append({"source_id": "client:profile", "kind": "client_data", "title": f"Профиль {c['display_name']} (данные кейса)",
                "excerpt": f"{c['okved_code']} {c['okved_name']}; регион {c['region']}", "url": None, "doc_id": None, "page": None, "date": None})
    out.append({"source_id": "client:payments", "kind": "client_data", "title": "Платежи компании (данные кейса)",
                "excerpt": f"Поставщиков: {c['suppliers']['counterparties']}, покупателей: {c['customers']['counterparties']}",
                "url": None, "doc_id": None, "page": None, "date": None})
    for p in ctx.get("products", []):
        out.append({"source_id": f"product:{p['id']}", "kind": "bank_product", "title": p["title"], "excerpt": p["text"],
                    "url": None, "doc_id": None, "page": None, "date": None})
    return out


def _grounding_text(ctx: dict) -> str:
    c = ctx["company"]
    parts = [ctx["news"]["title"], ctx["news"]["text"]] + [t["text"] for t in ctx["theses"]]
    m = c["market"]
    parts += [str(m.get("okved_rank")), str(m.get("okved_peers")), c.get("okved_code") or "", composer.pct(m.get('okved_share') or 0),
              f"{(c.get('revenue') or 0) / 1e9:.1f}", c.get("workers_fns") or ""]
    parts += [composer.pct(s['share'], 0) for side in ("suppliers", "customers") for s in c[side]["by_sector"]]
    if c["suppliers"]["top1_share"]:
        parts.append(composer.pct(c['suppliers']['top1_share'], 0))
    parts += ["14%", "2026", "2027", "4К26", "3–6", "6"]  # горизонты из шаблонов действий
    return " ".join(parts)


def _features(ctx: dict, draft: dict) -> list[dict]:
    c = ctx["company"]
    used = {f for sec in ("why_important", "risks", "opportunities") for cl in draft[sec] for f in cl.get("features", [])}
    values = {
        "sector": c["sector_name"], "products.loans": "есть" if c["products"].get("loans") else "нет",
        "products.leasing": "есть" if c["products"].get("leasing") else "нет",
        "products.deposits": "есть" if c["products"].get("deposits") else "нет",
        "products.factoring": "есть" if c["products"].get("factoring") else "нет",
        "products.guarantees": "есть" if c["products"].get("guarantees") else "нет",
        "workers_fns": c.get("workers_fns") or "н/д", "fts_countries": ", ".join(c["fts_countries"]) or "нет данных",
        "revenue": f"{(c.get('revenue') or 0) / 1e9:.1f} млрд ₽",
        "suppliers.by_sector": ", ".join(f"{SECTOR_NAMES.get(s['sector'], 'вне выборки')} {s['share']:.0%}" for s in c["suppliers"]["by_sector"][:3]) or "нет данных",
        "customers.by_sector": ", ".join(f"{SECTOR_NAMES.get(s['sector'], 'вне выборки')} {s['share']:.0%}" for s in c["customers"]["by_sector"][:3]) or "нет данных",
        "suppliers.top1_share": f"{(c['suppliers']['top1_share'] or 0):.0%}",
        "market": f"№{c['market'].get('okved_rank')} из {c['market'].get('okved_peers')} по ОКВЭД {c['okved_code']}",
    }
    return [{"name": f, "label": FEATURE_LABELS.get(f, f), "value": values.get(f, "—")} for f in sorted(used) if f in values]


def _merge_llm(draft: dict, data: dict) -> dict:
    """Переносит в черновик разделы из ответа LLM, сохраняя структуру Claim."""
    def claims(items, default_origin="ai"):
        out = []
        for it in items or []:
            if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
                origin = it.get("origin") if it.get("origin") in ("fact", "client_data", "bank", "ai") else default_origin
                out.append({"text": it["text"].strip()[:600], "origin": origin,
                            "source_ids": [str(s) for s in it.get("source_ids", [])][:6],
                            "features": [str(f) for f in it.get("features", [])][:6]})
        return out

    for key in ("why_important", "risks", "opportunities", "actions"):
        if data.get(key):
            draft[key] = claims(data[key])
    if isinstance(data.get("headline"), str) and data["headline"].strip():
        draft["headline"] = data["headline"].strip()[:400]
    if data.get("facts"):
        draft["what_happened"]["facts"] = claims(data["facts"], "fact")
    if data.get("assumptions"):
        draft["what_happened"]["assumptions"] = claims(data["assumptions"])
    if isinstance(data.get("bank_summary"), str):
        draft["bank_view"]["summary"] = data["bank_summary"][:600]
    if data.get("questions"):
        draft["questions"] = [str(q)[:300] for q in data["questions"]][:4]
    return draft


async def run(company: dict, role: str, news: dict, request_id: str) -> dict:
    trace = Trace()
    runner = ToolRunner(request_id)
    use_llm = llm.available()
    model = None
    started = time.perf_counter()

    # 1. План.
    t0 = time.perf_counter()
    plan, plan_source = _rules_plan(news, company), "rules"
    if use_llm:
        try:
            plan, meta = _llm_plan(news, company)
            plan_source, model = "llm", meta["model"]
        except llm.LLMError as exc:
            trace.add("plan", "llm_plan", f"LLM-план не получен ({exc}); используется план на правилах", "warning")
    trace.add("plan", "plan", f"План ({plan_source}): " + " → ".join(s["tool"] for s in plan), "ok",
              (time.perf_counter() - t0) * 1000, {"steps": [{"tool": s["tool"], "why": s["why"]} for s in plan]})

    # 2. Инструменты -> общий контекст.
    ctx = {"news": news, "company": company, "role": role, "exposures": [], "theses": [], "products": [],
           "forecast_conflicts": [], "counterparties": None, "related": []}
    for step in plan:
        try:
            result, ms = runner.call(step["tool"], **step["args"])
        except ToolError as exc:
            trace.add("tool", step["tool"], f"{step['why']}: ошибка — {exc}", "error")
            continue
        summary = ""
        if step["tool"] == "get_exposures":
            ctx["exposures"] = list(result)
            summary = f"найдено экспозиций: {len(result)}"
        elif step["tool"] == "search_bank_analytics":
            ctx["theses"] = result
            summary = "тезисы: " + ", ".join(t["id"] for t in result) if result else "материалы не найдены"
        elif step["tool"] == "get_bank_products":
            ctx["products"] = result
            summary = f"продуктов: {len(result)}"
        elif step["tool"] == "check_forecast_conflicts":
            ctx["forecast_conflicts"] = result
            summary = f"тем с несколькими прогнозами: {len(result)}"
        elif step["tool"] == "get_counterparties":
            ctx["counterparties"] = result
            summary = f"поставщиков {result['suppliers']['counterparties']}, покупателей {result['customers']['counterparties']}"
        elif step["tool"] == "find_related_news":
            ctx["related"] = result
            summary = f"связанных новостей: {len(result)}"
        else:
            summary = "получено"
        trace.add("tool", step["tool"], f"{step['why']}: {summary}", "ok", ms)

    # 3. Черновик.
    t0 = time.perf_counter()
    draft = composer.compose(ctx)
    mode = "rules"
    if use_llm:
        try:
            data, meta = llm.chat_json(prompts.COMPOSE_SYSTEM, prompts.compose_user(ctx, _sources(ctx)), "reasoning", 2500)
            draft = _merge_llm(draft, data)
            mode, model = "llm", meta["model"]
            trace.add("compose", "llm_compose", f"Черновик модели {meta['model']}, токенов {meta['tokens']}", "ok", meta["duration_ms"])
        except llm.LLMError as exc:
            trace.add("compose", "llm_compose", f"LLM недоступна ({exc}); черновик на правилах", "warning")
    if mode == "rules":
        trace.add("compose", "rules_compose", "Черновик составлен правилами: эффект = чувствительность компании × направление события",
                  "ok", (time.perf_counter() - t0) * 1000)

    # 4–5. Самопроверка и адаптация.
    attempts = 1
    for round_no in range(MAX_ADAPT_ROUNDS + 1):
        sources = _sources(ctx)
        source_ids = {s["source_id"] for s in sources}
        grounding = _grounding_text(ctx)
        results = validators.check(draft, ctx, source_ids, grounding)
        failed = [r for r in results if not r["passed"]]
        trace.add("check", f"self_check_{round_no + 1}",
                  "Все проверки пройдены" if not failed else "Не пройдено: " + ", ".join(r["name"] for r in failed),
                  "ok" if not failed else "warning", 0, {"checks": [{k: r[k] for k in ("name", "passed")} for r in results]})
        if not failed or round_no == MAX_ADAPT_ROUNDS:
            break
        attempts += 1
        actions = []
        fixes = {r["fix"] for r in failed}
        if "broaden_search" in fixes:
            try:
                wider, ms = runner.call("search_bank_analytics", query=news["text"][:600], topics=[], sectors=[], include_stale=True)
                ctx["theses"] = wider
                rebuilt = composer.compose(ctx)
                draft["bank_view"] = rebuilt["bank_view"]
                actions.append(f"расширен поиск по аналитике банка: {len(wider)} тезисов")
            except ToolError as exc:
                actions.append(f"расширить поиск не удалось: {exc}")
        if "fill_from_rules" in fixes:
            rebuilt = composer.compose(ctx)
            for key in ("why_important", "risks", "opportunities", "actions"):
                if not draft[key] or len({f for c in draft[key] for f in c.get("features", [])}) < 1:
                    draft[key] = rebuilt[key]
            if validators.similarity(draft["headline"], news["title"]) > 0.5:
                draft["headline"] = rebuilt["headline"]
            actions.append("разделы дополнены правилами")
        actions += validators.apply_fix(draft, failed, {s["source_id"] for s in _sources(ctx)}, _grounding_text(ctx))
        trace.add("adapt", f"adapt_{round_no + 1}", "; ".join(actions) or "исправления не потребовались", "ok")

    final_checks = results
    quality = {"passed": all(r["passed"] for r in final_checks), "attempts": attempts,
               "checks": [{"name": r["name"], "passed": r["passed"], "detail": r["detail"]} for r in final_checks]}

    # 6. Итог.
    used_ids = {s for sec in ("why_important", "risks", "opportunities", "actions") for c in draft[sec] for s in c["source_ids"]}
    used_ids |= {s for c in draft["bank_view"]["theses"] + draft["what_happened"]["facts"] for s in c["source_ids"]}
    used_ids |= {f"product:{p['product_id']}" for p in draft["products"]}
    sources = [s for s in _sources(ctx) if s["source_id"] in used_ids]
    relevance = score(news, company["company_id"], role)
    trace.add("finalize", "finalize", f"Источников: {len(sources)}, режим: {mode}, всего {(time.perf_counter() - started) * 1000:.0f} мс")

    insight = {
        "schema_version": SCHEMA_VERSION,
        "insight_id": f"ins-{uuid.uuid4().hex[:12]}",
        "request_id": request_id,
        "company_id": company["company_id"],
        "role": role,
        "news_id": news["news_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "model": model,
        "title": draft["title"],
        "headline": draft["headline"],
        "what_happened": draft["what_happened"],
        "why_important": draft["why_important"],
        "risks": draft["risks"],
        "opportunities": draft["opportunities"],
        "actions": draft["actions"],
        "questions": draft["questions"],
        "bank_view": draft["bank_view"],
        "products": draft["products"],
        "features_used": _features(ctx, draft),
        "relevance": {"score": relevance["score"], "reasons": [
            {k: r.get(k) for k in ("kind", "feature", "origin", "weight", "text", "topic")} for r in relevance["reasons"]]},
        "sources": sources,
        "quality": quality,
        "trace": trace.steps,
        "disclaimer": DISCLAIMER,
    }
    try:
        return Insight.model_validate(insight).model_dump()
    except Exception as exc:  # pragma: no cover - защитный барьер
        logger.exception("insight failed schema validation request_id=%s", request_id)
        raise AnalysisUnavailable("Карточка не прошла проверку схемы") from exc

