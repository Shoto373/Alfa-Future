"""Уведомления (SPR4-04): настройки подписки, сообщения в приложении, переходы из сводок, отписка из письма."""

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from app.api.router import ERRORS
from app.auth.deps import check_origin, current_user, member_of
from app.errors import ApiError
from app.news.taxonomy import TOPICS
from app.notifications import delivery, service, settings
from app.schemas import NotificationReadRequest, NotificationSettings

router = APIRouter(prefix="/api/v1/notifications", dependencies=[Depends(check_origin)])
public = APIRouter(prefix="/api/v1/notifications")  # отписка по ссылке из письма — без входа и без проверки Origin


def _view(company_id: str, found: dict) -> dict:
    return {"company_id": company_id, **{k: v for k, v in found.items() if k != "unsubscribe_token"}}


@router.get("/settings", responses=ERRORS)
def notification_settings(company_id: str = Query(..., max_length=64), user: dict = Depends(current_user)) -> dict:
    member_of(user, company_id)
    return _view(company_id, settings.get(user["user_id"], company_id))


@router.put("/settings", responses=ERRORS)
def notification_settings_save(payload: NotificationSettings, company_id: str = Query(..., max_length=64),
                               user: dict = Depends(current_user)) -> dict:
    member_of(user, company_id)
    changes = payload.model_dump(exclude_none=True)
    if "timezone" in changes and changes["timezone"] not in available_timezones():
        raise ApiError("INVALID_REQUEST", "Неизвестный часовой пояс")
    if any(t not in TOPICS for t in changes.get("topics", [])):
        raise ApiError("INVALID_REQUEST", "Неизвестная тема")
    return _view(company_id, settings.save(user["user_id"], company_id, changes))


@router.get("", responses=ERRORS)
def notifications(company_id: str = Query(..., max_length=64), user: dict = Depends(current_user)) -> dict:
    member_of(user, company_id)
    return delivery.inbox(user["user_id"], company_id)


@router.post("/read", responses=ERRORS)
def notifications_read(payload: NotificationReadRequest, user: dict = Depends(current_user)) -> dict:
    member_of(user, payload.company_id)
    return {"updated": delivery.mark_read(user["user_id"], payload.company_id, payload.ids)}


@router.post("/{delivery_id}/opened", responses=ERRORS)
def notification_opened(delivery_id: int, user: dict = Depends(current_user)) -> dict:
    """Переход из сводки или алерта (?from=digest|alert&d=id): чужая запись не отмечается."""
    return {"ok": delivery.opened(user["user_id"], delivery_id)}


@router.post("/test-digest", responses=ERRORS)
def notification_test_digest(company_id: str = Query(..., max_length=64), user: dict = Depends(current_user)) -> dict:
    """«Отправить тестовую сводку»: сразу, вне расписания. Меньше трех значимых событий — сводки нет."""
    role = member_of(user, company_id)["role"]
    return service.test_digest(user, company_id, role)


_PAGE = ("<!doctype html><html lang='ru'><meta charset='utf-8'><title>Альфа.Пульс</title>"
         "<body style='font-family:sans-serif;max-width:32rem;margin:4rem auto'><h1>Альфа.Пульс</h1><p>{}</p></body></html>")


@public.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str = Query(..., min_length=8, max_length=64)) -> HTMLResponse:
    ok = settings.unsubscribe_email(token)
    text = ("Письма отключены. Сводки в приложении остаются — их можно настроить в разделе «Уведомления»."
            if ok else "Ссылка устарела или уже использована.")
    return HTMLResponse(_PAGE.format(text), status_code=200 if ok else 404)


@public.post("/unsubscribe")
def unsubscribe_one_click(token: str = Query(..., min_length=8, max_length=64)) -> dict:
    """Отписка в один клик из почтового клиента (RFC 8058: List-Unsubscribe-Post)."""
    return {"ok": settings.unsubscribe_email(token)}
