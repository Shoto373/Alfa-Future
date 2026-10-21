import asyncio
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse

from app import config, storage
from app.agent import audit, llm, orchestrator, qa
from app.api.errors import ApiError
from app.companies import profiles
from app.companies.sectors import SECTOR_NAMES
from app.errors import AnalysisUnavailable, InvalidAnalysisResult
from app.knowledge import kb
from app.news import parser, store
from app.news.taxonomy import TOPICS
from app.ranking import ROLES, feed
from app.schemas import (Answer, ErrorResponse, FeedbackRequest, Insight, InsightRequest, NewsCreateRequest,
                         QuestionRequest, Role)

logger = logging.getLogger("app.api")
router = APIRouter(prefix="/api/v1")
# Описания заданы явно: иначе FastAPI берет их из http.HTTPStatus, а они различаются
# между версиями Python (413 в 3.13+ — «Content Too Large»), и контракт перестает совпадать.
ERROR_DESCRIPTIONS = {
    400: "Некорректный запрос (INVALID_REQUEST)",
    404: "Объект не найден (*_NOT_FOUND)",
    413: "Тело запроса больше 64 КиБ (REQUEST_TOO_LARGE)",
    422: "Не удалось загрузить материал по ссылке (FETCH_FAILED)",
    500: "Внутренняя ошибка (INTERNAL_ERROR, INVALID_ANALYSIS_RESULT)",
    503: "Сервис или данные временно недоступны (ANALYSIS_UNAVAILABLE, DATA_UNAVAILABLE)",
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


@router.get("/meta", responses=ERRORS)
async def meta() -> dict:
    try:
        data = profiles.meta()
    except profiles.ProfilesError:
        raise ApiError("DATA_UNAVAILABLE")
    return {
        "data": data,
        "knowledge": {"documents": len(kb.documents()), "theses": sum(1 for _ in kb.search(topics=list(TOPICS), limit=1000, include_stale=True))},
        "news": len(store.all_items()),
        "llm": {"connected": llm.available(), "allowed_models": list(config.ALLOWED_MODELS), "usage": llm.usage()},
        "roles": [{"role": k, "name": v["name"]} for k, v in ROLES.items()],
        "topics": [{"topic": k, "name": v["name"]} for k, v in TOPICS.items()],
        "sectors": [{"sector": k, "name": v} for k, v in SECTOR_NAMES.items()],
    }


@router.get("/companies", responses=ERRORS)
async def list_companies(q: str = Query("", max_length=100), sector: str | None = Query(None, max_length=40),
                         limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    try:
        total, items = profiles.list_companies(q, sector, limit, offset)
    except profiles.ProfilesError:
        raise ApiError("DATA_UNAVAILABLE")
    return {"total": total, "items": items}


@router.get("/companies/{company_id}", responses=ERRORS)
async def company(company_id: str) -> dict:
    c = _company(company_id)
    return {"profile": c, "exposures": list(profiles.exposures(company_id))}


@router.get("/feed", responses=ERRORS)
async def news_feed(company_id: str, role: Role, topic: str | None = Query(None, max_length=40),
                    limit: int = Query(30, ge=1, le=100)) -> dict:
    _company(company_id)
    ranked = feed(store.all_items(), company_id, role, topic, limit)
    storage.log_event("feed_view", company_id=company_id, role=role)
    return {"company_id": company_id, "role": role, "items": [
        {"news": _news_brief(r["news"]), "relevance": r["relevance"],
         "cached_insight_id": (storage.cached_insight(company_id, role, r["news"]["news_id"]) or {}).get("insight_id")}
        for r in ranked]}


@router.get("/news/{news_id}", responses=ERRORS)
async def news(news_id: str) -> dict:
    return _news(news_id)


@router.post("/news", responses=ERRORS)
async def add_news(payload: NewsCreateRequest) -> dict:
    if payload.url:
        try:
            item = await asyncio.to_thread(parser.fetch_article, payload.url)
        except parser.FetchError as exc:
            raise ApiError("FETCH_FAILED", f"Не удалось загрузить материал: {exc}")
        except Exception:
            raise ApiError("FETCH_FAILED")
    elif payload.text and len(payload.text.strip()) >= 40:
        title = (payload.title or payload.text.strip().split(".")[0])[:300]
        item = store.make_item(title, payload.text, "Добавлено пользователем", None, None, "user")
    else:
        raise ApiError("INVALID_REQUEST", "Укажите ссылку или текст новости не короче 40 символов")
    saved, created = store.add(item)
    return {"created": created, "duplicate_of": None if created else saved["news_id"], "news": _news_brief(saved),
            "classification": saved["classification"]}


@router.post("/news/refresh", responses=ERRORS)
async def refresh_news() -> dict:
    return await asyncio.to_thread(parser.refresh)


@router.post("/insights", response_model=Insight, responses=ERRORS)
async def create_insight(payload: InsightRequest, request: Request) -> dict:
    request_id: str = request.state.request_id
    c = _company(payload.company_id)
    n = _news(payload.news_id)
    if not payload.force_refresh:
        cached = storage.cached_insight(c["company_id"], payload.role, n["news_id"])
        if cached:
            storage.log_event("insight_open", insight_id=cached["insight_id"], cached=True)
            return cached
    try:
        insight = await asyncio.wait_for(orchestrator.run(c, payload.role, n, request_id), timeout=config.analysis_timeout())
    except asyncio.TimeoutError:
        raise ApiError("ANALYSIS_TIMEOUT")
    except AnalysisUnavailable:
        raise ApiError("ANALYSIS_UNAVAILABLE")
    except InvalidAnalysisResult:
        raise ApiError("INVALID_ANALYSIS_RESULT")
    except Exception:
        logger.exception("analysis failed request_id=%s", request_id)
        raise ApiError("INTERNAL_ERROR")
    if (insight["company_id"], insight["news_id"], insight["role"], insight["request_id"]) != (
            c["company_id"], n["news_id"], payload.role, request_id):
        raise ApiError("INVALID_ANALYSIS_RESULT")
    storage.save_insight(insight)
    storage.log_event("insight_open", insight_id=insight["insight_id"], cached=False)
    return insight


@router.get("/insights/{insight_id}", response_model=Insight, responses=ERRORS)
async def get_insight(insight_id: str) -> dict:
    ins = storage.get_insight(insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    return ins


@router.post("/insights/{insight_id}/questions", response_model=Answer, responses=ERRORS)
async def ask(insight_id: str, payload: QuestionRequest) -> dict:
    ins = storage.get_insight(insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    c = _company(ins["company_id"])
    result = await asyncio.to_thread(qa.answer, ins, c, payload.question.strip())
    storage.log_event("question", insight_id=insight_id, refused=result["refused"], mode=result["mode"])
    return result


@router.post("/feedback", responses=ERRORS)
async def feedback(payload: FeedbackRequest) -> dict:
    if storage.get_insight(payload.insight_id) is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    storage.add_feedback(payload.model_dump())
    return {"status": "ok"}


@router.get("/metrics", responses=ERRORS)
async def metrics() -> dict:
    return storage.metrics()


@router.get("/analytics", responses=ERRORS)
async def analytics() -> dict:
    docs = sorted(kb.documents(), key=lambda d: d["date"], reverse=True)
    theses = kb.search(topics=list(TOPICS), limit=1000, include_stale=True)
    pdf_dir = config.bank_pdf_dir()
    return {"documents": [d | {"pdf_available": bool(pdf_dir and (pdf_dir / d["file"]).exists()),
                               "theses": sorted([t for t in theses if t["doc_id"] == d["doc_id"]], key=lambda t: (t["page"], t["id"]))}
                          for d in docs]}


@router.get("/analytics/{doc_id}/pdf", responses=ERRORS)
async def analytics_pdf(doc_id: str):
    doc = kb.document(doc_id)
    pdf_dir = config.bank_pdf_dir()
    if doc is None or pdf_dir is None:
        raise ApiError("DOCUMENT_NOT_FOUND")
    path = (pdf_dir / doc["file"]).resolve()
    if path.parent != pdf_dir.resolve() or not path.exists():
        raise ApiError("DOCUMENT_NOT_FOUND")
    return FileResponse(path, media_type="application/pdf", filename=Path(doc["file"]).name)


@router.get("/audit", responses=ERRORS)
async def audit_log(limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"items": audit.tail(limit)}
