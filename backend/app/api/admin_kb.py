"""Экран аналитика банка (SPR3-03): загрузка PDF, черновики тезисов, правка, публикация и отклонение.

Только сотрудникам банка (OPERATOR_EMAILS). Распознавание идет в воркере (задача kb_ingest): API лишь
сохраняет файл и ставит задачу, поэтому загрузка отвечает сразу.
"""

import asyncio

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.api.router import ERRORS
from app.auth.deps import check_origin, require_operator
from app.errors import ApiError
from app.knowledge import ingest
from app.schemas import KbApproveRequest, KbDocumentMeta, KbDraftPatch, KbRejectRequest
from app.worker import queue as jobs

router = APIRouter(prefix="/api/v1/admin/kb", dependencies=[Depends(check_origin), Depends(require_operator)])


def _invalid(exc: ingest.IngestError) -> ApiError:
    return ApiError("INVALID_REQUEST", str(exc))


@router.get("/documents", responses=ERRORS)
def kb_documents() -> dict:
    return {"items": ingest.uploads()}


@router.post("/documents", responses=ERRORS, status_code=202)
async def kb_upload(request: Request, name: str = Query(..., min_length=1, max_length=200),
                    title: str | None = Query(None, max_length=300), date: str | None = Query(None, max_length=10),
                    user: dict = Depends(require_operator)) -> dict:
    """PDF телом запроса (до 20 МБ). Тот же файл повторно не распознается."""
    data = await request.body()
    try:
        result = await asyncio.to_thread(ingest.upload, name, data, {"title": title, "date": date}, user["email"])
    except ingest.IngestError as exc:
        raise _invalid(exc)
    except Exception:  # поврежденный PDF
        raise ApiError("INVALID_REQUEST", "Не удалось прочитать PDF")
    if result["created"]:
        await asyncio.to_thread(jobs.enqueue, "kb_ingest", {"doc_id": result["doc_id"]},
                                dedupe_key=f"kb_ingest:{result['doc_id']}", max_attempts=3)
    return result


@router.post("/demo", responses=ERRORS, status_code=202)
def kb_upload_demo(user: dict = Depends(require_operator)) -> dict:
    """Синтетический демо-обзор ЦМА (не материал банка): показать конвейер без своего PDF и без трат на модель."""
    result = ingest.upload(ingest.DEMO_NAME, ingest.demo_pdf(), {}, user["email"])
    if result["created"]:
        jobs.enqueue("kb_ingest", {"doc_id": result["doc_id"]}, dedupe_key=f"kb_ingest:{result['doc_id']}", max_attempts=3)
    return result


@router.get("/documents/{doc_id}", responses=ERRORS)
def kb_document(doc_id: str) -> dict:
    found = ingest.document(doc_id)
    if found is None:
        raise ApiError("DOCUMENT_NOT_FOUND")
    return found


@router.patch("/documents/{doc_id}", responses=ERRORS)
def kb_document_meta(doc_id: str, payload: KbDocumentMeta) -> dict:
    try:
        return ingest.set_document_meta(doc_id, payload.title, payload.date)
    except ingest.IngestError:
        raise ApiError("DOCUMENT_NOT_FOUND")


@router.get("/documents/{doc_id}/pdf", responses=ERRORS)
def kb_pdf(doc_id: str) -> Response:
    found = ingest.pdf(doc_id)
    if found is None:
        raise ApiError("DOCUMENT_NOT_FOUND")
    return Response(found[1], media_type="application/pdf")


@router.get("/documents/{doc_id}/pages/{page}/image", responses=ERRORS)
def kb_page_image(doc_id: str, page: int) -> Response:
    """Изображение страницы (скан) рядом с черновиком; у текстового PDF — 404, экран показывает текст страницы."""
    found = ingest.page_image(doc_id, page)
    if found is None:
        raise ApiError("DOCUMENT_NOT_FOUND")
    return Response(found[1], media_type=found[0], headers={"Cache-Control": "private, max-age=3600"})


@router.patch("/drafts/{draft_id}", responses=ERRORS)
def kb_edit_draft(draft_id: str, payload: KbDraftPatch) -> dict:
    try:
        return ingest.update_draft(draft_id, payload.model_dump(exclude_unset=True))
    except ingest.IngestError as exc:
        raise _invalid(exc)


@router.post("/drafts/{draft_id}/approve", responses=ERRORS)
def kb_approve(draft_id: str, payload: KbApproveRequest, user: dict = Depends(require_operator)) -> dict:
    try:
        return {"thesis": ingest.approve(draft_id, user["email"], payload.supersedes)}
    except ingest.IngestError as exc:
        raise _invalid(exc)


@router.post("/drafts/{draft_id}/reject", responses=ERRORS)
def kb_reject(draft_id: str, payload: KbRejectRequest, user: dict = Depends(require_operator)) -> dict:
    try:
        return ingest.reject(draft_id, user["email"], payload.reason)
    except ingest.IngestError as exc:
        raise _invalid(exc)
