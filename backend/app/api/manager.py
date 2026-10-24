"""Связь с банком (SPR4-06): предложения по потребности, заявка «обсудить с менеджером» и кабинет менеджера.

Клиент видит предложение только при выявленной потребности и отправляет заявку только с явным согласием.
Менеджер видит клиентов, затронутых событиями, и заявки — только своих закрепленных компаний;
чужая заявка для него неотличима от несуществующей. Закрепляет клиентов сотрудник банка (оператор).
"""

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app import ranking, storage
from app.api.router import ERRORS, _company
from app.auth import store as auth_store
from app.auth.deps import check_origin, current_user, member_of, require_operator
from app.errors import ApiError
from app.news import store
from app.offers import leads, needs
from app.schemas import LeadRequest, LeadStatusRequest, ManagerAssignRequest

router = APIRouter(prefix="/api/v1", dependencies=[Depends(check_origin)])
PRIORITY_FORMULA = "оценка события × (0,7 + 0,06 × порядок выручки сверх 1 млн ₽)"


def _insight_for(insight_id: str, user: dict) -> tuple[dict, dict]:
    ins = storage.get_insight(insight_id)
    if ins is None:
        raise ApiError("INSIGHT_NOT_FOUND")
    return ins, member_of(user, ins["company_id"])


def _offers(ins: dict) -> list[dict]:
    news = store.get(ins["news_id"])
    return needs.offers_for(ins, _company(ins["company_id"]), news) if news else []


@router.get("/insights/{insight_id}/offers", responses=ERRORS)
def insight_offers(insight_id: str, user: dict = Depends(current_user)) -> dict:
    """Предложения банка к разбору: только при потребности; плюс уже отправленные пользователем заявки."""
    ins, _ = _insight_for(insight_id, user)
    return {"offers": _offers(ins), "leads": leads.of_user(user["user_id"], insight_id), "consent_text": leads.CONSENT_TEXT}


@router.post("/leads", responses=ERRORS, status_code=201)
def create_lead(payload: LeadRequest, user: dict = Depends(current_user)) -> dict:
    ins, membership = _insight_for(payload.insight_id, user)
    offer = next((o for o in _offers(ins) if o["offer_id"] == payload.offer_id), None)
    if offer is None:
        raise ApiError("INVALID_REQUEST", "Предложение для этого разбора не показывалось")
    company = _company(ins["company_id"])
    lead, created = leads.create(user, membership["role"], ins, offer, company["display_name"], payload.comment)
    if created:
        storage.log_event("lead_created", offer_id=offer["offer_id"])  # вебхук CRM — заглушка: заявка только в кабинете
    return {**lead, "created": created, "managers": len(leads.managers_of(ins["company_id"]))}


# --- кабинет менеджера ---

def require_manager(user: dict = Depends(current_user)) -> dict:
    """Менеджер банка: работает только с закрепленными за ним компаниями."""
    companies = leads.companies_of(user["email"])
    if not companies:
        raise ApiError("FORBIDDEN")
    return {**user, "companies": companies}


def _role(company_id: str) -> str:
    members = [m for m in auth_store.list_members(company_id) if m["user_id"]]
    return members[0]["role"] if members else "ceo"


def _priority(score: float, revenue: float | None) -> float:
    size = max(0.0, math.log10(max(revenue or 0, 1e6)) - 6)
    return round(score * (0.7 + 0.06 * size), 1)


def _client(company_id: str, since: str, new_leads: int) -> dict | None:
    company = _company(company_id)
    events = [r for r in ranking.company_feed(company_id, _role(company_id)) if r["news"]["published_at"] >= since][:5]
    top = events[0]["relevance"]["score"] if events else 0
    return {"company_id": company_id, "name": company["display_name"], "sector": company["sector_name"],
            "revenue": company.get("revenue"), "priority": _priority(top, company.get("revenue")), "new_leads": new_leads,
            "events": [{"news_id": r["news"]["news_id"], "title": r["news"]["title"], "score": r["relevance"]["score"],
                        "published_at": r["news"]["published_at"]} for r in events]}


@router.get("/manager/clients", responses=ERRORS)
def manager_clients(hours: int = Query(24, ge=1, le=24 * 30), user: dict = Depends(require_manager)) -> dict:
    """Клиенты, затронутые событиями за окно (по умолчанию сутки), по приоритету: оценка события и размер бизнеса."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    new = {}
    for lead in leads.of_companies(user["companies"], with_contact=False):
        new[lead["company_id"]] = new.get(lead["company_id"], 0) + (lead["status"] == "new")
    clients = [_client(cid, since, new.get(cid, 0)) for cid in sorted(user["companies"])]
    clients.sort(key=lambda c: (c["priority"], c["new_leads"]), reverse=True)
    return {"hours": hours, "priority_formula": PRIORITY_FORMULA, "clients": clients}


@router.get("/manager/leads", responses=ERRORS)
def manager_leads(user: dict = Depends(require_manager)) -> dict:
    return {"items": leads.of_companies(user["companies"])}


@router.get("/manager/leads.csv", responses=ERRORS)
def manager_leads_csv(user: dict = Depends(require_manager)) -> Response:
    """Выгрузка заявок своих клиентов (вместо отправки во внешнюю CRM)."""
    return Response("﻿" + leads.to_csv(leads.of_companies(user["companies"])), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.patch("/manager/leads/{lead_id}", responses=ERRORS)
def manager_lead_status(lead_id: int, payload: LeadStatusRequest, user: dict = Depends(require_manager)) -> dict:
    lead = leads.set_status(lead_id, payload.status, user["companies"])
    if lead is None:
        raise ApiError("LEAD_NOT_FOUND")
    return lead


# --- закрепление клиентов (сотрудник банка) ---

@router.get("/admin/managers", responses=ERRORS, dependencies=[Depends(require_operator)])
def managers_list(company_id: str = Query(..., max_length=64)) -> dict:
    return {"company_id": company_id, "managers": leads.managers_of(company_id)}


@router.post("/admin/managers", responses=ERRORS, dependencies=[Depends(require_operator)])
def managers_assign(payload: ManagerAssignRequest) -> dict:
    _company(payload.company_id)
    leads.assign(payload.email, payload.company_id)
    return {"company_id": payload.company_id, "managers": leads.managers_of(payload.company_id)}


@router.delete("/admin/managers", responses=ERRORS, dependencies=[Depends(require_operator)])
def managers_unassign(email: str = Query(..., max_length=200), company_id: str = Query(..., max_length=64)) -> dict:
    leads.unassign(email, company_id)
    return {"company_id": company_id, "managers": leads.managers_of(company_id)}
