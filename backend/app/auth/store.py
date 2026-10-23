"""Пользователи, членство в компаниях и сессии — в PostgreSQL (таблицы users, memberships, sessions).

Приглашение — это членство с user_id=None; при регистрации с тем же email оно привязывается к пользователю.
Email хранится в нижнем регистре и уникален. Изменения членства в компании идут в транзакции под
pg_advisory_xact_lock компании: «один основатель», «не убрать последнего администратора» и «одна
регистрация компании» соблюдаются при любом числе воркеров. Сессия хранит только SHA-256 токена и
истекает через SESSION_TTL_HOURS без активности (скользящее продление). Прежнее JSON-хранилище
переносится один раз: app.legacy_import.import_auth.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app import config, database
from app.api.errors import ApiError
from app.auth import security
from app.companies import profiles
from app.models import AuthMembership, AuthSession, AuthUser, LoginFailure

MAX_COMPANIES_PER_USER = 5
MAX_MEMBERS_PER_COMPANY = 100
SESSION_TOUCH = timedelta(minutes=5)  # чаще last_seen и срок не продлеваются — без записи на каждый запрос


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _lock_company(db, company_id: str) -> None:
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"company:{company_id}"))))


def _user_dict(u: AuthUser) -> dict:
    return {"user_id": u.user_id, "name": u.name, "email": u.email, "pw_salt": u.pw_salt, "pw_hash": u.pw_hash,
            "pw_params": u.pw_params, "created_at": _iso(u.created_at)}


def _member_dict(m: AuthMembership) -> dict:
    return {"member_id": m.member_id, "company_id": m.company_id, "user_id": m.user_id, "email": m.email,
            "role": m.role, "is_admin": m.is_admin, "founder": m.founder, "invited_by": m.invited_by,
            "created_at": _iso(m.created_at)}


def _members(db, company_id: str | None = None) -> list[dict]:
    query = select(AuthMembership).order_by(AuthMembership.created_at, AuthMembership.member_id)
    if company_id is not None:
        query = query.where(AuthMembership.company_id == company_id)
    return [_member_dict(m) for m in db.scalars(query)]


# ---- пользователи ----

def create_user(name: str, email: str, password: str) -> dict:
    salt, digest, params = security.hash_password(password)
    email = email.lower()
    user = AuthUser(user_id=f"usr-{uuid.uuid4().hex[:12]}", name=name, email=email, pw_salt=salt, pw_hash=digest,
                    pw_params=params, created_at=_now())
    try:
        with database.session() as db:
            db.add(user)
            db.flush()
            # Ожидающие приглашения на этот email.
            db.execute(update(AuthMembership).where(AuthMembership.email == email, AuthMembership.user_id.is_(None))
                       .values(user_id=user.user_id))
    except IntegrityError:
        raise ApiError("EMAIL_TAKEN") from None
    return _user_dict(user)


def find_user_by_email(email: str) -> dict | None:
    with database.session() as db:
        u = db.scalar(select(AuthUser).where(AuthUser.email == email.lower()))
        return _user_dict(u) if u else None


def get_user(user_id: str) -> dict | None:
    with database.session() as db:
        u = db.get(AuthUser, user_id)
        return _user_dict(u) if u else None


def rehash_if_needed(user: dict, password: str) -> None:
    """После успешного входа: пароль со старыми параметрами scrypt перехэшируется текущими."""
    if not security.needs_rehash(user.get("pw_params")):
        return
    salt, digest, params = security.hash_password(password)
    with database.session() as db:
        db.execute(update(AuthUser).where(AuthUser.user_id == user["user_id"])
                   .values(pw_salt=salt, pw_hash=digest, pw_params=params))


def _company_name(company_id: str) -> str:
    try:
        c = profiles.get(company_id)
    except profiles.ProfilesError:
        c = None
    return c["display_name"] if c else company_id


def founder_id(members: list[dict], company_id: str) -> str | None:
    """Основатель компании — тот, кто её зарегистрировал; у старых записей — самый ранний администратор."""
    admins = _active_admins(members, company_id)
    flagged = next((m for m in admins if m.get("founder")), None)
    if flagged:
        return flagged["member_id"]
    return min(admins, key=lambda m: m["created_at"])["member_id"] if admins else None


def membership_view(m: dict, members: list[dict] | None = None) -> dict:
    if members is None:
        with database.session() as db:
            members = _members(db, m["company_id"])
    return {"company_id": m["company_id"], "company_name": _company_name(m["company_id"]),
            "role": m["role"], "is_admin": m["is_admin"],
            "is_founder": founder_id(members, m["company_id"]) == m["member_id"]}


def user_view(user: dict) -> dict:
    with database.session() as db:
        # Приглашение, созданное одновременно с регистрацией (другой воркер), регистрация не увидела —
        # привязываем при чтении: обычно запрос ничего не меняет.
        db.execute(update(AuthMembership).where(AuthMembership.email == user["email"], AuthMembership.user_id.is_(None))
                   .values(user_id=user["user_id"]))
        mine = [_member_dict(m) for m in db.scalars(select(AuthMembership).where(AuthMembership.user_id == user["user_id"])
                                                    .order_by(AuthMembership.created_at, AuthMembership.member_id))]
        companies = {m["company_id"] for m in mine}
        members = [_member_dict(m) for m in db.scalars(select(AuthMembership)
                                                       .where(AuthMembership.company_id.in_(companies)))] if companies else []
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"],
            "memberships": [membership_view(m, members) for m in mine],
            "is_operator": user["email"].lower() in config.operator_emails()}


# ---- вход: блокировка после неудач (общая для всех воркеров) ----

def login_attempt(email: str, ip: str) -> bool:
    """Записывает попытку до проверки пароля и решает, можно ли проверять. False — 429.

    Запись до проверки: параллельные запросы с разных воркеров видят друг друга и не обходят лимит.
    Блокировка — по паре email + адрес (чужие неверные пароли не запирают владельца), плюс общий
    потолок на email против перебора с множества адресов. Успешный вход удаляет записи своего адреса.
    """
    email, now = email.lower(), _now()
    with database.session() as db:
        db.add(LoginFailure(email=email, ip=ip, at=now))
        db.execute(delete(LoginFailure).where(LoginFailure.at < now - timedelta(days=1)))  # не нужны для окна
    since = now - timedelta(seconds=security.FAIL_WINDOW_SECONDS)
    with database.session() as db:
        recent = select(func.count()).select_from(LoginFailure).where(LoginFailure.email == email, LoginFailure.at >= since)
        from_ip = db.scalar(recent.where(LoginFailure.ip == ip)) or 0
        total = db.scalar(recent) or 0
    return from_ip <= security.MAX_FAILS and total <= security.MAX_FAILS_PER_EMAIL


def login_succeeded(email: str, ip: str) -> None:
    with database.session() as db:
        db.execute(delete(LoginFailure).where(LoginFailure.email == email.lower(), LoginFailure.ip == ip))


# ---- сессии ----

def _ttl() -> timedelta:
    return timedelta(hours=config.session_ttl_hours())


def create_session(user_id: str) -> str:
    token = security.new_token()
    now = _now()
    with database.session() as db:
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
        db.add(AuthSession(token_hash=security.hash_token(token), user_id=user_id, created_at=now,
                           expires_at=now + _ttl(), last_seen=now))
    return token


def session_user(token: str | None) -> dict | None:
    """Пользователь живой сессии; активность продлевает срок (не чаще раза в SESSION_TOUCH)."""
    if not token:
        return None
    now = _now()
    with database.session() as db:
        s = db.get(AuthSession, security.hash_token(token))
        if s is None or s.expires_at <= now:
            return None
        if now - s.last_seen >= SESSION_TOUCH:
            s.last_seen, s.expires_at = now, now + _ttl()
        u = db.get(AuthUser, s.user_id)
        return _user_dict(u) if u else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    with database.session() as db:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == security.hash_token(token)))


# ---- членство ----

def _active_admins(members: list[dict], company_id: str) -> list[dict]:
    return [m for m in members if m["company_id"] == company_id and m["is_admin"] and m["user_id"]]


def claimed_ids() -> set[str]:
    with database.session() as db:
        return set(db.scalars(select(AuthMembership.company_id).distinct()
                              .where(AuthMembership.is_admin.is_(True), AuthMembership.user_id.is_not(None))))


def claim(user_id: str, company_id: str, role: str) -> dict:
    with database.session() as db:
        _lock_company(db, company_id)
        members = _members(db, company_id)
        if _active_admins(members, company_id):
            raise ApiError("COMPANY_CLAIMED")
        owned = db.scalar(select(func.count()).select_from(AuthMembership).where(AuthMembership.user_id == user_id)) or 0
        if owned >= MAX_COMPANIES_PER_USER:
            raise ApiError("TOO_MANY_COMPANIES")
        mine = db.scalar(select(AuthMembership).where(AuthMembership.company_id == company_id,
                                                      AuthMembership.user_id == user_id))
        if mine:
            mine.role, mine.is_admin, mine.founder = role, True, True
        else:
            mine = AuthMembership(member_id=f"mem-{uuid.uuid4().hex[:12]}", company_id=company_id, user_id=user_id,
                                  email=db.get(AuthUser, user_id).email, role=role, is_admin=True, founder=True,
                                  created_at=_now())
            db.add(mine)
        db.flush()
        return _member_dict(mine)


def list_members(company_id: str) -> list[dict]:
    with database.session() as db:
        members = _members(db, company_id)
        ids = [m["user_id"] for m in members if m["user_id"]]
        names = dict(db.execute(select(AuthUser.user_id, AuthUser.name).where(AuthUser.user_id.in_(ids))).all()) if ids else {}
    founder = founder_id(members, company_id)
    return [{"member_id": m["member_id"], "user_id": m["user_id"], "name": names.get(m["user_id"]),
             "email": m["email"], "role": m["role"], "is_admin": m["is_admin"],
             "is_founder": m["member_id"] == founder, "status": "active" if m["user_id"] else "invited"}
            for m in members]


def member_view(company_id: str, member_id: str) -> dict:
    return next(m for m in list_members(company_id) if m["member_id"] == member_id)


def add_member(company_id: str, email: str, role: str, is_admin: bool, invited_by: str | None = None) -> dict:
    email = email.lower()
    try:
        with database.session() as db:
            _lock_company(db, company_id)
            members = _members(db, company_id)
            if any(m["email"] == email for m in members):
                raise ApiError("MEMBER_EXISTS")
            if len(members) >= MAX_MEMBERS_PER_COMPANY:
                raise ApiError("INVALID_REQUEST", "Достигнут предел числа участников компании")
            user_id = db.scalar(select(AuthUser.user_id).where(AuthUser.email == email))
            member = AuthMembership(member_id=f"mem-{uuid.uuid4().hex[:12]}", company_id=company_id, user_id=user_id,
                                    email=email, role=role, is_admin=is_admin, founder=False, invited_by=invited_by,
                                    created_at=_now())
            db.add(member)
    except IntegrityError:
        raise ApiError("MEMBER_EXISTS") from None
    return member_view(company_id, member.member_id)


def _find(db, company_id: str, member_id: str) -> AuthMembership:
    m = db.scalar(select(AuthMembership).where(AuthMembership.member_id == member_id,
                                               AuthMembership.company_id == company_id))
    if m is None:
        raise ApiError("MEMBER_NOT_FOUND")
    return m


def get_member(company_id: str, member_id: str) -> dict:
    with database.session() as db:
        return _member_dict(_find(db, company_id, member_id))


def update_member(company_id: str, member_id: str, role: str | None, is_admin: bool | None) -> dict:
    with database.session() as db:
        _lock_company(db, company_id)
        m = _find(db, company_id, member_id)
        was_admin = bool(m.is_admin and m.user_id)
        if role is not None:
            m.role = role
        if is_admin is not None:
            m.is_admin = is_admin
        db.flush()
        if was_admin and not _active_admins(_members(db, company_id), company_id):
            raise ApiError("LAST_ADMIN")  # исключение откатывает транзакцию
    return member_view(company_id, member_id)


def remove_member(company_id: str, member_id: str) -> None:
    with database.session() as db:
        _lock_company(db, company_id)
        m = _find(db, company_id, member_id)
        was_admin = bool(m.is_admin and m.user_id)
        db.delete(m)
        db.flush()
        if was_admin and not _active_admins(_members(db, company_id), company_id):
            raise ApiError("LAST_ADMIN")


def disband(company_id: str) -> None:
    """Расформировать компанию: убрать всех участников и приглашения, компания снова свободна для регистрации."""
    with database.session() as db:
        _lock_company(db, company_id)
        db.execute(delete(AuthMembership).where(AuthMembership.company_id == company_id))


def is_founder(company_id: str, member_id: str) -> bool:
    with database.session() as db:
        return founder_id(_members(db, company_id), company_id) == member_id
