"""Эндпойнты регистрации, входа и управления участниками компаний."""


from fastapi import APIRouter, Depends, Request, Response

from app import config
from app.errors import ApiError
from app.api.router import ERRORS, company_or_404
from app.auth import security, store
from app.auth.deps import COOKIE, check_origin, client_ip, current_user, member_of, require_admin, require_member
from app.auth.schemas import (ClaimRequest, LoginRequest, Member, MemberCreateRequest, MembersResponse,
                              MemberUpdateRequest, Membership, RegisterRequest, User)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_origin)])


COOKIE_MAX_AGE = 30 * 24 * 3600  # срок без активности (SESSION_TTL_HOURS) проверяет сервер; cookie не продлевается


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", path="/",
                        secure=config.frontend_origin().startswith("https://"))


@router.post("/auth/register", status_code=201, response_model=User, responses=ERRORS)
def register(payload: RegisterRequest, response: Response) -> dict:
    user = store.create_user(payload.name, payload.email, payload.password)
    _set_cookie(response, store.create_session(user["user_id"]))
    return store.user_view(user)


@router.post("/auth/login", response_model=User, responses=ERRORS)
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    # 5 неудач с адреса на email за 15 минут (и 30 со всех адресов) — блокировка; счетчик в базе, общий для воркеров.
    ip = client_ip(request)
    if not store.login_attempt(payload.email, ip):
        raise ApiError("TOO_MANY_ATTEMPTS")
    user = store.find_user_by_email(payload.email)
    if user is None:
        security.verify_dummy(payload.password)
        ok = False
    else:
        ok = security.verify_password(payload.password, user["pw_salt"], user["pw_hash"], user["pw_params"])
    if not ok:
        raise ApiError("INVALID_CREDENTIALS")  # попытка уже записана
    store.login_succeeded(payload.email, ip)
    store.rehash_if_needed(user, payload.password)
    _set_cookie(response, store.create_session(user["user_id"]))
    return store.user_view(user)


@router.post("/auth/logout", status_code=204, response_class=Response, responses=ERRORS)
def logout(request: Request) -> Response:
    store.delete_session(request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")
    return response


@router.get("/auth/me", response_model=User, responses=ERRORS)
def me(user: dict = Depends(current_user)) -> dict:
    return user


@router.post("/companies/{company_id}/claim", status_code=201, response_model=Membership, responses=ERRORS)
def claim_company(company_id: str, payload: ClaimRequest, user: dict = Depends(current_user)) -> dict:
    company_or_404(company_id)
    return store.membership_view(store.claim(user["user_id"], company_id, payload.role))


@router.get("/companies/{company_id}/members", response_model=MembersResponse, responses=ERRORS)
def members(company_id: str, _m: dict = Depends(require_member)) -> dict:
    return {"members": store.list_members(company_id)}


@router.post("/companies/{company_id}/members", status_code=201, response_model=Member, responses=ERRORS)
def add_member(company_id: str, payload: MemberCreateRequest, _m: dict = Depends(require_admin),
               user: dict = Depends(current_user)) -> dict:
    return store.add_member(company_id, payload.email, payload.role, payload.is_admin, invited_by=user["user_id"])


@router.patch("/companies/{company_id}/members/{member_id}", response_model=Member, responses=ERRORS)
def update_member(company_id: str, member_id: str, payload: MemberUpdateRequest,
                        user: dict = Depends(current_user)) -> dict:
    if not member_of(user, company_id)["is_admin"]:
        raise ApiError("FORBIDDEN")
    target = store.get_member(company_id, member_id)
    if target["user_id"] == user["user_id"]:
        raise ApiError("FORBIDDEN", "Нельзя менять собственную роль и права")
    if store.is_founder(company_id, member_id):  # основателя не понижают и не переназначают
        raise ApiError("FORBIDDEN")
    return store.update_member(company_id, member_id, payload.role, payload.is_admin)


@router.delete("/companies/{company_id}/members/{member_id}", status_code=204, response_class=Response, responses=ERRORS)
def remove_member(company_id: str, member_id: str, user: dict = Depends(current_user)) -> Response:
    mine = member_of(user, company_id)
    target = store.get_member(company_id, member_id)
    if target["user_id"] != user["user_id"] and not mine["is_admin"]:
        raise ApiError("FORBIDDEN")
    if store.is_founder(company_id, member_id):  # основатель уходит только расформированием компании
        raise ApiError("FORBIDDEN")
    store.remove_member(company_id, member_id)
    return Response(status_code=204)


@router.delete("/companies/{company_id}", status_code=204, response_class=Response, responses=ERRORS)
def disband_company(company_id: str, m: dict = Depends(require_member)) -> Response:
    if not m["is_founder"]:
        raise ApiError("FORBIDDEN")
    store.disband(company_id)
    return Response(status_code=204)
