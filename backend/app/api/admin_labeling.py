"""Экран разметки релевантности для аналитиков банка (SPR3-06). Только сотрудникам банка."""

from fastapi import APIRouter, Depends

from app import labeling
from app.api.router import ERRORS
from app.auth.deps import check_origin, require_operator
from app.schemas import LabelRequest

router = APIRouter(prefix="/api/v1/admin/labeling", dependencies=[Depends(check_origin), Depends(require_operator)])


@router.get("/next", responses=ERRORS)
def labeling_next(user: dict = Depends(require_operator)) -> dict:
    """Следующая пара для этого разметчика (без оценки и причин системы) и прогресс."""
    return {"pair": labeling.next_pair(user["email"]), "stats": labeling.stats()}


@router.post("/labels", responses=ERRORS)
def labeling_save(payload: LabelRequest, user: dict = Depends(require_operator)) -> dict:
    labeling.save(payload.news_id, payload.company_id, payload.role, payload.grade, payload.reason, user["email"])
    return {"pair": labeling.next_pair(user["email"]), "stats": labeling.stats()}


@router.get("/stats", responses=ERRORS)
def labeling_stats() -> dict:
    return labeling.stats()


@router.get("/export", responses=ERRORS)
def labeling_export() -> dict:
    """Разметка для scripts/eval_ranking.py и fit_ranking.py (--labels файл с этим ответом)."""
    return {"labels": labeling.labels()}
