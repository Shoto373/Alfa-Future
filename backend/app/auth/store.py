"""Пользователи, членство в компаниях и сессии (users/memberships/sessions.json в RUNTIME_DIR).

Приглашение — это членство с user_id=None; при регистрации с тем же email оно привязывается к пользователю.
Все изменения идут под одной блокировкой, запись атомарная (tmp + replace).
"""

import copy
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from app import config
from app.api.errors import ApiError
from app.auth import security
from app.companies import profiles

_lock = threading.RLock()
MAX_COMPANIES_PER_USER = 5
MAX_MEMBERS_PER_COMPANY = 100


_parsed: dict[str, tuple[tuple[int, int, int], object]] = {}  # путь -> (inode, mtime_ns, size), разобранный JSON


def _read(name: str, key: str):
    """Файл читается с диска только после изменения (запись атомарная: новый mtime и inode).

    Возвращается копия: вызывающий код меняет результат перед _write.
    """
    path = config.runtime_dir() / name
    try:
        st = path.stat()
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        hit = _parsed.get(str(path))
        if hit is None or hit[0] != stamp:
            hit = (stamp, json.loads(path.read_text(encoding="utf-8"))[key])
            _parsed[str(path)] = hit
        return copy.deepcopy(hit[1])
    except (OSError, ValueError, KeyError):
        return [] if key == "members" else {}


def _write(name: str, key: str, value) -> None:
    path = config.runtime_dir() / name
    tmp = path.with_name(f"{name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps({key: value}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- пользователи ----

def create_user(name: str, email: str, password: str) -> dict:
    salt, digest = security.hash_password(password)
    with _lock:
        users = _read("users.json", "users")
        if any(u["email"] == email for u in users.values()):
            raise ApiError("EMAIL_TAKEN")
        user = {"user_id": f"usr-{uuid.uuid4().hex[:12]}", "name": name, "email": email,
                "pw_salt": salt, "pw_hash": digest, "created_at": _now()}
        users[user["user_id"]] = user
        _write("users.json", "users", users)
        members = _read("memberships.json", "members")
        changed = False
        for m in members:  # ожидающие приглашения на этот email
            if m["user_id"] is None and m["email"] == email:
                m["user_id"] = user["user_id"]
                changed = True
        if changed:
            _write("memberships.json", "members", members)
    return user


def find_user_by_email(email: str) -> dict | None:
    return next((u for u in _read("users.json", "users").values() if u["email"] == email), None)


def get_user(user_id: str) -> dict | None:
    return _read("users.json", "users").get(user_id)


def _company_name(company_id: str) -> str:
    try:
        c = profiles.get(company_id)
    except profiles.ProfilesError:
        c = None
    return c["display_name"] if c else company_id


def founder_id(members: list[dict], company_id: str) -> str | None:
    """Основатель компании — тот, кто её зарегистрировал; у старых записей — самый ранний администратор."""
    admins = [m for m in _active_admins(members, company_id)]
    flagged = next((m for m in admins if m.get("founder")), None)
    if flagged:
        return flagged["member_id"]
    return min(admins, key=lambda m: m["created_at"])["member_id"] if admins else None


def membership_view(m: dict, members: list[dict] | None = None) -> dict:
    members = members if members is not None else _read("memberships.json", "members")
    return {"company_id": m["company_id"], "company_name": _company_name(m["company_id"]),
            "role": m["role"], "is_admin": m["is_admin"],
            "is_founder": founder_id(members, m["company_id"]) == m["member_id"]}


def user_view(user: dict) -> dict:
    members = _read("memberships.json", "members")
    mine = [m for m in members if m["user_id"] == user["user_id"]]
    return {"user_id": user["user_id"], "name": user["name"], "email": user["email"],
            "memberships": [membership_view(m, members) for m in mine]}


# ---- сессии ----

def create_session(user_id: str) -> str:
    token = security.new_token()
    now = time.time()
    with _lock:
        sessions = {k: v for k, v in _read("sessions.json", "sessions").items() if v["expires_at"] > now}
        sessions[security.hash_token(token)] = {"user_id": user_id, "expires_at": now + security.SESSION_TTL}
        _write("sessions.json", "sessions", sessions)
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    s = _read("sessions.json", "sessions").get(security.hash_token(token))
    if not s or s["expires_at"] <= time.time():
        return None
    return get_user(s["user_id"])


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _read("sessions.json", "sessions")
        if sessions.pop(security.hash_token(token), None) is not None:
            _write("sessions.json", "sessions", sessions)


# ---- членство ----

def _active_admins(members: list[dict], company_id: str) -> list[dict]:
    return [m for m in members if m["company_id"] == company_id and m["is_admin"] and m["user_id"]]


def claimed_ids() -> set[str]:
    return {m["company_id"] for m in _read("memberships.json", "members") if m["is_admin"] and m["user_id"]}


def claim(user_id: str, company_id: str, role: str) -> dict:
    with _lock:
        members = _read("memberships.json", "members")
        if _active_admins(members, company_id):
            raise ApiError("COMPANY_CLAIMED")
        if sum(m["user_id"] == user_id for m in members) >= MAX_COMPANIES_PER_USER:
            raise ApiError("TOO_MANY_COMPANIES")
        mine = next((m for m in members if m["company_id"] == company_id and m["user_id"] == user_id), None)
        if mine:
            mine["role"], mine["is_admin"], mine["founder"] = role, True, True
        else:
            mine = {"member_id": f"mem-{uuid.uuid4().hex[:12]}", "company_id": company_id, "user_id": user_id,
                    "email": get_user(user_id)["email"], "role": role, "is_admin": True, "founder": True,
                    "created_at": _now()}
            members.append(mine)
        _write("memberships.json", "members", members)
    return mine


def list_members(company_id: str) -> list[dict]:
    users = _read("users.json", "users")
    all_members = _read("memberships.json", "members")
    founder = founder_id(all_members, company_id)
    out = []
    for m in all_members:
        if m["company_id"] != company_id:
            continue
        u = users.get(m["user_id"]) if m["user_id"] else None
        out.append({"member_id": m["member_id"], "user_id": m["user_id"], "name": u["name"] if u else None,
                    "email": m["email"], "role": m["role"], "is_admin": m["is_admin"],
                    "is_founder": m["member_id"] == founder, "status": "active" if m["user_id"] else "invited"})
    return out


def member_view(company_id: str, member_id: str) -> dict:
    return next(m for m in list_members(company_id) if m["member_id"] == member_id)


def add_member(company_id: str, email: str, role: str, is_admin: bool) -> dict:
    with _lock:
        members = _read("memberships.json", "members")
        in_company = [m for m in members if m["company_id"] == company_id]
        if any(m["email"] == email for m in in_company):
            raise ApiError("MEMBER_EXISTS")
        if len(in_company) >= MAX_MEMBERS_PER_COMPANY:
            raise ApiError("INVALID_REQUEST", "Достигнут предел числа участников компании")
        user = find_user_by_email(email)
        m = {"member_id": f"mem-{uuid.uuid4().hex[:12]}", "company_id": company_id,
             "user_id": user["user_id"] if user else None, "email": email, "role": role,
             "is_admin": is_admin, "created_at": _now()}
        members.append(m)
        _write("memberships.json", "members", members)
    return member_view(company_id, m["member_id"])


def _find(members: list[dict], company_id: str, member_id: str) -> dict:
    m = next((m for m in members if m["member_id"] == member_id and m["company_id"] == company_id), None)
    if m is None:
        raise ApiError("MEMBER_NOT_FOUND")
    return m


def get_member(company_id: str, member_id: str) -> dict:
    return dict(_find(_read("memberships.json", "members"), company_id, member_id))


def update_member(company_id: str, member_id: str, role: str | None, is_admin: bool | None) -> dict:
    with _lock:
        members = _read("memberships.json", "members")
        m = _find(members, company_id, member_id)
        was_admin = bool(m["is_admin"] and m["user_id"])
        if role is not None:
            m["role"] = role
        if is_admin is not None:
            m["is_admin"] = is_admin
        if was_admin and not _active_admins(members, company_id):
            raise ApiError("LAST_ADMIN")
        _write("memberships.json", "members", members)
    return member_view(company_id, member_id)


def remove_member(company_id: str, member_id: str) -> None:
    with _lock:
        members = _read("memberships.json", "members")
        m = _find(members, company_id, member_id)
        members.remove(m)
        if m["is_admin"] and m["user_id"] and not _active_admins(members, company_id):
            raise ApiError("LAST_ADMIN")
        _write("memberships.json", "members", members)


def disband(company_id: str) -> None:
    """Расформировать компанию: убрать всех участников и приглашения, компания снова свободна для регистрации."""
    with _lock:
        members = _read("memberships.json", "members")
        _write("memberships.json", "members", [m for m in members if m["company_id"] != company_id])


def is_founder(company_id: str, member_id: str) -> bool:
    return founder_id(_read("memberships.json", "members"), company_id) == member_id
