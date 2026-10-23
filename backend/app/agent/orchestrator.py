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
import asyncio
import copy
import time
import uuid
from datetime import datetime, timezone

from app.agent import composer, llm, prompts, review, validators
from app.agent.tools import ToolError, ToolRunner
from app.companies.sectors import SECTOR_NAMES
from app.errors import AnalysisUnavailable
from app.news.taxonomy import TOPICS
from app.ranking import ROLES, score
from app.schemas import SCHEMA_VERSION, Insight

logger = logging.getLogger("app.agent")
MAX_ADAPT_ROUNDS = 2
DISCLAIMER = ("Прототип для хакатона. Данные о компаниях обезличены, новости демо-ленты пересказывают материалы кейса. "
              "Материал не является инвестиционной рекомендацией. Выводы с пометкой «AI» сформированы автоматически.")

FEATURE_LABELS = {
    "products.payroll": "Зарплатный проект",
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


MAX_EXTRA_QUERIES = 3
MAX_THESES = 8  # тезисов банка в контексте модели после основного и уточняющих поисков


def _rules_plan(news: dict, company: dict) -> list[dict]:
    """Обязательные шаги: без них разбор не опирается на данные компании, контрагентов и банка."""
    topics = [t["topic"] for t in news["classification"]["topics"]]
    query = f"{news['title']} {news['lead']}"
    cid = company["company_id"]
    return [
        {"tool": "get_company_profile", "args": {"company_id": cid}, "why": "контекст компании"},
        {"tool": "get_exposures", "args": {"company_id": cid, "topics": topics},
         "why": "через какие признаки событие касается компании"},
        {"tool": "get_counterparties", "args": {"company_id": cid}, "why": "событие может прийти через цепочку поставок"},
        {"tool": "search_bank_analytics", "args": {"query": query, "topics": topics,
                                                   "sectors": [company["sector"]] + news["classification"]["sectors"]},
         "why": "позиция и прогнозы Альфа-Банка по теме"},
        {"tool": "check_forecast_conflicts", "args": {"topics": topics[:2]}, "why": "сверить прогнозы банка из разных материалов"},
        {"tool": "get_story_history", "args": {"news_id": news["news_id"]}, "why": "тренд или разовое событие"},
        {"tool": "get_story_coverage", "args": {"news_id": news["news_id"]}, "why": "сверить факты с другими источниками"},
        {"tool": "get_bank_products", "args": {"company_id": cid, "topics": topics}, "why": "релевантные решения банка"},
    ]


def _llm_queries(news: dict, company: dict, role: str) -> tuple[list[dict], dict]:
    """Модель-исследователь предлагает уточняющие запросы к аналитике банка — только в темах новости."""
    data, meta = llm.chat_json(prompts.PLAN_SYSTEM, prompts.plan_user(news, company, role), "plan", 1500)
    raw = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise llm.LLMError("План модели не содержит списка запросов")
    allowed = {t["topic"] for t in news["classification"]["topics"]}
    queries = []
    for q in raw[:MAX_EXTRA_QUERIES]:
        if not isinstance(q, dict) or not isinstance(q.get("query"), str) or not q["query"].strip():
            continue
        topics = [t for t in q.get("topics", []) if isinstance(t, str) and t in allowed] if isinstance(q.get("topics"), list) else []
        if allowed and not topics:
            topics = sorted(allowed)
        if not topics:  # у события нет бизнес-тем — модель не может «притянуть» материалы банка
            continue
        queries.append({"tool": "search_bank_analytics", "why": str(q.get("why", "уточняющий запрос"))[:200],
                        "args": {"query": q["query"].strip()[:300], "topics": topics,
                                 "sectors": [company["sector"]] + news["classification"]["sectors"], "include_stale": False}})
    return queries, meta


def _sources(ctx: dict) -> list[dict]:
    news = ctx["news"]
    out = [{"source_id": f"news:{news['news_id']}", "kind": "news", "title": news["title"], "url": news.get("url"),
            "date": news["published_at"][:10], "excerpt": news["lead"][:300], "doc_id": None, "page": None}]
    for n in ctx.get("story", []):
        out.append({"source_id": f"news:{n['news_id']}", "kind": "news", "title": n["title"], "url": None,
                    "date": n["published_at"][:10], "excerpt": n["lead"][:300], "doc_id": None, "page": None})
    for n in ctx.get("coverage", []):
        out.append({"source_id": f"news:{n['news_id']}", "kind": "news", "title": f"{n['source']}: {n['title']}",
                    "url": n.get("url"), "date": n["published_at"][:10], "excerpt": n["lead"][:300], "doc_id": None, "page": None})
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


def _llm_repair(draft: dict, ctx: dict, source_ids: set[str]) -> dict | None:
    """Модель исправляет только утверждения с ошибками проверки (а не весь черновик).

    Возвращает {status, detail} для трассы или None, если исправлять нечего.
    Ответ модели не принимается на веру: после замены черновик проходит те же проверки.
    """
    from app.agent import evidence

    sections = [("why_important", draft["why_important"]), ("risks", draft["risks"]),
                ("opportunities", draft["opportunities"]), ("actions", draft["actions"]),
                ("what_happened", draft["what_happened"]["facts"]), ("what_happened", draft["what_happened"]["assumptions"])]
    bad, where = [], {}
    for section, items in sections:
        for idx, c in enumerate(items):
            errors = validators.claim_errors(section, c, ctx, source_ids)
            if errors:
                where[len(bad)] = (items, idx)
                bad.append({"id": len(bad), "section": section, "claim": c, "errors": errors})
    if not bad:
        return None
    texts = {sid: t for sid, t in evidence.source_texts(ctx).items() if sid in source_ids}
    features = sorted(evidence.valid_features(ctx["company"]))
    try:
        data, meta = llm.chat_json(prompts.REPAIR_SYSTEM, prompts.repair_user(bad, texts, features), "review", 2500)
    except llm.LLMError as exc:
        return {"status": "warning", "detail": f"Исправление моделью недоступно ({exc}); неподтвержденное будет удалено"}
    fixed = dropped = 0
    drop: list[tuple[list, int]] = []
    for item in data.get("claims", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("id") not in where:
            continue
        items, idx = where[item["id"]]
        if item.get("drop"):
            drop.append((items, idx))
            dropped += 1
            continue
        text, origin, ids = item.get("text"), item.get("origin"), item.get("source_ids")
        if isinstance(text, str) and text.strip() and origin in ("fact", "client_data", "bank", "ai")                 and isinstance(ids, list) and all(isinstance(x, str) for x in ids):
            feats = [f for f in item.get("features") or [] if isinstance(f, str)]
            items[idx] = {"text": text.strip()[:400], "origin": origin, "source_ids": ids[:5], "features": feats[:6]}
            fixed += 1
    for items, idx in sorted(drop, key=lambda d: -d[1]):
        items.pop(idx)
    return {"status": "ok", "detail": f"Модель {meta['model']} исправила утверждений: {fixed}, убрала: {dropped} "
                                      f"(из {len(bad)} с ошибками)"}


def _grounding_text(ctx: dict) -> str:
    c = ctx["company"]
    parts = [ctx["news"]["title"], ctx["news"]["text"]] + [t["text"] for t in ctx["theses"]]
    parts += [f"{n['title']} {n['lead']}" for n in ctx.get("story", []) + ctx.get("coverage", [])]
    m = c["market"]
    parts += [str(m.get("okved_rank")), str(m.get("okved_peers")), c.get("okved_code") or "", composer.pct(m.get('okved_share') or 0),
              f"{(c.get('revenue') or 0) / 1e9:.1f}", c.get("workers_fns") or ""]
    parts += [composer.pct(s['share'], 0) for side in ("suppliers", "customers") for s in c[side]["by_sector"]]
    if c["suppliers"]["top1_share"]:
        parts.append(composer.pct(c['suppliers']['top1_share'], 0))
    parts += [c["company_id"]]
    return " ".join(parts)


def _features(ctx: dict, draft: dict) -> list[dict]:
    c = ctx["company"]
    used = {f for sec in ("why_important", "risks", "opportunities") for cl in draft[sec] for f in cl.get("features", [])}
    values = {
        "products.payroll": "есть" if c["products"].get("payroll") else "нет данных",
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
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
                origin = it.get("origin") if it.get("origin") in ("fact", "client_data", "bank", "ai") else default_origin
                out.append({"text": it["text"].strip()[:600], "origin": origin,
                            "source_ids": [str(s) for s in it.get("source_ids", [])][:6] if isinstance(it.get("source_ids"), list) else [],
                            "features": [str(f) for f in it.get("features", [])][:6] if isinstance(it.get("features"), list) else []})
        return out

    rules_why = [c for c in draft["why_important"] if c["origin"] == "client_data"]
    for key in ("why_important", "risks", "opportunities", "actions"):
        if data.get(key):
            draft[key] = claims(data[key])
    # «Почему это важно» всегда сохраняет признаки компании из профиля: выводы модели
    # дополняются ими, чтобы связь с данными клиента оставалась трассируемой.
    texts = {c["text"] for c in draft["why_important"]}
    draft["why_important"] = [c for c in rules_why[:2] if c["text"] not in texts] + draft["why_important"][:4]
    # Keep the evidence-based summary from the composer. A free-form model
    # headline has no per-claim citations and cannot be independently grounded.
    if data.get("facts"):
        draft["what_happened"]["facts"] = claims(data["facts"], "fact")
    if data.get("assumptions"):
        # Оценка силы события — из чисел новости по правилам, модель ее не заменяет.
        strength = [c for c in draft["what_happened"]["assumptions"] if c["text"].startswith("Масштаб изменения")]
        draft["what_happened"]["assumptions"] = strength + claims(data["assumptions"])
    # The bank summary remains a reviewed thesis. Free model text cannot become
    # the bank's position just because it is placed in the bank_summary field.
    if isinstance(data.get("questions"), list):
        draft["questions"] = [str(q)[:300] for q in data["questions"]][:4]
    return draft


async def run(company: dict, role: str, news: dict, request_id: str, use_llm: bool | None = None) -> dict:
    """use_llm=False — только правила (быстрый черновой разбор), None — LLM, если подключена."""
    trace = Trace()
    runner = ToolRunner(request_id)
    use_llm = llm.available() if use_llm is None else (use_llm and llm.available())
    model = None
    started = time.perf_counter()

    # 1. План: обязательные шаги сразу, модель-исследователь параллельно придумывает уточняющие запросы.
    t0 = time.perf_counter()
    plan = _rules_plan(news, company)
    planner = asyncio.create_task(asyncio.to_thread(_llm_queries, news, company, role)) if use_llm else None
    trace.add("plan", "plan", "Обязательные шаги: " + " → ".join(s["tool"] for s in plan), "ok",
              (time.perf_counter() - t0) * 1000, {"steps": [{"tool": s["tool"], "why": s["why"]} for s in plan]})

    # 2. Инструменты -> общий контекст.
    ctx = {"news": news, "company": company, "role": role, "exposures": [], "theses": [], "products": [],
           "forecast_conflicts": [], "counterparties": None, "story": [], "coverage": [], "bank_search_complete": False,
           "role_focus": [TOPICS[t]["name"] for t, w in sorted(ROLES.get(role, ROLES["ceo"])["focus"].items(),
                                                              key=lambda kv: -kv[1]) if t in TOPICS]}

    def run_step(step: dict) -> None:
        try:
            result, ms = runner.call(step["tool"], **step["args"])
        except ToolError as exc:
            trace.add("tool", step["tool"], f"{step['why']}: ошибка — {exc}", "error")
            return
        summary = ""
        if step["tool"] == "get_exposures":
            event_topics = {t["topic"] for t in news["classification"]["topics"]}
            ctx["exposures"] = [e for e in result if e["topic"] in event_topics]
            summary = f"найдено экспозиций: {len(result)}"
        elif step["tool"] == "search_bank_analytics":
            known = {t["id"] for t in ctx["theses"]}
            fresh = [t for t in result if not t.get("stale") and t["id"] not in known]
            ctx["theses"] = (ctx["theses"] + fresh)[:MAX_THESES]
            ctx["bank_search_complete"] = True
            summary = ("тезисы: " + ", ".join(t["id"] for t in result) + (f" (новых {len(fresh)})" if known else "")) \
                if result else "материалы не найдены"
        elif step["tool"] == "get_bank_products":
            ctx["products"] = result
            summary = f"продуктов: {len(result)}"
        elif step["tool"] == "check_forecast_conflicts":
            ctx["forecast_conflicts"] = result
            summary = f"тем с несколькими прогнозами: {len(result)}"
        elif step["tool"] == "get_counterparties":
            ctx["counterparties"] = result
            summary = f"поставщиков {result['suppliers']['counterparties']}, покупателей {result['customers']['counterparties']}"
        elif step["tool"] == "get_story_coverage":
            seen = {n["news_id"] for n in ctx["story"]}
            ctx["coverage"] = [n for n in result if n["news_id"] not in seen]
            summary = (f"то же событие в других источниках: {', '.join(n['source'] for n in ctx['coverage'])}"
                       if ctx["coverage"] else "других источников по событию нет")
        elif step["tool"] == "get_story_history":
            ctx["story"] = result
            summary = (f"ранее по сюжету: {len(result)}, последнее {result[0]['published_at']}" if result
                       else "предыдущих событий сюжета нет")
        else:
            summary = "получено"
        trace.add("tool", step["tool"], f"{step['why']}: {summary}", "ok", ms,
                  {"args": {k: v for k, v in step["args"].items() if k != "company_id"}})

    def run_steps(steps: list[dict]) -> None:
        for step in steps:
            run_step(step)

    # Инструменты читают БД и векторное хранилище — в потоке, чтобы не блокировать другие запросы.
    await asyncio.to_thread(run_steps, plan)
    if planner:
        try:
            extra, meta = await planner
            trace.add("plan", "llm_queries", f"Модель {meta['model']} предложила запросов: {len(extra)}" +
                      ("".join(f"; «{q['args']['query']}» — {q['why']}" for q in extra)), "ok", meta["duration_ms"])
            await asyncio.to_thread(run_steps, extra)
        except llm.LLMError as exc:
            trace.add("plan", "llm_queries", f"Уточняющие запросы модели не получены ({exc}); достаточно обязательных шагов", "warning")

    # 3. Черновик.
    t0 = time.perf_counter()
    draft = composer.compose(ctx)
    mode = "rules"
    fallback_reason = None  # почему модель не дала итог: budget | unavailable | checks — для плашки в карточке
    if use_llm:
        try:
            data, meta = await asyncio.to_thread(llm.chat_json, prompts.COMPOSE_SYSTEM, prompts.compose_user(ctx, _sources(ctx)), "compose", 8000)
            draft = _merge_llm(draft, data)
            mode, model = "llm", meta["model"]
            trace.add("compose", "llm_compose", f"Черновик модели {meta['model']}, токенов {meta['tokens']}", "ok", meta["duration_ms"])
        except llm.LLMError as exc:
            fallback_reason = "budget" if isinstance(exc, llm.BudgetError) else "unavailable"
            trace.add("compose", "llm_compose", f"LLM недоступна ({exc}); черновик на правилах", "warning")
    if mode == "rules":
        trace.add("compose", "rules_compose", "Черновик составлен правилами: эффект = чувствительность компании × направление события",
                  "ok", (time.perf_counter() - t0) * 1000)

    # 4–5. Самопроверка и адаптация.
    attempts = 1
    repaired = False
    for round_no in range(MAX_ADAPT_ROUNDS + 1):
        sources = _sources(ctx)
        source_ids = {s["source_id"] for s in sources}
        grounding = _grounding_text(ctx)
        results = validators.check(draft, ctx, source_ids, grounding)
        failed = [r for r in results if not r["passed"]]
        # Типы ошибок по утверждениям — для мониторинга качества черновиков (какие правила модель нарушает чаще).
        claim_errors: dict[str, int] = {}
        for section, c in validators._claims(draft):
            for err in validators.claim_errors(section, c, ctx, source_ids):
                claim_errors[err] = claim_errors.get(err, 0) + 1
        trace.add("check", f"self_check_{round_no + 1}",
                  "Все проверки пройдены" if not failed else "Не пройдено: " + ", ".join(r["name"] for r in failed),
                  "ok" if not failed else "warning", 0, {"checks": [{k: r[k] for k in ("name", "passed")} for r in results],
                                                         "claim_errors": claim_errors})
        if not failed or round_no == MAX_ADAPT_ROUNDS:
            break
        attempts += 1
        actions = []
        fixes = {r["fix"] for r in failed}
        if mode == "llm" and not repaired:
            repaired = True
            t1 = time.perf_counter()
            outcome = await asyncio.to_thread(_llm_repair, draft, ctx, source_ids)
            if outcome:
                trace.add("adapt", "llm_repair", outcome["detail"], outcome["status"], (time.perf_counter() - t1) * 1000)
                if outcome["status"] == "ok":
                    actions.append(outcome["detail"])
                    # Исправленный черновик проверяется заново; удаление — только если ошибки остались.
                    sources = _sources(ctx)
                    source_ids = {s["source_id"] for s in sources}
                    results = validators.check(draft, ctx, source_ids, _grounding_text(ctx))
                    failed = [r for r in results if not r["passed"]]
                    fixes = {r["fix"] for r in failed}
        if "broaden_search" in fixes:
            try:
                wider, ms = await asyncio.to_thread(
                    runner.call, "search_bank_analytics", query=news["text"][:600],
                    topics=[t["topic"] for t in news["classification"]["topics"]], sectors=[], include_stale=False)
                ctx["theses"] = wider
                ctx["bank_search_complete"] = True
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
            # Факты «Что произошло» — дословные предложения новости; если проверка их сняла, берутся из правил.
            if not draft["what_happened"]["facts"]:
                draft["what_happened"]["facts"] = rebuilt["what_happened"]["facts"]
            if validators.similarity(draft["headline"], news["title"]) > 0.5:
                draft["headline"] = rebuilt["headline"]
            actions.append("разделы дополнены правилами")
        actions += validators.apply_fix(draft, failed, {s["source_id"] for s in _sources(ctx)}, _grounding_text(ctx), ctx)
        trace.add("adapt", f"adapt_{round_no + 1}", "; ".join(actions) or "исправления не потребовались", "ok")

    if any(not r["passed"] for r in results):
        # Never return known-invalid output after exhausting bounded corrections.
        if mode == "llm":
            fallback_reason = "checks"
        draft = composer.compose(ctx)
        mode, model = "rules", None
        results = validators.check(draft, ctx, {s["source_id"] for s in _sources(ctx)}, _grounding_text(ctx))
        trace.add("adapt", "safe_fallback", "Лимит коррекций исчерпан; повторно проверен разбор на правилах", "warning")
        if any(not r["passed"] for r in results):
            logger.warning("analysis rejected request_id=%s checks=%s", request_id,
                           [r["name"] for r in results if not r["passed"]])
            raise AnalysisUnavailable("Не удалось подготовить подтвержденный разбор")
    final_checks = list(results)

    # 5a. Смысловая проверка выводов AI второй моделью (только для текста модели).
    if mode == "llm":
        t0 = time.perf_counter()
        backup = copy.deepcopy(draft)
        try:
            outcome = await asyncio.to_thread(review.review, draft, ctx, _sources(ctx))
            recheck = validators.check(draft, ctx, {s["source_id"] for s in _sources(ctx)}, _grounding_text(ctx))
            if any(not r["passed"] for r in recheck):
                draft = backup
                detail = "Критик предложил убрать выводы, но разбор без них не прошел проверки — оставлен прежний"
            else:
                final_checks = list(recheck)
                detail = (f"Проверено выводов AI: {outcome['reviewed']}; подтверждено {outcome['supported']}, "
                          f"частично {outcome['partial']}, убрано {len(outcome['removed'])}")
                if outcome["removed"]:
                    detail += ": " + "; ".join(outcome["removed"])
            final_checks.append({"name": "semantic_review", "passed": True, "detail": detail[:400]})
            trace.add("check", "semantic_review", detail, "ok", (time.perf_counter() - t0) * 1000)
        except llm.LLMError as exc:
            draft = backup
            trace.add("check", "semantic_review", f"Смысловая проверка недоступна ({exc}); остаются детерминированные проверки",
                      "warning", (time.perf_counter() - t0) * 1000)
    quality = {"passed": all(r["passed"] for r in final_checks), "attempts": attempts,
               "checks": [{"name": r["name"], "passed": r["passed"], "detail": r["detail"]} for r in final_checks]}

    # 6. Итог.
    used_ids = {s for sec in ("why_important", "risks", "opportunities", "actions") for c in draft[sec] for s in c["source_ids"]}
    used_ids |= {s for c in draft["bank_view"]["theses"] + draft["what_happened"]["facts"] for s in c["source_ids"]}
    used_ids |= {f"product:{p['product_id']}" for p in draft["products"]}
    used_ids |= {"client:profile", "client:payments"}
    used_ids |= {f"bank:{item['id']}" for conflict in ctx["forecast_conflicts"] for item in conflict["items"]}
    # Historical forecast versions used in the revision notice are sources too.
    existing_theses = {t["id"] for t in ctx["theses"]}
    for conflict in ctx["forecast_conflicts"]:
        for item in conflict["items"]:
            if item["id"] not in existing_theses:
                from app.knowledge import kb
                thesis = kb.thesis(item["id"])
                if thesis:
                    ctx["theses"].append(thesis)
                    existing_theses.add(item["id"])
    sources = [s for s in _sources(ctx) if s["source_id"] in used_ids]
    relevance = score(news, company["company_id"], role)
    trace.add("finalize", "finalize", f"Источников: {len(sources)}, режим: {mode}, всего {(time.perf_counter() - started) * 1000:.0f} мс",
              output={"total_duration_ms": round((time.perf_counter() - started) * 1000, 1)})

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
        "fallback_reason": fallback_reason if mode == "rules" else None,
        "title": draft["title"],
        "headline": draft["headline"],
        "effect": composer.overall_effect(draft),
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

