"""Админка доменной конфигурации (SPR4-00): отрасли, темы и действия как данные. Только сотрудникам банка.

Аналитик правит YAML, видит ошибки валидатора, смотрит превью «как изменится лента компании» и публикует
версию без деплоя; откат — публикация прежней версии. После публикации воркер переклассифицирует новости.
"""

import uuid

from fastapi import APIRouter, Depends

from app.api.router import ERRORS
from app.auth.deps import check_origin, require_operator
from app.domain_config import loader, preview, runtime
from app.domain_config.validate import validate_texts
from app.errors import ApiError
from app.schemas import DomainConfigPreviewRequest, DomainConfigPublish, DomainConfigTexts
from app.worker import queue as jobs

router = APIRouter(prefix="/api/v1/admin/config", dependencies=[Depends(check_origin), Depends(require_operator)])


def _texts(payload: DomainConfigTexts) -> dict[str, str]:
    return {"topics": payload.topics, "sectors": payload.sectors, "language": payload.language}


@router.get("", responses=ERRORS)
def config_current() -> dict:
    texts, version = loader.current_texts()
    _, issues = validate_texts(texts)
    return {"version": version, "signature": runtime.signature(), "texts": texts,
            "issues": [i.as_dict() for i in issues], "versions": loader.versions()}


@router.post("/validate", responses=ERRORS)
def config_validate(payload: DomainConfigTexts) -> dict:
    _, issues = validate_texts(_texts(payload))
    return {"ok": not any(i.level == "error" for i in issues), "issues": [i.as_dict() for i in issues]}


@router.post("/preview", responses=ERRORS, status_code=202)
def config_preview(payload: DomainConfigPreviewRequest) -> dict:
    preview_id = uuid.uuid4().hex[:12]
    preview.save(preview_id, {"status": "queued"})
    jobs.enqueue("domain_config_preview", {"id": preview_id, "texts": _texts(payload), "company_id": payload.company_id,
                                           "role": payload.role}, max_attempts=1)
    return {"id": preview_id, "status": "queued"}


@router.get("/preview/{preview_id}", responses=ERRORS)
def config_preview_result(preview_id: str) -> dict:
    found = preview.get(preview_id)
    if found is None:
        raise ApiError("INVALID_REQUEST", "Превью не найдено")
    return found


def _published(result: dict) -> dict:
    jobs.enqueue("domain_config_apply", {"version": result["id"]}, dedupe_key=f"domain_config_apply:{result['id']}")
    return result


@router.post("/publish", responses=ERRORS)
def config_publish(payload: DomainConfigPublish, user: dict = Depends(require_operator)) -> dict:
    try:
        return _published(loader.publish(_texts(payload), user["email"], payload.note))
    except loader.ConfigError as exc:
        raise ApiError("INVALID_REQUEST", f"Конфигурация не прошла проверку: {len(exc.issues)} ошибок")


@router.post("/versions/{version_id}/rollback", responses=ERRORS)
def config_rollback(version_id: int, user: dict = Depends(require_operator)) -> dict:
    try:
        return _published(loader.rollback(version_id, user["email"]))
    except LookupError:
        raise ApiError("INVALID_REQUEST", "Версия не найдена")
    except loader.ConfigError:
        raise ApiError("INVALID_REQUEST", "Версия не проходит текущую проверку")
