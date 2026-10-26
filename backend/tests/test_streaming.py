"""Потоковый разбор (SPR4-03): события SSE, проверенные разделы сразу, версия модели — заменой разделов."""

import json
import time

from app import llm
from app.agent import stages
from app.schemas import Insight
from tests.test_characterization import recorded_model

STREAM = "/api/v1/insights/stream"


def _events(client, **params) -> tuple[list[tuple[str, dict]], float]:
    """События потока и время до первого раздела, с."""
    started, first, out = time.perf_counter(), None, []
    with client.stream("GET", STREAM, params=params) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-accel-buffering"] == "no", "nginx не буферизует поток"
        name = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                if name == "section" and first is None:
                    first = time.perf_counter() - started
                out.append((name, json.loads(line[6:])))
    return out, first


def _news_id(client, company) -> str:
    return client.get("/api/v1/feed", params={"company_id": company["company_id"]}).json()["items"][0]["news"]["news_id"]


def test_rules_stream_sections_then_done(client, company):
    events, first = _events(client, company_id=company["company_id"], news_id=_news_id(client, company))
    names = [n for n, _ in events]
    assert names[0] == "section" and first < 3, "первый раздел — за доли секунды"
    assert {d["name"] for n, d in events if n == "section"} >= {"what_happened", "risks", "actions", "bank_view"}
    assert names[-1] == "done" and "insight" in names and "sources" in names
    done = events[-1][1]
    Insight.model_validate(done)  # итог — валидный разбор контракта
    assert done["mode"] == "rules"


def test_llm_stream_replaces_sections_after_checks(client, company, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", recorded_model)
    events, _ = _events(client, company_id=company["company_id"], news_id=_news_id(client, company))
    names = [n for n, _ in events]
    assert names.index("insight") < names.index("stage"), "сначала проверенный разбор правил, потом ход модели"
    stages_seen = {d["stage"] for n, d in events if n == "stage"}
    assert {"plan", "tool", "compose", "check"} <= stages_seen
    done = events[-1][1]
    Insight.model_validate(done)
    # В поток не попадает непроверенный текст: каждый раздел — из разборов, прошедших проверки (правила или итог).
    checked = [d for n, d in events if n == "insight"] + [done]
    for n, d in events:
        if n in ("section", "section_replaced"):
            assert any(ins.get(d["name"]) == d["value"] for ins in checked), f"раздел {d['name']} не из проверенного разбора"
    if done["mode"] == "llm":
        assert "section_replaced" in names and "review" in names


def test_stream_is_cached_and_access_checked(client, company, new_client):
    news_id = _news_id(client, company)
    _events(client, company_id=company["company_id"], news_id=news_id)
    again, _ = _events(client, company_id=company["company_id"], news_id=news_id)
    assert [n for n, _ in again][-1] == "done" and "stage" not in {n for n, _ in again}, "готовый разбор — без повторной работы"
    outsider = new_client()
    outsider.post("/api/v1/auth/register", json={"name": "Чужой", "email": "spy@example.com", "password": "correct-horse"})
    assert outsider.get(STREAM, params={"company_id": company["company_id"], "news_id": news_id}).status_code == 403


def test_tools_run_in_parallel_but_trace_keeps_plan_order(monkeypatch):
    calls = []

    class Runner:
        def call(self, tool, **args):
            calls.append(tool)
            time.sleep(0.05)
            return [], 50.0

    class Run:
        runner = Runner()
        ctx = {"news": {"classification": {"topics": []}}, "theses": [], "story": []}
        trace = stages.Trace()

    steps = [{"tool": t, "args": {}, "why": t} for t in ("get_exposures", "get_story_history", "get_bank_products")]
    started = time.perf_counter()
    stages._run_steps(Run(), steps)
    assert time.perf_counter() - started < 0.13, "три инструмента по 50 мс — параллельно"
    assert [s["name"] for s in Run.trace.steps] == ["get_exposures", "get_story_history", "get_bank_products"]


def test_llm_stream_emits_real_progress_milestones(client, company, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", recorded_model)
    events, _ = _events(client, company_id=company["company_id"], news_id=_news_id(client, company))
    names = [n for n, _ in events]
    marks = [d for n, d in events if n == "progress"]
    assert names.index("insight") < names.index("progress") < names.index("done"), "вехи — после разбора правил, до итога"
    assert {m["total"] for m in marks} == {len(stages.PHASES)}
    assert all(set(m) <= {"stage", "index", "total", "state", "label", "step"} for m in marks), "в событии нет данных компании"
    # Номер этапа не убывает; у каждого начатого этапа есть завершение, collect — первый, finalize — последний.
    assert [m["index"] for m in marks] == sorted(m["index"] for m in marks)
    started = [m["stage"] for m in marks if m["state"] == "start" and not m.get("step")]
    finished = [m["stage"] for m in marks if m["state"] == "done"]
    assert started[0] == "collect" and finished[-1] == "finalize" and set(started) == set(finished)
    assert {"collect", "draft", "check", "finalize"} <= set(finished)


def test_progress_milestones_are_silent_without_listener():
    assert stages.milestone.get() is None
    stages.mark("collect", "start")  # без подписчика (обычный POST /insights) — ничего не происходит
    got = []
    token = stages.milestone.set(got.append)
    try:
        stages.mark("check", "start", "fix")
    finally:
        stages.milestone.reset(token)
    assert got == [{"stage": "check", "index": 3, "total": 5, "state": "start", "label": "Проверяем факты и источники", "step": "fix"}]
