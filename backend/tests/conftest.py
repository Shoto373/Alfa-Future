"""Общая изоляция тестов: синтетические данные кейса и временный RUNTIME_DIR."""

from pathlib import Path
import os
import uuid

import pytest
from sqlalchemy.schema import DropSchema

from app.companies import profiles
from app.news import store

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path_factory, monkeypatch):
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn and os.environ.get("PGHOST"):
        from app.config import database_url
        dsn = database_url()
    if not dsn:
        pytest.fail("Set TEST_DATABASE_URL to a dedicated local PostgreSQL instance; tests create isolated schemas.")
    schema = "test_" + uuid.uuid4().hex
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    runtime = tmp_path_factory.mktemp("runtime")
    monkeypatch.setenv("RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("DATA_DIR", str(REPO / "data" / "synthetic"))
    monkeypatch.delenv("PROFILES_PATH", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("RSS_SOURCES", "")
    # Тесты не скачивают модель: смысловой слой проверяется подменой embeddings.embed.
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "0")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:3000")
    profiles.reset_cache()
    store.reset_cache()
    yield runtime
    profiles.reset_cache()
    store.reset_cache()
    from app.knowledge import kb
    from app import database, embeddings
    from app.news import semantic
    kb._index.cache_clear()
    kb._thesis_vectors.cache_clear()
    semantic._prototypes.cache_clear()
    embeddings.reset()
    database._ready.discard((dsn, schema))
    # Only the randomly generated test schema is removed, never public or a database.
    assert schema.startswith("test_") and len(schema) == 37
    engine = database.engine()
    with engine.begin() as conn:
        conn.execute(DropSchema(schema, cascade=True, if_exists=True))
    engine.dispose()


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
