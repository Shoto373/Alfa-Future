"""Этапы агента подготовки разбора; orchestrator.run вызывает их по очереди с общим состоянием Run.

  1. plan           — обязательные шаги (правила) и уточняющие запросы модели-исследователя;
  2. collect        — выполнить инструменты, результаты сложить в общий контекст;
  3. draft          — черновик интерпретации (правила; модель по JSON-схеме поверх них);
  4. verify_and_fix — самопроверка: полнота, источники, цифры, противоречия; при провале — расширить поиск,
                      убрать неподтвержденное, дополнить правилами и проверить снова (до 2 раз); затем —
                      безопасный откат к правилам и смысловая проверка выводов AI второй моделью;
  5. finalize       — карточка с источниками, признаками, проверками и трассой шагов.
Контекст разбора (план, источники, признаки, ответы модели) — app/agent/context.py.
"""

import asyncio
import copy
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app import config, llm
from app.agent import composer, context, prompts, review, validators
from app.agent.tools import ToolError, ToolRunner
from app.errors import AnalysisUnavailable
from app.knowledge import kb
from app.news.taxonomy import TOPICS
from app.ranking import ROLES, score
from app.schemas import SCHEMA_VERSION, Insight

logger = logging.getLogger("app.agent")

MAX_ADAPT_ROUNDS = 2

DISCLAIMER = ("Прототип для хакатона. Данные о компаниях обезличены, новости демо-ленты пересказывают материалы кейса. "
              "Материал не является инвестиционной рекомендацией. Выводы с пометкой «AI» сформированы автоматически.")

class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, stage: str, name: str, detail: str, status: str = "ok", duration_ms: float = 0.0, output=None):
        self.steps.append({"step": len(self.steps) + 1, "stage": stage, "name": name, "detail": detail[:400],
                           "status": status, "duration_ms": round(duration_ms, 1), "output": output})

MAX_THESES = 8  # тезисов банка в контексте модели после основного и уточняющих поисков


@dataclass
class Run:
    """Состояние одного разбора, общее для этапов: контекст инструментов, черновик, режим и трасса."""
    company: dict
    role: str
    news: dict
    request_id: str
    use_llm: bool
    fallback_reason: str | None
    runner: ToolRunner
    ctx: dict
    started: float
    trace: Trace = field(default_factory=Trace)
    effect: str | None = None  # знак эффекта по правилам (метка в ленте и шапке)
    draft: dict = field(default_factory=dict)
    mode: str = "rules"
    model: str | None = None
    attempts: int = 1
    results: list[dict] = field(default_factory=list)
    final_checks: list[dict] = field(default_factory=list)


def start(company: dict, role: str, news: dict, request_id: str, use_llm: bool | None) -> Run:
    """Режим разбора и пустой контекст. use_llm=False — только правила, None — модель, если подключена."""
    runner = ToolRunner(request_id)
    wanted = use_llm is not False  # модель нужна, если ее не отключили явно (быстрый разбор, правила конвейера)
    use_llm = llm.available() if use_llm is None else (use_llm and llm.available())
    # Почему модель не дала итог — для плашки в карточке: paused — AI выключен банком, disabled — ключ
    # не задан, unavailable — шлюз не отвечает, budget — лимит, checks — выводы модели не прошли проверки.
    fallback_reason = None if use_llm or not wanted else llm.unavailable_reason()
    ctx = {"news": news, "company": company, "role": role, "exposures": [], "theses": [], "products": [],
           "forecast_conflicts": [], "counterparties": None, "story": [], "coverage": [], "bank_search_complete": False,
           "role_focus": [TOPICS[t]["name"] for t, w in sorted(ROLES.get(role, ROLES["ceo"])["focus"].items(),
                                                              key=lambda kv: -kv[1]) if t in TOPICS]}
    return Run(company, role, news, request_id, use_llm, fallback_reason, runner, ctx, time.perf_counter())


# 1. План ---------------------------------------------------------------------------------------------

def plan(run: Run) -> tuple[list[dict], asyncio.Task | None]:
    """Обязательные шаги сразу; модель-исследователь параллельно придумывает уточняющие запросы."""
    t0 = time.perf_counter()
    steps = context.rules_plan(run.news, run.company)
    planner = asyncio.create_task(asyncio.to_thread(context.llm_queries, run.news, run.company, run.role))         if run.use_llm and config.llm_extra_queries() else None
    if planner:  # разбор может прерваться раньше, чем дождется планировщика: ошибку все равно забираем
        planner.add_done_callback(lambda t: t.cancelled() or t.exception())
    run.trace.add("plan", "plan", "Обязательные шаги: " + " → ".join(s["tool"] for s in steps), "ok",
                  (time.perf_counter() - t0) * 1000, {"steps": [{"tool": s["tool"], "why": s["why"]} for s in steps]})
    return steps, planner


# 2. Инструменты --------------------------------------------------------------------------------------

def _absorb(ctx: dict, tool: str, result) -> str:
    """Результат инструмента — в общий контекст; возвращает краткое описание для трассы."""
    if tool == "get_exposures":
        event_topics = {t["topic"] for t in ctx["news"]["classification"]["topics"]}
        ctx["exposures"] = [e for e in result if e["topic"] in event_topics]
        return f"найдено связей с компанией: {len(result)}"
    if tool == "search_bank_analytics":
        known = {t["id"] for t in ctx["theses"]}
        fresh = [t for t in result if not t.get("stale") and t["id"] not in known]
        ctx["theses"] = (ctx["theses"] + fresh)[:MAX_THESES]
        ctx["bank_search_complete"] = True
        return (f"найдено тезисов: {len(result)}" + (f", из них новых {len(fresh)}" if known else "")) \
            if result else "материалы не найдены"
    if tool == "get_bank_products":
        ctx["products"] = result
        return f"подходящих продуктов: {len(result)}"
    if tool == "check_forecast_conflicts":
        ctx["forecast_conflicts"] = result
        return f"расхождения в прогнозах: {len(result)}" if result else "прогнозы не расходятся"
    if tool == "get_counterparties":
        ctx["counterparties"] = result
        return f"поставщиков {result['suppliers']['counterparties']}, покупателей {result['customers']['counterparties']}"
    if tool == "get_story_coverage":
        seen = {n["news_id"] for n in ctx["story"]}
        ctx["coverage"] = [n for n in result if n["news_id"] not in seen]
        return (f"то же событие в других источниках: {', '.join(n['source'] for n in ctx['coverage'])}"
                if ctx["coverage"] else "других источников по событию нет")
    if tool == "get_story_history":
        ctx["story"] = result
        return (f"похожих событий раньше: {len(result)}, последнее {result[0]['published_at'][:10]}" if result
                else "похожих событий раньше не было")
    return "получено"


def _run_steps(run: Run, steps: list[dict]) -> None:
    for step in steps:
        try:
            result, ms = run.runner.call(step["tool"], **step["args"])
        except ToolError as exc:
            run.trace.add("tool", step["tool"], f"{step['why']}: ошибка — {exc}", "error")
            continue
        summary = _absorb(run.ctx, step["tool"], result)
        run.trace.add("tool", step["tool"], f"{step['why']}: {summary}", "ok", ms,
                      {"args": {k: v for k, v in step["args"].items() if k != "company_id"},
                       **({"thesis_ids": [t["id"] for t in result]} if step["tool"] == "search_bank_analytics" else {})})


async def collect(run: Run, steps: list[dict], planner: asyncio.Task | None) -> None:
    """Инструменты читают БД и векторное хранилище — в потоке, чтобы не блокировать другие запросы."""
    await asyncio.to_thread(_run_steps, run, steps)
    if not planner:
        return
    try:
        extra, meta = await planner
        run.trace.add("plan", "llm_queries", f"Модель {meta['model']} предложила уточняющих запросов: {len(extra)}", "ok",
                      meta["duration_ms"], {"queries": [{"query": q["args"]["query"], "why": q["why"]} for q in extra]})
        await asyncio.to_thread(_run_steps, run, extra)
    except llm.LLMError as exc:
        run.trace.add("plan", "llm_queries", f"Уточняющие запросы модели не получены ({exc}); достаточно обязательных шагов", "warning")


# 3. Черновик -----------------------------------------------------------------------------------------

async def draft(run: Run) -> None:
    """Черновик правилами; с моделью — ее разделы поверх правил (при сбое модели остаются правила)."""
    t0 = time.perf_counter()
    run.draft = composer.compose(run.ctx)
    # Знак эффекта для метки — по правилу «чувствительность компании × направление события»: модель почти всегда
    # пишет и риски, и возможности, и по ее разделам метка была бы «и риск, и возможность» у любой новости.
    run.effect = composer.overall_effect(run.draft)
    run.ctx["rules_effect"] = run.effect
    if run.use_llm:
        try:
            data, meta = await asyncio.to_thread(llm.chat_json, prompts.COMPOSE_SYSTEM,
                                                 prompts.compose_user(run.ctx, context.sources(run.ctx)), "compose", 8000)
            rules_facts = run.draft["what_happened"]["facts"]
            run.draft = context.merge_llm(run.draft, data)
            notes = context.tidy_llm(run.draft, rules_facts, run.ctx)
            run.mode, run.model = "llm", meta["model"]
            run.trace.add("compose", "llm_compose", f"Черновик модели {meta['model']}, токенов {meta['tokens']}"
                          + (f"; {'; '.join(notes)}" if notes else ""), "ok", meta["duration_ms"])
        except llm.LLMError as exc:
            if isinstance(exc, llm.BudgetError):
                run.fallback_reason = "company_budget" if exc.scope == "company" else "budget"
            else:
                run.fallback_reason = "unavailable"
            run.trace.add("compose", "llm_compose", f"LLM недоступна ({exc}); быстрый разбор", "warning")
    if run.mode == "rules":
        run.trace.add("compose", "rules_compose", "Быстрый разбор: эффект = чувствительность компании × направление события",
                      "ok", (time.perf_counter() - t0) * 1000)


# 4–5. Самопроверка и коррекция -----------------------------------------------------------------------

def _check(run: Run, round_no: int) -> tuple[list[dict], set[str]]:
    """Проверки черновика; не пройденные — в трассу вместе с типами ошибок по утверждениям."""
    source_ids = {s["source_id"] for s in context.sources(run.ctx)}
    run.results = validators.check(run.draft, run.ctx, source_ids, context.grounding_text(run.ctx))
    failed = [r for r in run.results if not r["passed"]]
    # Типы ошибок по утверждениям — для мониторинга качества черновиков (какие правила модель нарушает чаще).
    claim_errors: dict[str, int] = {}
    for section, c in validators._claims(run.draft):
        for err in validators.claim_errors(section, c, run.ctx, source_ids):
            claim_errors[err] = claim_errors.get(err, 0) + 1
    run.trace.add("check", f"self_check_{round_no + 1}",
                  "Все проверки пройдены" if not failed else "Не пройдено: " + ", ".join(r["name"] for r in failed),
                  "ok" if not failed else "warning", 0, {"checks": [{k: r[k] for k in ("name", "passed")} for r in run.results],
                                                         "claim_errors": claim_errors})
    return failed, source_ids


async def _repair(run: Run, source_ids: set[str], failed: list[dict], actions: list[str]) -> list[dict]:
    """Модель исправляет утверждения с ошибками; исправленный черновик проверяется заново."""
    t1 = time.perf_counter()
    outcome = await asyncio.to_thread(context.llm_repair, run.draft, run.ctx, source_ids)
    if not outcome:
        return failed
    run.trace.add("adapt", "llm_repair", outcome["detail"], outcome["status"], (time.perf_counter() - t1) * 1000)
    if outcome["status"] != "ok":
        return failed
    actions.append(outcome["detail"])
    # Удаление неподтвержденного — только если ошибки остались.
    results = validators.check(run.draft, run.ctx, {s["source_id"] for s in context.sources(run.ctx)}, context.grounding_text(run.ctx))
    return [r for r in results if not r["passed"]]


async def _broaden(run: Run, actions: list[str]) -> None:
    """Расширенный поиск по аналитике банка: весь текст новости, без фильтра по отраслям."""
    news = run.news
    try:
        wider, ms = await asyncio.to_thread(
            run.runner.call, "search_bank_analytics", query=news["text"][:600],
            topics=[t["topic"] for t in news["classification"]["topics"]], sectors=[], include_stale=False)
        run.ctx["theses"] = wider
        run.ctx["bank_search_complete"] = True
        rebuilt = composer.compose(run.ctx)
        run.draft["bank_view"] = rebuilt["bank_view"]
        actions.append(f"расширен поиск по аналитике банка: {len(wider)} тезисов")
    except ToolError as exc:
        actions.append(f"расширить поиск не удалось: {exc}")


def _fill_from_rules(run: Run, actions: list[str]) -> None:
    draft, rebuilt = run.draft, composer.compose(run.ctx)
    for key in ("why_important", "risks", "opportunities", "actions"):
        if not draft[key] or len({f for c in draft[key] for f in c.get("features", [])}) < 1:
            draft[key] = rebuilt[key]
    # Факты «Что произошло» — дословные предложения новости; если проверка их сняла, берутся из правил.
    if not draft["what_happened"]["facts"]:
        draft["what_happened"]["facts"] = rebuilt["what_happened"]["facts"]
    if validators.similarity(draft["headline"], run.news["title"]) > 0.5:
        draft["headline"] = rebuilt["headline"]
    actions.append("разделы дополнены быстрым разбором")


async def _adapt(run: Run, round_no: int, failed: list[dict], source_ids: set[str], repaired: bool) -> bool:
    """Одна коррекция по не пройденным проверкам. Возвращает, было ли уже исправление моделью."""
    run.attempts += 1
    actions: list[str] = []
    if run.mode == "llm" and not repaired:
        repaired = True
        failed = await _repair(run, source_ids, failed, actions)
    fixes = {r["fix"] for r in failed}
    if "broaden_search" in fixes:
        await _broaden(run, actions)
    if "fill_from_rules" in fixes:
        _fill_from_rules(run, actions)
    actions += validators.apply_fix(run.draft, failed, {s["source_id"] for s in context.sources(run.ctx)}, context.grounding_text(run.ctx), run.ctx)
    run.trace.add("adapt", f"adapt_{round_no + 1}", "; ".join(actions) or "исправления не потребовались", "ok")
    return repaired


def _safe_fallback(run: Run) -> None:
    """Лимит коррекций исчерпан, а проверки не пройдены: заведомо неверный разбор не возвращается."""
    if run.mode == "llm":
        run.fallback_reason = "checks"
    run.draft = composer.compose(run.ctx)
    run.mode, run.model = "rules", None
    run.results = validators.check(run.draft, run.ctx, {s["source_id"] for s in context.sources(run.ctx)}, context.grounding_text(run.ctx))
    run.trace.add("adapt", "safe_fallback", "Лимит коррекций исчерпан; повторно проверен быстрый разбор", "warning")
    if any(not r["passed"] for r in run.results):
        logger.warning("analysis rejected request_id=%s checks=%s", run.request_id,
                       [r["name"] for r in run.results if not r["passed"]])
        raise AnalysisUnavailable("Не удалось подготовить подтвержденный разбор")


async def _semantic_review(run: Run) -> None:
    """Смысловая проверка выводов AI второй моделью (только для текста модели)."""
    t0 = time.perf_counter()
    backup = copy.deepcopy(run.draft)
    try:
        outcome = await asyncio.to_thread(review.review, run.draft, run.ctx, context.sources(run.ctx))
        recheck = validators.check(run.draft, run.ctx, {s["source_id"] for s in context.sources(run.ctx)}, context.grounding_text(run.ctx))
        if any(not r["passed"] for r in recheck):
            run.draft = backup
            detail = "Критик предложил убрать выводы, но разбор без них не прошел проверки — оставлен прежний"
        else:
            run.final_checks = list(recheck)
            detail = (f"Проверено выводов AI: {outcome['reviewed']}; подтверждено {outcome['supported']}, "
                      f"частично {outcome['partial']}, убрано {len(outcome['removed'])}")
            if outcome["removed"]:
                detail += ": " + "; ".join(outcome["removed"])
        run.final_checks.append({"name": "semantic_review", "passed": True, "detail": detail[:400]})
        run.trace.add("check", "semantic_review", detail, "ok", (time.perf_counter() - t0) * 1000)
    except llm.LLMError as exc:
        run.draft = backup
        run.trace.add("check", "semantic_review", f"Смысловая проверка недоступна ({exc}); остаются детерминированные проверки",
                      "warning", (time.perf_counter() - t0) * 1000)


async def verify_and_fix(run: Run) -> None:
    """Проверки и до MAX_ADAPT_ROUNDS коррекций; затем безопасный откат к правилам и смысловая проверка."""
    repaired = False
    for round_no in range(MAX_ADAPT_ROUNDS + 1):
        failed, source_ids = _check(run, round_no)
        if not failed or round_no == MAX_ADAPT_ROUNDS:
            break
        repaired = await _adapt(run, round_no, failed, source_ids, repaired)
    if any(not r["passed"] for r in run.results):
        _safe_fallback(run)
    run.final_checks = list(run.results)
    if run.mode == "llm":
        await _semantic_review(run)


# 6. Итог ---------------------------------------------------------------------------------------------

def _used_sources(run: Run) -> list[dict]:
    """Источники, на которые ссылается разбор, включая прежние версии прогнозов из уведомления о пересмотре."""
    draft, ctx = run.draft, run.ctx
    used_ids = {s for sec in ("why_important", "risks", "opportunities", "actions") for c in draft[sec] for s in c["source_ids"]}
    used_ids |= {s for c in draft["bank_view"]["theses"] + draft["what_happened"]["facts"] for s in c["source_ids"]}
    used_ids |= {f"product:{p['product_id']}" for p in draft["products"]}
    used_ids |= {"client:profile", "client:payments"}
    used_ids |= {f"bank:{item['id']}" for conflict in ctx["forecast_conflicts"] for item in conflict["items"]}
    existing_theses = {t["id"] for t in ctx["theses"]}
    for conflict in ctx["forecast_conflicts"]:
        for item in conflict["items"]:
            if item["id"] not in existing_theses:
                thesis = kb.thesis(item["id"])
                if thesis:
                    ctx["theses"].append(thesis)
                    existing_theses.add(item["id"])
    return [s for s in context.sources(ctx) if s["source_id"] in used_ids]


def finalize(run: Run) -> dict:
    """Карточка разбора по схеме Insight: разделы, признаки, релевантность, источники, проверки и трасса."""
    draft, company = run.draft, run.company
    quality = {"passed": all(r["passed"] for r in run.final_checks), "attempts": run.attempts,
               "checks": [{"name": r["name"], "passed": r["passed"], "detail": r["detail"]} for r in run.final_checks]}
    sources = _used_sources(run)
    relevance = score(run.news, company["company_id"], run.role)
    run.trace.add("finalize", "finalize", f"{'AI-разбор' if run.mode == 'llm' else 'Быстрый разбор'} готов, источников: {len(sources)}",
                  output={"total_duration_ms": round((time.perf_counter() - run.started) * 1000, 1)})
    insight = {
        "schema_version": SCHEMA_VERSION, "insight_id": f"ins-{uuid.uuid4().hex[:12]}", "request_id": run.request_id,
        "company_id": company["company_id"], "role": run.role, "news_id": run.news["news_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": run.mode, "model": run.model, "fallback_reason": run.fallback_reason if run.mode == "rules" else None,
        "title": draft["title"], "headline": draft["headline"], "effect": run.effect or composer.overall_effect(draft),
        "what_happened": draft["what_happened"], "why_important": draft["why_important"], "risks": draft["risks"],
        "opportunities": draft["opportunities"], "actions": draft["actions"], "questions": draft["questions"],
        "bank_view": draft["bank_view"], "products": draft["products"], "features_used": context.features_used(run.ctx, draft),
        "relevance": {"score": relevance["score"], "reasons": [
            {k: r.get(k) for k in ("kind", "feature", "origin", "weight", "text", "topic")} for r in relevance["reasons"]]},
        "sources": sources, "quality": quality, "trace": run.trace.steps, "disclaimer": DISCLAIMER,
    }
    try:
        return Insight.model_validate(insight).model_dump()
    except Exception as exc:  # pragma: no cover - защитный барьер
        logger.exception("insight failed schema validation request_id=%s", run.request_id)
        raise AnalysisUnavailable("Карточка не прошла проверку схемы") from exc
