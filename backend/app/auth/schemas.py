"""Модели запросов и ответов аутентификации."""

import re
from typing import Literal

from pydantic import Field, field_validator

from app.schemas import Role, Strict

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def _norm_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.match(v):
        raise ValueError("invalid email")
    return v


class RegisterRequest(Strict):
    name: str = Field(..., min_length=1, max_length=80)
    email: str
    password: str = Field(..., min_length=8, max_length=128)
    _email = field_validator("email")(_norm_email)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty name")
        return v


class LoginRequest(Strict):
    email: str
    password: str = Field(..., min_length=1, max_length=128)
    _email = field_validator("email")(_norm_email)


class ClaimRequest(Strict):
    role: Role


class MemberCreateRequest(Strict):
    email: str
    role: Role
    is_admin: bool = False
    _email = field_validator("email")(_norm_email)


class MemberUpdateRequest(Strict):
    role: Role | None = None
    is_admin: bool | None = None


class Membership(Strict):
    company_id: str
    company_name: str
    role: Role
    is_admin: bool
    is_founder: bool


class User(Strict):
    user_id: str
    name: str
    email: str
    memberships: list[Membership]
    is_operator: bool = False  # сотрудник банка (OPERATOR_EMAILS): блок «Сервис банка» в профиле
    is_manager: bool = False  # менеджер банка с закрепленными клиентами: кабинет менеджера (SPR4-06)


class Member(Strict):
    member_id: str
    user_id: str | None
    name: str | None
    email: str
    role: Role
    is_admin: bool
    is_founder: bool
    status: Literal["active", "invited"]


class MembersResponse(Strict):
    members: list[Member]
