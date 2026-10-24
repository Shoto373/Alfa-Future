"""Наблюдаемость (SPR3-05): /metrics в формате Prometheus, JSON-логи без персональных данных,
trace_id этапов агента в Insight.trace, приемник алертов."""

import json
import logging

from app import database, notify, observability
from app.news.sources import registry


def _metrics(c, **headers) -> str:
    r = c.get("/metrics", headers=headers)
    assert r.status_code == 200, r.text
    return r.text


def test_metrics_cover_http_llm_worker_and_backup(client, company):
    client.get("/api/v1/feed", params={"company_id": company["company_id"]})
    with database.session() as db:
        database.set_state("backup_last", {"at": "2026-10-24T03:00:00+00:00", "file": "alfa.dump"}, db)
    text = _metrics(client)
    assert 'alfa_http_requests_total{method="GET",route="/api/v1/feed",status="200"}' in text
    assert 'alfa_http_request_duration_seconds_bucket{route="/api/v1/feed",le="+Inf"}' in text
    for name in ("alfa_llm_budget_spent_ratio", "alfa_llm_cost_limit_rub", 'alfa_jobs{status="queued"}',
                 "alfa_worker_heartbeat_age_seconds", "alfa_cache_requests_total"):
        assert name in text, name
    assert "alfa_backup_last_success_timestamp_seconds 1792810800\n" in text, "время бэкапа — без округления"
    assert "/api/v1/feed?" not in text, "в метках — шаблон маршрута, без параметров"


def test_metrics_token(client, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert "alfa_" in _metrics(client, Authorization="Bearer s3cret")


def test_histogram_is_cumulative():
    h = observability.Histogram("t_seconds", "test", ("route",), buckets=(1, 5))
    for v in (0.5, 2, 2, 10):
        h.observe(v, "/x")
    lines = h.render()
    assert 't_seconds_bucket{route="/x",le="1"} 1' in lines
    assert 't_seconds_bucket{route="/x",le="5"} 3' in lines
    assert 't_seconds_bucket{route="/x",le="+Inf"} 4' in lines and 't_seconds_count{route="/x"} 4' in lines


def test_request_log_is_json_with_pseudonymous_user(client, company, caplog):
    caplog.set_level(logging.INFO, logger="app.api")
    client.get("/api/v1/feed", params={"company_id": company["company_id"]})
    record = next(r for r in caplog.records if r.getMessage() == "request" and getattr(r, "route", "") == "/api/v1/feed")
    line = json.loads(observability.JsonFormatter().format(record))
    assert line["status"] == 200 and line["company_id"] == company["company_id"] and line["duration_ms"] >= 0
    me = client.get("/api/v1/auth/me").json()
    assert line["user"] == observability.user_hash(me["user_id"]) and me["user_id"] not in json.dumps(line)
    assert line["request_id"].startswith("req_")


def test_insight_trace_carries_trace_id_and_stage_metrics(client, company):
    feed = client.get("/api/v1/feed", params={"company_id": company["company_id"]}).json()["items"]
    before = observability.INSIGHTS.value("rules", "disabled")
    ins = client.post("/api/v1/insights", json={"company_id": company["company_id"], "news_id": feed[0]["news"]["news_id"],
                                                 "fast": True, "force_refresh": True}).json()
    ids = {s["output"]["trace_id"] for s in ins["trace"]}
    assert len(ids) == 1 and len(ids.pop()) == 32, "один trace_id на все этапы разбора"
    assert observability.INSIGHTS.value("rules", ins.get("fallback_reason") or "none") >= 1 or before >= 0
    assert "alfa_agent_stage_duration_seconds_bucket" in _metrics(client)


def test_spans_are_exported_to_local_collector(monkeypatch):
    sent = []
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4318")
    monkeypatch.setattr(observability, "_ensure_exporter", lambda: None)
    insight = {"mode": "rules", "trace": [{"stage": "plan", "name": "план", "status": "ok", "duration_ms": 12.0}]}
    trace_id = observability.record_insight(insight, 1_000.0, "req_1")
    while not observability._spans.empty():
        sent.append(observability._spans.get_nowait())
    assert [s["name"] for s in sent] == ["insight", "plan: план"] and {s["traceId"] for s in sent} == {trace_id}
    assert sent[1]["parentSpanId"] == sent[0]["spanId"]


def test_alerts_are_forwarded_to_team_channel(client, monkeypatch):
    texts = []
    monkeypatch.setattr(notify, "send", lambda text: texts.append(text) or True)
    body = {"alerts": [{"status": "firing", "labels": {"alertname": "BackupOlderThan26h"},
                        "annotations": {"summary": "Последний успешный бэкап старше 26 часов"}}]}
    assert client.post("/internal/alerts", json=body).status_code == 403, "без токена — только из внутренней сети"
    monkeypatch.setenv("METRICS_TOKEN", "s3cret")
    r = client.post("/internal/alerts", json=body, headers={"Authorization": "Bearer s3cret"})
    assert r.json() == {"received": 1, "sent": 1}
    assert texts == ["🔴 BackupOlderThan26h: Последний успешный бэкап старше 26 часов"]


def test_metrics_have_no_duplicate_series(client, monkeypatch):
    """Повтор серии в одном ответе Prometheus отбрасывает весь сбор: у изданий бывает несколько лент с одним именем."""
    with database.session() as db:
        database.set_state(registry.STATS_KEY, {
            "rss:a": {"name": "Ведомости", "kind": "rss", "errors_total": 0, "last_ok": "2026-10-24T10:00:00+00:00"},
            "rss:b": {"name": "Ведомости", "kind": "rss", "errors_total": 1, "last_ok": "2026-10-24T10:00:00+00:00"}}, db)
    series = [line.rsplit(" ", 1)[0] for line in _metrics(client).splitlines() if line and not line.startswith("#")]
    assert len(series) == len(set(series)), [s for s in series if series.count(s) > 1]
