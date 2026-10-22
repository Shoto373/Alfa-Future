import asyncio
import json

import pytest

from app.agent import orchestrator
from app.api.setup import MAX_BODY_BYTES
from app.errors import AnalysisUnavailable

ORIGIN = "http://localhost:3000"


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    err = response.json()["error"]
    assert err["code"] == code
    assert err["request_id"].startswith("req_")
    assert err["retryable"] is (status in (503, 504))


def test_healthz_and_meta(client):
    assert client.get("/healthz").json() == {"status": "ok", "service": "backend"}
    meta = client.get("/api/v1/meta").json()
    assert meta["data"]["profiles"] > 0
    assert meta["knowledge"]["documents"] == 9
    assert meta["llm"]["connected"] is False
    assert {r["role"] for r in meta["roles"]} == {"owner", "ceo", "cfo", "accountant", "treasurer", "clevel"}


def test_companies_search_and_profile(client, company):
    body = client.get("/api/v1/companies", params={"limit": 5}).json()
    assert body["total"] > 0 and len(body["items"]) <= 5
    found = client.get("/api/v1/companies", params={"q": company["company_id"]}).json()
    assert found["items"][0]["company_id"] == company["company_id"]
    detail = client.get(f"/api/v1/companies/{company['company_id']}").json()
    assert detail["profile"]["company_id"] == company["company_id"] and detail["exposures"]
    assert body["total"] == 1 and body["items"][0]["company_id"] == company["company_id"]
    # Несуществующая и чужая компании неразличимы.
    assert_error(client.get("/api/v1/companies/U_nope"), 403, "FORBIDDEN")


def test_feed_is_personalized(client):
    from app.companies import profiles
    data = profiles._load()["companies"]
    a = next(c for c in data if c["products"]["loans"])
    b = next(c for c in data if c["sector"] != a["sector"] and not c["products"]["loans"])
    client.post(f"/api/v1/companies/{a['company_id']}/claim", json={"role": "cfo"})
    client.post(f"/api/v1/companies/{b['company_id']}/claim", json={"role": "ceo"})
    fa = client.get("/api/v1/feed", params={"company_id": a["company_id"]}).json()["items"]
    fb = client.get("/api/v1/feed", params={"company_id": b["company_id"]}).json()["items"]
    assert fa and fb
    assert fa[0]["relevance"]["reasons"]
    assert [i["news"]["news_id"] for i in fa[:5]] != [i["news"]["news_id"] for i in fb[:5]] or \
        [i["relevance"]["score"] for i in fa[:5]] != [i["relevance"]["score"] for i in fb[:5]]
    scores = [i["relevance"]["score"] for i in fa]
    assert scores == sorted(scores, reverse=True)


def test_insight_flow_with_cache_question_feedback_metrics(client, company):
    req = {"company_id": company["company_id"], "news_id": "seed-rate-hold"}
    first = client.post("/api/v1/insights", json=req)
    assert first.status_code == 200, first.text
    ins = first.json()
    assert ins["schema_version"] == "1.0.0" and ins["request_id"].startswith("req_")
    again = client.post("/api/v1/insights", json=req).json()
    assert again["insight_id"] == ins["insight_id"]
    fresh = client.post("/api/v1/insights", json=req | {"force_refresh": True}).json()
    assert fresh["insight_id"] != ins["insight_id"]

    assert client.get(f"/api/v1/insights/{ins['insight_id']}").json()["insight_id"] == ins["insight_id"]
    ans = client.post(f"/api/v1/insights/{ins['insight_id']}/questions", json={"question": "Какие источники?"}).json()
    assert ans["sources"]
    assert client.post("/api/v1/feedback", json={"insight_id": ins["insight_id"], "rating": 1, "section": "risks"}).json() == {"status": "ok"}
    m = client.get("/api/v1/metrics").json()
    assert m["content"]["insights"] >= 1 and m["personalization"]["feedback"]["up"] == 1
    audit = client.get("/api/v1/audit").json()["items"]
    assert any(a["tool"] == "search_bank_analytics" for a in audit)


def test_insight_errors(client, company, monkeypatch):
    base = {"company_id": company["company_id"], "news_id": "seed-rate-hold"}
    assert_error(client.post("/api/v1/insights", json=base | {"news_id": "nope"}), 404, "NEWS_NOT_FOUND")
    assert_error(client.post("/api/v1/insights", json=base | {"company_id": "nope"}), 403, "FORBIDDEN")
    assert_error(client.post("/api/v1/insights", json=base | {"role": "cfo"}), 400, "INVALID_REQUEST")
    assert_error(client.post("/api/v1/insights", json=base | {"extra": 1}), 400, "INVALID_REQUEST")
    assert_error(client.post("/api/v1/insights", content=b"{bad", headers={"Content-Type": "application/json"}), 400, "INVALID_REQUEST")
    body = json.dumps(base | {"pad": "x" * MAX_BODY_BYTES}).encode()
    assert_error(client.post("/api/v1/insights", content=body, headers={"Content-Type": "application/json"}), 413, "REQUEST_TOO_LARGE")

    async def unavailable(*a):
        raise AnalysisUnavailable()

    monkeypatch.setattr(orchestrator, "run", unavailable)
    assert_error(client.post("/api/v1/insights", json=base | {"force_refresh": True}), 503, "ANALYSIS_UNAVAILABLE")

    async def slow(*a):
        await asyncio.sleep(5)

    monkeypatch.setenv("ANALYSIS_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setattr(orchestrator, "run", slow)
    assert_error(client.post("/api/v1/insights", json=base | {"force_refresh": True}), 504, "ANALYSIS_TIMEOUT")

    async def wrong(company, role, news, request_id):
        return {"company_id": "other", "news_id": news["news_id"], "role": role, "request_id": request_id}

    monkeypatch.setattr(orchestrator, "run", wrong)
    assert_error(client.post("/api/v1/insights", json=base | {"force_refresh": True}), 500, "INVALID_ANALYSIS_RESULT")

    async def boom(*a):
        raise RuntimeError("secret")

    monkeypatch.setattr(orchestrator, "run", boom)
    r = client.post("/api/v1/insights", json=base | {"force_refresh": True})
    assert_error(r, 500, "INTERNAL_ERROR")
    assert "secret" not in r.text


def test_add_news_text_and_validation(client):
    r = client.post("/api/v1/news", json={"text": "Минфин объявил о росте НДС с 1 января 2027 года, что повлияет на цены и бюджет компаний."})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] and body["news"]["topics"]
    dup = client.post("/api/v1/news", json={"text": "Минфин объявил о росте НДС с 1 января 2027 года, что повлияет на цены и бюджет компаний."}).json()
    assert dup["created"] is False
    assert_error(client.post("/api/v1/news", json={"text": "коротко"}), 400, "INVALID_REQUEST")
    assert_error(client.post("/api/v1/news", json={"url": "http://127.0.0.1/secret"}), 422, "FETCH_FAILED")


def test_analytics_and_pdf(client, tmp_path, monkeypatch):
    docs = client.get("/api/v1/analytics").json()["documents"]
    assert len(docs) == 9 and all(d["theses"] for d in docs)
    assert_error(client.get("/api/v1/analytics/rate_2026_09_11/pdf"), 404, "DOCUMENT_NOT_FOUND")
    (tmp_path / "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setenv("BANK_PDF_DIR", str(tmp_path))
    r = client.get("/api/v1/analytics/rate_2026_09_11/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")


def test_openapi_uses_400_instead_of_422(client):
    spec = client.get("/openapi.json").json()
    for ops in spec["paths"].values():
        for op in ops.values():
            assert "422" not in op["responses"] or op["responses"]["422"]["description"].endswith("(FETCH_FAILED)")
    assert "HTTPValidationError" not in spec.get("components", {}).get("schemas", {})
    assert "role" not in {p["name"] for p in spec["paths"]["/api/v1/feed"]["get"]["parameters"]}
    assert "role" not in spec["components"]["schemas"]["InsightRequest"]["properties"]


def test_cors(client):
    for origin in (ORIGIN, "http://127.0.0.1:3000"):
        ok = client.options("/api/v1/feed", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == origin
        assert ok.headers["access-control-allow-credentials"] == "true"
        response = client.get("/api/v1/meta", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
    patch = client.options("/api/v1/companies/x/members/y", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "PATCH"})
    assert "PATCH" in patch.headers["access-control-allow-methods"] and "DELETE" in patch.headers["access-control-allow-methods"]
    for origin in ("http://evil.example", "http://127.0.0.1:3001", "http://localhost.evil.example:3000"):
        denied = client.options("/api/v1/feed", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers
        assert "access-control-allow-origin" not in client.get("/api/v1/meta", headers={"Origin": origin}).headers


@pytest.mark.parametrize("configured,expected", [
    ("http://localhost:3100", ["http://localhost:3100", "http://127.0.0.1:3100"]),
    ("http://127.0.0.1:3100/", ["http://127.0.0.1:3100", "http://localhost:3100"]),
    ("https://example.com", ["https://example.com"]),
])
def test_cors_origin_configuration(monkeypatch, configured, expected):
    from app import config
    monkeypatch.setenv("FRONTEND_ORIGIN", configured)
    assert config.frontend_origins() == expected


@pytest.mark.parametrize("path", ["/api/v1/insights/..%2F..%2Fetc", "/api/v1/insights/ins-zzz"])
def test_insight_lookup_is_safe(client, path):
    assert client.get(path).status_code in (404,)
