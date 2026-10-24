"""Зависимости FastAPI: текущий пользователь, членство и права администратора компании."""

import ipaddress

from fastapi import Cookie, Depends, Request

from app import config, observability
from app.errors import ApiError
from app.auth import store

COOKIE = "session"
_SAFE = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str:
    """Адрес клиента. За nginx соединение приходит с внутреннего адреса, настоящий — в X-Real-IP;
    заголовку верим только от внутреннего адреса, иначе его подделал бы любой."""
    host = request.client.host if request.client else ""
    try:
        internal = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        internal = False
    forwarded = request.headers.get("x-real-ip", "").strip()
    return forwarded if internal and forwarded else host


def check_origin(request: Request) -> None:
    """Дополнительная защита от CSRF: изменяющий запрос из чужого Origin отклоняется."""
    origin = request.headers.get("origin")
    if request.method not in _SAFE and origin and origin not in config.frontend_origins():
        raise ApiError("FORBIDDEN")


def current_user(session: str | None = Cookie(None)) -> dict:
    user = store.session_user(session)
    if user is None:
        raise ApiError("UNAUTHORIZED")
    view = store.user_view(user)
    observability.set_user(view["user_id"])  # в логе запроса — псевдоним пользователя
    return view


def member_of(user: dict, company_id: str) -> dict:
    """Членство пользователя в компании; чужая и несуществующая компании неразличимы (403)."""
    observability.set_company(company_id)
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


def require_operator(user: dict = Depends(current_user)) -> dict:
    """Сотрудник банка из OPERATOR_EMAILS. Сводные данные по всем клиентам (метрики, расходы, аудит)
    не открываются администратору компании-клиента: он видит только свою компанию."""
    if user["email"].lower() not in config.operator_emails():
        raise ApiError("FORBIDDEN")
    return user
