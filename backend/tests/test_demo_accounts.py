"""Готовые учетные записи для локальной проверки: вход без регистрации, повторный старт ничего не ломает,
в production их нет."""

from pathlib import Path

import pytest

from app import demo_accounts
from app.auth import store

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[2]


def test_demo_accounts_are_off_by_default(raw_client, monkeypatch):
    monkeypatch.delenv("DEMO_ACCOUNTS", raising=False)
    assert demo_accounts.ensure() is None
    assert store.find_user_by_email("demo@alfa.test") is None


def test_demo_accounts_open_a_ready_feed(raw_client, new_client, monkeypatch):
    monkeypatch.setenv("DEMO_ACCOUNTS", "1")
    monkeypatch.setenv("DEMO_PASSWORD", "demo-pass-123")
    first = demo_accounts.ensure()
    assert set(first["created"]) == {"demo@alfa.test", "demo-ceo@alfa.test", "operator@alfa.test", "manager@alfa.test"}
    assert demo_accounts.ensure()["created"] == [], "повторный старт ничего не создает заново"

    cfo, ceo = new_client(), new_client()
    assert cfo.post(f"{API}/auth/login", json={"email": "demo@alfa.test", "password": "demo-pass-123"}).status_code == 200
    assert ceo.post(f"{API}/auth/login", json={"email": "demo-ceo@alfa.test", "password": "demo-pass-123"}).status_code == 200
    me_cfo, me_ceo = cfo.get(f"{API}/auth/me").json(), ceo.get(f"{API}/auth/me").json()
    company_id = first["company_id"]
    assert me_cfo["memberships"][0]["company_id"] == company_id and me_cfo["memberships"][0]["role"] == "cfo"
    assert me_ceo["memberships"][0]["company_id"] == company_id and me_ceo["memberships"][0]["role"] == "ceo"
    assert cfo.get(f"{API}/feed", params={"company_id": company_id}).status_code == 200
    members = store.list_members(company_id)
    assert len(members) == 2, "демо-учетки не дублируют участников"
    mgr = new_client()
    assert mgr.post(f"{API}/auth/login", json={"email": "manager@alfa.test", "password": "demo-pass-123"}).status_code == 200
    assert mgr.get(f"{API}/auth/me").json()["is_manager"] is True
    assert [c["company_id"] for c in mgr.get(f"{API}/manager/clients").json()["clients"]] == [company_id]


def test_claimed_company_is_not_taken_over(raw_client, new_client, monkeypatch):
    """Компанию уже зарегистрировал настоящий пользователь — демо-записи ее не трогают и берут следующую."""
    monkeypatch.setenv("DEMO_ACCOUNTS", "1")
    first, second = [c["company_id"] for c in demo_accounts.candidates()[:2]]
    owner = new_client()
    owner.post(f"{API}/auth/register", json={"name": "Владелец", "email": "real@example.com", "password": "correct-horse"})
    assert owner.post(f"{API}/companies/{first}/claim", json={"role": "owner"}).status_code == 201
    assert demo_accounts.ensure()["company_id"] == second
    assert [m["email"] for m in store.list_members(first)] == ["real@example.com"]
    assert {m["email"] for m in store.list_members(second)} == {"demo@alfa.test", "demo-ceo@alfa.test"}


def test_production_compose_has_no_demo_accounts():
    if not (ROOT / "docker-compose.yml").exists():
        pytest.skip("в тестовом образе (make test) нет compose-файлов; проверка идет в CI по репозиторию")
    assert "DEMO_ACCOUNTS" in (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "DEMO_" not in (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
