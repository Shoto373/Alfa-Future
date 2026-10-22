"""Зависимости FastAPI: текущий пользователь, членство и права администратора компании."""

from fastapi import Cookie, Depends, Request

from app import config
from app.api.errors import ApiError
from app.auth import store

COOKIE = "session"
_SAFE = {"GET", "HEAD", "OPTIONS"}


def check_origin(request: Request) -> None:
    """Дополнительная защита от CSRF: изменяющий запрос из чужого Origin отклоняется."""
    origin = request.headers.get("origin")
    if request.method not in _SAFE and origin and origin not in config.frontend_origins():
        raise ApiError("FORBIDDEN")


def current_user(session: str | None = Cookie(None)) -> dict:
    user = store.session_user(session)
    if user is None:
        raise ApiError("UNAUTHORIZED")
    return store.user_view(user)


def member_of(user: dict, company_id: str) -> dict:
    """Членство пользователя в компании; чужая и несуществующая компании неразличимы (403)."""
    m = next((m for m in user["memberships"] if m["company_id"] == company_id), None)
    if m is None:
        raise ApiError("FORBIDDEN")
    return m


def require_member(company_id: str, user: dict = Depends(current_user)) -> dict:
    """Участник компании из path/query-параметра company_id; возвращает его членство."""
    return member_of(user, company_id)


def require_admin(company_id: str, user: dict = Depends(current_user)) -> dict:
    m = member_of(user, company_id)
    if not m["is_admin"]:
        raise ApiError("FORBIDDEN")
    return m


def require_any_admin(user: dict = Depends(current_user)) -> dict:
    if not any(m["is_admin"] for m in user["memberships"]):
        raise ApiError("FORBIDDEN")
    return user
