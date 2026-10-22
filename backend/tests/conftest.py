"""Общая изоляция тестов: синтетические данные кейса и временный RUNTIME_DIR."""

from pathlib import Path

import pytest

from app.companies import profiles
from app.news import store

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path_factory, monkeypatch):
    runtime = tmp_path_factory.mktemp("runtime")
    monkeypatch.setenv("RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("DATA_DIR", str(REPO / "data" / "synthetic"))
    monkeypatch.delenv("PROFILES_PATH", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("RSS_SOURCES", "")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    profiles.reset_cache()
    store.reset_cache()
    yield runtime
    profiles.reset_cache()
    store.reset_cache()


@pytest.fixture(scope="session")
def shared_profiles(tmp_path_factory):
    """Профили строятся один раз за сессию и переиспользуются тестами через PROFILES_PATH."""
    from app.companies import etl
    import json

    path = tmp_path_factory.mktemp("profiles") / "companies.json"
    path.write_text(json.dumps(etl.build_profiles(REPO / "data" / "synthetic"), ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def raw_client(shared_profiles, monkeypatch):
    """Клиент без входа в систему."""
    from fastapi.testclient import TestClient

    from app.auth import security
    from app.main import app

    monkeypatch.setenv("PROFILES_PATH", str(shared_profiles))
    profiles.reset_cache()
    security.limiter.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def new_client(raw_client):
    """Фабрика клиентов с отдельными cookie (разные пользователи одного приложения)."""
    from fastapi.testclient import TestClient

    from app.main import app

    return lambda: TestClient(app)


@pytest.fixture
def company(raw_client):
    from app.companies import profiles as p

    data = p._load()["companies"]
    return next(c for c in data if c["products"]["loans"]) if any(c["products"]["loans"] for c in data) else data[0]


def register(c, email="owner@example.com", name="Иван", password="correct-horse"):
    r = c.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def client(raw_client, company):
    """Вошедший пользователь — администратор company (роль cfo)."""
    register(raw_client)
    r = raw_client.post(f"/api/v1/companies/{company['company_id']}/claim", json={"role": "cfo"})
    assert r.status_code == 201, r.text
    return raw_client
