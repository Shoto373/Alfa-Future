"""Продуктовая аналитика и эксперименты (SPR4-07): события воронки, флаги пользователя, отчет и настройка флагов."""

from fastapi import APIRouter, Depends, Query

from app import analytics_events, flags
from app.api.router import ERRORS
from app.auth.deps import check_origin, current_user, member_of, require_operator
from app.errors import ApiError
from app.schemas import FlagUpdateRequest, ProductEventRequest

router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_origin)])


@router.post("/events", responses=ERRORS, status_code=202)
def product_event(payload: ProductEventRequest, user: dict = Depends(current_user)) -> dict:
    role = member_of(user, payload.company_id)["role"] if payload.company_id else None
    try:
        analytics_events.record(payload.kind, user["user_id"], payload.company_id, role, payload.props)
    except analytics_events.EventError as exc:
        raise ApiError("INVALID_REQUEST", str(exc))
    return {"status": "accepted"}


@router.get("/flags", responses=ERRORS)
def user_flags(company_id: str | None = Query(None, max_length=64), user: dict = Depends(current_user)) -> dict:
    """Флаги и варианты экспериментов текущего пользователя (стабильны: зависят от хэша пользователя)."""
    if company_id:
        member_of(user, company_id)
    return {"flags": flags.evaluate(user["user_id"], company_id)}


@router.get("/admin/product", responses=ERRORS, dependencies=[Depends(require_operator)])
def product_report(days: int = Query(28, ge=7, le=90)) -> dict:
    return analytics_events.report(days)


@router.get("/admin/flags", responses=ERRORS, dependencies=[Depends(require_operator)])
def flags_list() -> dict:
    return {"flags": flags.settings()}


@router.put("/admin/flags/{key}", responses=ERRORS, dependencies=[Depends(require_operator)])
def flags_update(key: str, payload: FlagUpdateRequest) -> dict:
    if key not in flags.FLAGS:
        raise ApiError("INVALID_REQUEST", "Неизвестный флаг")
    return flags.save(key, payload.percent, payload.companies)
