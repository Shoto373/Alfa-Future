import asyncio
import logging
import os

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from app.analysis import service as analysis_service
from app.api.errors import ApiError
from app.companies import repository
from app.errors import AnalysisUnavailable, InvalidAnalysisResult
from app.schemas import CompanyProfile, ErrorResponse, Insight, InsightRequest

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/api/v1")

INSIGHT_ERRORS = {status: {"model": ErrorResponse} for status in (400, 404, 413, 500, 503, 504)}


class CompanyList(BaseModel):
    items: list[CompanyProfile]


def analysis_timeout() -> float:
    return float(os.environ.get("ANALYSIS_TIMEOUT_SECONDS", "5"))


def _load(loader, *args):
    try:
        return loader(*args)
    except repository.FixturesError:
        logger.exception("fixtures error")
        raise ApiError("INTERNAL_ERROR")


@router.get("/companies", response_model=CompanyList, responses={500: {"model": ErrorResponse}})
async def list_companies() -> CompanyList:
    return CompanyList(items=_load(repository.load_companies))


@router.post("/insights", response_model=Insight, responses=INSIGHT_ERRORS)
async def create_insight(payload: InsightRequest, request: Request) -> Insight:
    request_id: str = request.state.request_id

    company = _load(repository.get_company, payload.company_id)
    if company is None:
        raise ApiError("COMPANY_NOT_FOUND")
    event = _load(repository.get_event, payload.event_id)
    if event is None:
        raise ApiError("EVENT_NOT_FOUND")

    # Вызываем через модуль, а не импортированное имя: тесты подменяют функцию.
    try:
        result = await asyncio.wait_for(
            analysis_service.generate_insight(company, payload.role, event, request_id),
            timeout=analysis_timeout(),
        )
    except asyncio.TimeoutError:
        raise ApiError("ANALYSIS_TIMEOUT")
    except AnalysisUnavailable:
        raise ApiError("ANALYSIS_UNAVAILABLE")
    except InvalidAnalysisResult:
        raise ApiError("INVALID_ANALYSIS_RESULT")
    except Exception:
        logger.exception("analysis failed request_id=%s", request_id)
        raise ApiError("INTERNAL_ERROR")

    try:
        raw = result.model_dump() if isinstance(result, BaseModel) else result
        insight = Insight.model_validate(raw)
    except ValidationError:
        raise ApiError("INVALID_ANALYSIS_RESULT")

    expected = (request_id, payload.company_id, payload.event_id, payload.role)
    actual = (insight.request_id, insight.company_id, insight.event_id, insight.role)
    if actual != expected:
        logger.warning("analysis context mismatch request_id=%s", request_id)
        raise ApiError("INVALID_ANALYSIS_RESULT")

    return insight
