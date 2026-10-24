import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app import cache, config, embeddings, llm, llm_usage, pipeline, quality, ratelimit, storage, vectors
from app.agent import audit, orchestrator, qa
from app.auth import store as auth_store
from app.auth.deps import check_origin, client_ip, current_user, member_of, require_operator
from app.companies import ai_settings as company_ai
from app.companies import extra as company_extra
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.errors import AnalysisUnavailable, ApiError, InvalidAnalysisResult
from app.knowledge import kb
from app.news import entities, parser, store
from app.news.sources import registry as sources
from app.news.taxonomy import TOPICS
from app.ranking import ROLES, company_feed
from app.worker import queue as jobs
from app.worker import runner as worker
from app.schemas import (AISettingsRequest, Answer, CompanyExtraRequest, ErrorResponse, FeedbackRequest, Insight, InsightRequest,
                         LLMSwitchRequest,
                         NewsCreateRequest, QuestionRequest)

logger = logging.getLogger("app.api")
router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_origin)])
# Описания заданы явно: иначе FastAPI берет их из http.HTTPStatus, а они различаются
# между версиями Python (413 в 3.13+ — «Content Too Large»), и контракт перестает совпадать.
ERROR_DESCRIPTIONS = {
    400: "Некорректный запрос (INVALID_REQUEST)",
    401: "Нет действительной сессии (UNAUTHORIZED, INVALID_CREDENTIALS)",
    403: "Недостаточно прав (FORBIDDEN)",
    404: "Объект не найден (*_NOT_FOUND, MEMBER_NOT_FOUND)",
    409: "Конфликт (EMAIL_TAKEN, COMPANY_CLAIMED, TOO_MANY_COMPANIES, MEMBER_EXISTS, LAST_ADMIN)",
    413: "Тело запроса больше 64 КиБ, файл — больше 5 МБ (REQUEST_TOO_LARGE)",
    422: "Не удалось загрузить материал по ссылке (FETCH_FAILED)",
    500: "Внутренняя ошибка (INTERNAL_ERROR, INVALID_ANALYSIS_RESULT)",
    503: "Сервис или данные временно недоступны (ANALYSIS_UNAVAILABLE, DATA_UNAVAILABLE)",
    429: "Слишком много неудачных попыток входа (TOO_MANY_ATTEMPTS)",
    504: "Превышено время анализа (ANALYSIS_TIMEOUT)",
}
ERRORS = {s: {"model": ErrorResponse, "description": d} for s, d in ERROR_DESCRIPTIONS.items()}
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _company(company_id: str) -> dict:
    if not _ID.match(company_id):
        raise ApiError("INVALID_REQUEST")
    try:
        c = profiles.get(company_id)
    except profiles.ProfilesError:
        logger.exception("profiles unavailable")
        raise ApiError("DATA_UNAVAILABLE")
    if c is None:
        raise ApiError("COMPANY_NOT_FOUND")
    return c


company_or_404 = _company


def limited(scope: str):
    """Зависимость: вошедший пользователь и учет запроса в лимите частоты (пользователь и адрес)."""
    def dependency(request: Request, user: dict = Depends(current_user)) -> dict:
        ratelimit.check(scope, user["user_id"], client_ip(request))
        return user
    return dependency


def _limit_llm(user: dict, action: str) -> None:
    """Частота запросов к модели на пользователя в час («Пересчитать», вопросы в чате).

    Действует, только когда модель подключена: без нее запрос бесплатен. Защищает общий бюджет от
    случайных и намеренных серий запросов; превышение — 429 RATE_LIMITED."""
    per_hour = config.llm_user_limits()[action]
    if not per_hour or not llm.available():
        return
    # Сначала запись, потом подсчет: параллельные запросы видят друг друга и не проскакивают лимит вместе.
    storage.log_event("llm_request", user_id=user["user_id"], action=action)
    if storage.count_events("llm_request", 3600, user_id=user["user_id"], action=action) > per_hour:
        raise ApiError("RATE_LIMITED")


def _news(news_id: str) -> dict:
    if not _ID.match(news_id):
        raise ApiError("INVALID_REQUEST")
    n = store.get(news_id)
    if n is None:
        raise ApiError("NEWS_NOT_FOUND")
    return n


def _news_brief(n: dict) -> dict:
    cls = n["classification"]
    return {"news_id": n["news_id"], "title": n["title"], "lead": n["lead"], "source": n["source"], "url": n["url"],
            "kind": n["kind"], "published_at": n["published_at"], "topics": [{"topic": t["topic"], "name": t["name"]} for t in cls["topics"]],
            "sectors": cls["sectors"], "countries": cls["countries"], "direction": cls["direction"],
            "duplicates": len(n["duplicates"])}


def _mentions(n: dict, company_id: str) -> dict:
    """Организации в новости и признак «упоминается ваша компания или ее контрагент» (SPR3-02)."""
    found = entities.mentions(n, company_id)
    return {"mentions": found, "mentions_company": any(m["relation"] != "other" for m in found)}


def _worker_status() -> dict:
    """Пульс фонового воркера и очередь задач: API отвечает и без воркера, но новости тогда не обновляются."""
    beat = worker.status() or {}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(beat["at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    return {"alive": age is not None and age < 120, "workers": beat.get("workers", 0), "last_seen": beat.get("at"),
            "last_job": beat.get("last_job"),
            "queue": jobs.stats()}


@router.get("/meta", responses=ERRORS)
def meta() -> dict:
    try:
        data = profiles.meta()
    except profiles.ProfilesError:
        raise ApiError("DATA_UNAVAILABLE")
    return {
        "data": data,
        "knowledge": {"documents": len(kb.documents()), "theses": sum(1 for _ in kb.search(topics=list(TOPICS), limit=1000, include_stale=True))},
        "news": len(store.all_items()),
        "search": {"embeddings": embeddings.signature() != "emb:off", "vectors": vectors.stats(), "redis": cache.ping()},
        "pipeline": pipeline.status(),
        "worker": _worker_status(),
        # Расходы банка на LLM — не публичные данные: только сотрудникам банка в /metrics.
        "llm": {"connected": llm.available(), "allowed_models": list(config.ALLOWED_MODELS)},
        "roles": [{"role": k, "name": v["name"]} for k, v in ROLES.items()],
        "topics": [{"topic": k, "name": v["name"]} for k, v in TOPICS.items()],
        "sectors": [{"sector": k, "name": v} for k, v in SECTOR_NAMES.items()],
    }


@router.get("/companies/lookup", responses=ERRORS)
def lookup_companies(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50),
                           offset: int = Query(0, ge=0), _user: dict = Depends(current_user)) -> dict:
    """Поиск компании для привязки: только публичные поля, без финансовых данных.
    Доступны компании витрины (SHOWCASE_PER_SECTOR): по каждой отрасли — с самыми полными данными."""
    try:
        total, items = profiles.list_companies(q, None, limit, offset, profiles.showcase_ids(config.showcase_per_sector()))
    except profiles.ProfilesError:
        raise ApiError("DATA_UNAVAILABLE")
    claimed = auth_store.claimed_ids()
    return {"total": total, "items": [
        {"company_id": c["company_id"], "display_name": c["display_name"], "sector_name": c["sector_name"],
         "region": c["region"], "claimed": c["company_id"] in claimed} for c in items]}


@router.get("/companies", responses=ERRORS)
def list_companies(q: str = Query("", max_length=100), sector: str | None = Query(None, max_length=40),
                         limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         user: dict = Depends(current_user)) -> dict:
    """Только компании, в которых состоит пользователь."""
    mine = {m["company_id"] for m in user["memberships"]}
    try:
        _, items = profiles.list_companies(q, sector, 100000, 0)
    except profiles.ProfilesError:
        raise ApiError("DATA_UNAVAILABLE")
    items = [c for c in items if c["company_id"] in mine]
    return {"total": len(items), "items": items[offset:offset + limit]}


@router.get("/companies/{company_id}", responses=ERRORS)
def company(company_id: str, user: dict = Depends(current_user)) -> dict:
    member_of(user, company_id)
    c = _company(company_id)
    return {"profile": c, "exposures": list(profiles.exposures(company_id))}


def _extra_view(company_id: str) -> dict:
    value = company_extra.get(company_id) or {}
    return {"company_id": company_id, "shares": value.get("shares", {}), "notes": value.get("notes", ""),
            "updated_at": value.get("updated_at"),
            "files": [{k: f[k] for k in ("file_id", "name", "kind", "size", "chars", "uploaded_at")} | {"preview": f["text"][:200]}
                      for f in value.get("files", [])],
            "fields": [{"key": k, "label": v["label"]} for k, v in company_extra.SHARES.items()]}


@router.get("/companies/{company_id}/ai-settings", responses=ERRORS)
def get_ai_settings(company_id: str, user: dict = Depends(current_user)) -> dict:
    """Готовить ли AI-разборы важных новостей заранее и с какой важности (видят все участники)."""
    member_of(user, company_id)
    _company(company_id)
    return {"company_id": company_id, **company_ai.get(company_id)}


@router.put("/companies/{company_id}/ai-settings", responses=ERRORS)
def put_ai_settings(company_id: str, payload: AISettingsRequest, user: dict = Depends(current_user)) -> dict:
    """Меняет администратор компании; конвейер учитывает настройку со следующего цикла."""
    _admin_of(user, company_id)
    storage.log_event("ai_settings_saved", company_id=company_id)
    return {"company_id": company_id, **company_ai.save(company_id, payload.enabled, payload.threshold, user["user_id"])}


@router.get("/companies/{company_id}/extra", responses=ERRORS)
def get_company_extra(company_id: str, user: dict = Depends(current_user)) -> dict:
    """Сведения, которые компания сообщила о себе (видят все участники)."""
    member_of(user, company_id)
    _company(company_id)
    return _extra_view(company_id)


@router.put("/companies/{company_id}/extra", responses=ERRORS)
def put_company_extra(company_id: str, payload: CompanyExtraRequest, user: dict = Depends(current_user)) -> dict:
    """Меняет администратор компании; карточки и лента компании после этого пересчитываются."""
    _admin_of(user, company_id)
    company_extra.save(company_id, payload.shares.model_dump(), payload.notes, user["user_id"])
    storage.log_event("company_extra_saved", company_id=company_id)
    return _extra_view(company_id)


def _admin_of(user: dict, company_id: str) -> None:
    if not member_of(user, company_id)["is_admin"]:
        raise ApiError("FORBIDDEN")
    _company(company_id)


@router.post("/companies/{company_id}/extra/files", responses=ERRORS)
async def upload_company_file(company_id: str, request: Request, name: str = Query(..., min_length=1, max_length=200),
                              user: dict = Depends(current_user)) -> dict:
    """Файл CSV или PDF телом запроса (до 5 МБ): текст из него дополняет сведения компании."""
    await asyncio.to_thread(_admin_of, user, company_id)
    data = await request.body()
    try:
        await asyncio.to_thread(company_extra.add_file, company_id, name, data, user["user_id"])
    except company_extra.FileError as exc:
        raise ApiError("INVALID_REQUEST", str(exc))
    storage.log_event("company_file_added", company_id=company_id)
    return await asyncio.to_thread(_extra_view, company_id)


@router.delete("/companies/{company_id}/extra/files/{file_id}", responses=ERRORS)
def delete_company_file(company_id: str, file_id: str, user: dict = Depends(current_user)) -> dict:
    _admin_of(user, company_id)
    if not company_extra.delete_file(company_id, file_id, user["user_id"]):
        raise ApiError("FILE_NOT_FOUND")
    return _extra_view(company_id)


@router.get("/feed", responses=ERRORS)
def news_feed(company_id: str, topic: str | None = Query(None, max_length=40),
              story: str | None = Query(None, max_length=64),
              limit: int = Query(30, ge=1, le=500), user: dict = Depends(current_user)) -> dict:
    role = member_of(user, company_id)["role"]  # роль берется из членства, не от клиента
    _company(company_id)
    # Вся лента компании без фильтра — для счетчиков тем: показываются только темы, где есть новости.
    everything = company_feed(company_id, role, 500)
    counts: dict[str, dict] = {}
    for r in everything:
        for t in r["news"]["classification"]["topics"]:
            counts.setdefault(t["topic"], {"topic": t["topic"], "name": t["name"], "count": 0})["count"] += 1
    # Динамические темы — сюжеты из нескольких сообщений, которые есть в ленте этой компании.
    stories = [{"story_id": r["story_id"], "label": store.story_label(r["story_id"]), "size": r["story_size"] + 1}
               for r in everything if r.get("story_id")][:8]
    ranked = [r for r in everything if (not topic or topic in {t["topic"] for t in r["news"]["classification"]["topics"]})
              and (not story or r.get("story_id") == story)][:limit]
    storage.log_event("feed_view", company_id=company_id, role=role)
    cached = storage.cached_insight_refs(company_id, role, [r["news"]["news_id"] for r in ranked])
    # total и topic_counts — по всей ленте компании: главная и лента показывают одни и те же числа.
    return {"company_id": company_id, "role": role, "total": len(everything),
            "topic_counts": sorted(counts.values(), key=lambda c: (-c["count"], c["name"])), "stories": stories, "items": [
        # Склеенные похожие новости других источников добавляются к счетчику «+N источников».
        {"news": {**_news_brief(r["news"]), "duplicates": len(r["news"]["duplicates"]) + r.get("story_size", 0),
                  "story_id": r.get("story_id"), **_mentions(r["news"], company_id)},
         "relevance": r["relevance"],
         # Знак эффекта — из готового разбора: метка «скорее риск / возможность» в карточке ленты.
         "cached_insight_id": cached.get(r["news"]["news_id"], (None, None))[0],
         "cached_effect": cached.get(r["news"]["news_id"], (None, None))[1]}
        for r in ranked]}


@router.get("/news/{news_id}", responses=ERRORS)
def news(news_id: str, company_id: str | None = Query(None, max_length=64), user: dict = Depends(current_user)) -> dict:
    """Новость с организациями в тексте; с company_id — и их отношение к компании (своя, поставщик, покупатель)."""
    n = _news(news_id)
    if company_id is None:
        return {**n, "entities": entities.of_news(n)}
    member_of(user, company_id)
    return {**n, "entities": entities.of_news(n), **_mentions(n, company_id)}


@router.post("/news", responses=ERRORS, dependencies=[Depends(limited("news"))])
def add_news(payload: NewsCreateRequest) -> dict:
    if payload.url:
        try:
            item = parser.fetch_article(payload.url)
        except parser.FetchError as exc:
            raise ApiError("FETCH_FAILED", f"Не удалось загрузить материал: {exc}")
        except Exception:
            raise ApiError("FETCH_FAILED")
    elif payload.text and len(payload.text.strip()) >= 40:
        title = (payload.title or payload.text.strip().split(".")[0])[:300]
        item = store.make_item(title, payload.text, "Добавлено пользователем", None, None, "user", llm=True)
    else:
        raise ApiError("INVALID_REQUEST", "Укажите ссылку или текст новости не короче 40 символов")
    if len(item["text"].strip()) < 40 or not item["title"].strip():
        raise ApiError("INVALID_REQUEST", "После очистки текст новости слишком короткий или не содержит заголовка")
    saved, created = store.add(item)
    return {"created": created, "duplicate_of": None if created else saved["news_id"], "news": _news_brief(saved),
            "classification": saved["classification"]}


@router.post("/news/refresh", responses=ERRORS, dependencies=[Depends(require_operator)])
def refresh_news() -> dict:
    return sources.collect(force=True)


@router.post("/insights", response_model=Insight, responses=ERRORS)
async def create_insight(payload: InsightRequest, request: Request, user: dict = Depends(limited("insights"))) -> dict:
    request_id: str = request.state.request_id
    # Роль — из членства; perspective лишь меняет угол зрения (доступ к компании проверяется так же).
    role = payload.perspective or member_of(user, payload.company_id)["role"]
    member_of(user, payload.company_id)

    def prepare():
        c, n = _company(payload.company_id), _news(payload.news_id)
        if payload.force_refresh:
            _limit_llm(user, "refresh")
            return c, n, None
        cached = storage.cached_insight(c["company_id"], role, n["news_id"])
        # Карточка на правилах пересчитывается моделью, если LLM подключена; быстрый запрос берет любую готовую.
        if cached and (payload.fast or not (cached["mode"] == "rules" and llm.available() and not storage.llm_attempted(cached))):
            storage.log_event("insight_open", insight_id=cached["insight_id"], cached=True)
            return c, n, cached
        return c, n, None

    c, n, cached = await asyncio.to_thread(prepare)
    if cached:
        # Готовый разбор на правилах (часто — от конвейера, без модели) не знает, почему модели нет сейчас:
        # причина — состояние сервера в момент открытия, для плашки «не подключена» / «не отвечает».
        if cached["mode"] == "rules" and not cached.get("fallback_reason") and not payload.fast and not llm.available():
            cached = {**cached, "fallback_reason": llm.unavailable_reason()}
        return cached
    async def check_and_save(insight: dict) -> None:
        # Свой разбор проверяется и сохраняется до того, как его получат ждущие этот же разбор запросы.
        if (insight["company_id"], insight["news_id"], insight["role"], insight["request_id"]) != (
                c["company_id"], n["news_id"], role, request_id):
            raise ApiError("INVALID_ANALYSIS_RESULT")
        await asyncio.to_thread(storage.save_insight, insight)

    try:
        # Тот же разбор уже строится (другой сотрудник, конвейер) — ждем его, а не платим за модель второй раз.
        job = orchestrator.run_once(c, role, n, request_id, use_llm=False if payload.fast else None,
                                    on_built=check_and_save)
        insight, leader = await asyncio.wait_for(job, timeout=config.analysis_timeout())
    except ApiError:
        raise
    except asyncio.TimeoutError:
        raise ApiError("ANALYSIS_TIMEOUT")
    except AnalysisUnavailable:
        raise ApiError("ANALYSIS_UNAVAILABLE")
    except InvalidAnalysisResult:
        raise ApiError("INVALID_ANALYSIS_RESULT")
    except Exception:
        logger.exception("analysis failed request_id=%s", request_id)
        raise ApiError("INTERNAL_ERROR")
    if (insight["company_id"], insight["news_id"], insight["role"]) != (c["company_id"], n["news_id"], role):
        raise ApiError("INVALID_ANALYSIS_RESULT")
    # Свой разбор уже сохранен в check_and_save; чужой (leader=False) сохранил первый запрос.
    await asyncio.to_thread(storage.log_event, "insight_open", insight_id=insight["insight_id"], cached=not leader)
    return insight


@router.get("/insights/{insight_id}", response_model=Insight, responses=ERRORS)
def get_insight(insight_id: str, user: dict = Depends(current_user)) -> dict:
    ins = storage.get_insight(insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    member_of(user, ins["company_id"])
    return ins


@router.post("/insights/{insight_id}/questions", response_model=Answer, responses=ERRORS)
def ask(insight_id: str, payload: QuestionRequest, user: dict = Depends(limited("questions"))) -> dict:
    ins = storage.get_insight(insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    member_of(user, ins["company_id"])
    c = _company(ins["company_id"])
    _limit_llm(user, "question")
    with llm_usage.for_company(c["company_id"]):  # ответ модели — в доле компании в общем бюджете
        result = qa.answer(ins, c, payload.question.strip())
    storage.save_answer(result)
    storage.log_event("question", insight_id=insight_id, refused=result["refused"], mode=result["mode"])
    return result


@router.post("/feedback", responses=ERRORS)
def feedback(payload: FeedbackRequest, user: dict = Depends(current_user)) -> dict:
    ins = storage.get_insight(payload.insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    role = member_of(user, ins["company_id"])["role"]
    storage.add_feedback(payload.model_dump() | {"role": role})
    return {"status": "ok"}


@router.get("/metrics", responses=ERRORS, dependencies=[Depends(require_operator)])
def metrics() -> dict:
    return storage.metrics()


@router.get("/metrics/daily", responses=ERRORS, dependencies=[Depends(require_operator)])
def daily_quality(hours: int = Query(24, ge=1, le=24 * 30)) -> dict:
    """Мониторинг качества за период: доля текста модели, проверки, источники, оценки, задержки, конвейер."""
    return quality.daily(hours)


@router.get("/metrics/overview", responses=ERRORS, dependencies=[Depends(require_operator)])
def quality_overview(hours: int = Query(24 * 7, ge=1, le=24 * 30)) -> dict:
    """Страница мониторинга: показатели за период, накопленные метрики и выводы «что улучшить»."""
    period, totals = quality.daily(hours), storage.metrics()
    return {"period": period, "totals": totals, "findings": quality.findings(period, totals),
            "check_labels": quality.CHECK_LABELS}


@router.get("/analytics", responses=ERRORS, dependencies=[Depends(current_user)])
def analytics() -> dict:
    docs = sorted(kb.documents(), key=lambda d: d["date"], reverse=True)
    theses = kb.search(topics=list(TOPICS), limit=1000, include_stale=True)
    pdf_dir = config.bank_pdf_dir()
    return {"documents": [d | {"pdf_available": bool(pdf_dir and (pdf_dir / d["file"]).exists()),
                               "theses": sorted([t for t in theses if t["doc_id"] == d["doc_id"]], key=lambda t: (t["page"], t["id"]))}
                          for d in docs]}


@router.get("/analytics/{doc_id}/pdf", responses=ERRORS, dependencies=[Depends(current_user)])
def analytics_pdf(doc_id: str):
    doc = kb.document(doc_id)
    pdf_dir = config.bank_pdf_dir()
    if doc is None or pdf_dir is None:
        raise ApiError("DOCUMENT_NOT_FOUND")
    path = (pdf_dir / doc["file"]).resolve()
    if path.parent != pdf_dir.resolve() or not path.exists():
        raise ApiError("DOCUMENT_NOT_FOUND")
    return FileResponse(path, media_type="application/pdf", filename=Path(doc["file"]).name,
                        content_disposition_type="inline")


@router.get("/audit", responses=ERRORS, dependencies=[Depends(require_operator)])
def audit_log(limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"items": audit.tail(limit)}


@router.get("/ops/llm", responses=ERRORS, dependencies=[Depends(require_operator)])
def llm_switch_state() -> dict:
    return llm_usage.pause_state() | {"connected": llm.available()}


@router.post("/ops/llm", responses=ERRORS)
def llm_switch(payload: LLMSwitchRequest, user: dict = Depends(require_operator)) -> dict:
    """Выключатель AI для сотрудника банка: подозрение на утечку ключа, защита — без удаления ключа с сервера.
    Пока выключено, разборы строятся правилами, в карточке — «AI временно выключен банком»."""
    return llm_usage.set_paused(payload.paused, user["email"]) | {"connected": llm.available()}
