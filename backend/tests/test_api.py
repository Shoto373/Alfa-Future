import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analysis import service as analysis_service
from app.api.router import router
from app.api.setup import MAX_BODY_BYTES, configure_api
from app.errors import AnalysisUnavailable, InvalidAnalysisResult

VALID = {"company_id": "demo_company_001", "role": "cfo", "event_id": "demo_event_001"}
ORIGIN = "http://localhost:3000"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FIXTURES_DIR", raising=False)
    monkeypatch.setenv("FRONTEND_ORIGIN", ORIGIN)
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SECONDS", "0.2")
    app = FastAPI()
    configure_api(app)
    app.include_router(router)
    return TestClient(app)


def patch_analysis(monkeypatch, fn):
    monkeypatch.setattr(analysis_service, "generate_insight", fn)


def assert_error(response, status, code, retryable=False):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["retryable"] is retryable
    assert error["request_id"].startswith("req_")
    assert error["message"]


def test_list_companies(client):
    response = client.get("/api/v1/companies")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["company_id"] for i in items] == ["demo_company_001", "demo_company_002"]


def test_insight_uses_real_module_and_preserves_context(client):
    response = client.post("/api/v1/insights", json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert (body["company_id"], body["event_id"], body["role"]) == (
        VALID["company_id"], VALID["event_id"], VALID["role"])
    assert body["request_id"].startswith("req_")
    assert body["is_mock"] is True and body["bank_position"] is None


def test_insight_passes_correct_profile(client, monkeypatch):
    seen = {}
    real = analysis_service.generate_insight

    async def spy(company, role, event, request_id):
        seen.update(company=company, role=role, event=event)
        return await real(company, role, event, request_id)

    patch_analysis(monkeypatch, spy)
    response = client.post("/api/v1/insights", json={**VALID, "company_id": "demo_company_002", "role": "ceo"})
    assert response.status_code == 200
    assert seen["company"].company_id == "demo_company_002"
    assert seen["company"].has_deposit is True
    assert seen["role"] == "ceo"
    assert seen["event"].event_id == "demo_event_001"


@pytest.mark.parametrize(
    "payload",
    [
        {**VALID, "role": "cto"},
        {**VALID, "extra": True},
        {"company_id": "demo_company_001", "role": "cfo"},
        {**VALID, "company_id": ""},
        [],
    ],
    ids=["wrong-role", "extra-field", "missing-field", "empty-id", "not-object"],
)
def test_invalid_request_returns_400(client, payload):
    assert_error(client.post("/api/v1/insights", json=payload), 400, "INVALID_REQUEST")


def test_malformed_json_returns_400(client):
    response = client.post("/api/v1/insights", content=b"{oops", headers={"Content-Type": "application/json"})
    assert_error(response, 400, "INVALID_REQUEST")


def test_unknown_company_and_event_return_404(client):
    assert_error(client.post("/api/v1/insights", json={**VALID, "company_id": "nope"}), 404, "COMPANY_NOT_FOUND")
    assert_error(client.post("/api/v1/insights", json={**VALID, "event_id": "nope"}), 404, "EVENT_NOT_FOUND")


def test_body_too_large_returns_413(client):
    body = json.dumps({**VALID, "pad": "x" * MAX_BODY_BYTES}).encode()
    assert_error(client.post("/api/v1/insights", content=body, headers={"Content-Type": "application/json"}),
                 413, "REQUEST_TOO_LARGE")


def test_streamed_body_too_large_returns_413(client):
    def chunks():
        yield b'{"pad": "'
        for _ in range(MAX_BODY_BYTES // 1024 + 1):
            yield b"x" * 1024
        yield b'"}'

    response = client.post("/api/v1/insights", content=chunks(), headers={"Content-Type": "application/json"})
    assert_error(response, 413, "REQUEST_TOO_LARGE")


def test_analysis_unavailable_returns_503(client, monkeypatch):
    async def fail(*args):
        raise AnalysisUnavailable()

    patch_analysis(monkeypatch, fail)
    assert_error(client.post("/api/v1/insights", json=VALID), 503, "ANALYSIS_UNAVAILABLE", retryable=True)


def test_analysis_timeout_returns_504(client, monkeypatch):
    async def slow(*args):
        await asyncio.sleep(5)

    patch_analysis(monkeypatch, slow)
    assert_error(client.post("/api/v1/insights", json=VALID), 504, "ANALYSIS_TIMEOUT", retryable=True)


def test_unexpected_exception_returns_500(client, monkeypatch):
    async def boom(*args):
        raise RuntimeError("secret detail")

    patch_analysis(monkeypatch, boom)
    response = client.post("/api/v1/insights", json=VALID)
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret" not in response.text


def test_invalid_analysis_exception_returns_500(client, monkeypatch):
    async def bad(*args):
        raise InvalidAnalysisResult()

    patch_analysis(monkeypatch, bad)
    assert_error(client.post("/api/v1/insights", json=VALID), 500, "INVALID_ANALYSIS_RESULT")


def test_invalid_card_returns_500(client, monkeypatch):
    async def broken(*args):
        return {"title": "no other fields"}

    patch_analysis(monkeypatch, broken)
    assert_error(client.post("/api/v1/insights", json=VALID), 500, "INVALID_ANALYSIS_RESULT")


@pytest.mark.parametrize("field,value", [
    ("company_id", "demo_company_002"),
    ("event_id", "other_event"),
    ("role", "ceo"),
    ("request_id", "req_other"),
])
def test_context_mismatch_returns_500(client, monkeypatch, field, value):
    real = analysis_service.generate_insight

    async def wrong(company, role, event, request_id):
        insight = await real(company, role, event, request_id)
        return insight.model_copy(update={field: value})

    patch_analysis(monkeypatch, wrong)
    assert_error(client.post("/api/v1/insights", json=VALID), 500, "INVALID_ANALYSIS_RESULT")


def test_corrupted_fixtures_return_500(client, monkeypatch, tmp_path):
    (tmp_path / "companies.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("FIXTURES_DIR", str(tmp_path))
    response = client.get("/api/v1/companies")
    assert_error(response, 500, "INTERNAL_ERROR")
    assert "broken" not in response.text
    assert_error(client.post("/api/v1/insights", json=VALID), 500, "INTERNAL_ERROR")


def test_cors_allows_only_frontend_origin(client):
    ok = client.options("/api/v1/insights", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN

    denied = client.get("/api/v1/companies", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in denied.headers

    error = client.post("/api/v1/insights", json={**VALID, "company_id": "nope"}, headers={"Origin": ORIGIN})
    assert error.headers["access-control-allow-origin"] == ORIGIN


def test_logs_do_not_contain_profile_data(client, caplog):
    caplog.set_level("INFO", logger="app.api")
    client.post("/api/v1/insights", json=VALID)
    text = caplog.text
    assert "request_id=req_" in text and "status=200" in text
    assert "Северная" not in text and "demo_company_001" not in text
