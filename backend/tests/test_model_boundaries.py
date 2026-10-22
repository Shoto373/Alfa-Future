import asyncio

import pytest

from app.agent import llm, orchestrator
from app.news import store


def test_model_cannot_change_event_topic_to_fetch_unrelated_products(client, company, monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    def response(system, user, kind="compose", max_tokens=0):
        if kind == "plan":
            steps = [{"tool": name, "args": args, "why": "test"} for name, args in [
                ("get_exposures", {"company_id": company["company_id"], "topics": ["key_rate"]}),
                ("search_bank_analytics", {"query": "ключевая ставка", "topics": ["key_rate"], "sectors": []}),
                ("get_bank_products", {"company_id": company["company_id"], "topics": ["key_rate"]}),
                ("check_forecast_conflicts", {"topics": ["key_rate"]}),
            ]]
            return {"steps": steps}, {"model": "deepseek-v4.1-flash", "tokens": 1, "duration_ms": 1}
        return {}, {"model": "glm-5.3-flash", "tokens": 1, "duration_ms": 1}
    monkeypatch.setattr(llm, "chat_json", response)
    news = store.make_item("Обновлен стандарт кибербезопасности", "Опубликован стандарт проверки защищенности программ и резервных учетных записей.", "Проверка")
    result = asyncio.run(orchestrator.run(company, "cfo", news, "req_topic_boundary"))
    assert not result["bank_view"]["available"]
    assert result["bank_view"]["conflicts"] == [] and result["products"] == []


@pytest.mark.parametrize("malformed", ["plan", "draft"])
def test_malformed_model_structure_does_not_break_analysis(client, company, monkeypatch, malformed):
    monkeypatch.setattr(llm, "available", lambda: True)
    def response(system, user, kind="compose", max_tokens=0):
        if kind == "plan":
            if malformed == "plan":
                return {"steps": None}, {"model": "deepseek-v4.1-flash"}
            raise llm.LLMError("rules plan")
        data = {"risks": 42, "opportunities": [{"text": "Некорректный ответ", "source_ids": None, "features": None}], "questions": 42}
        return data, {"model": "glm-5.3-flash", "tokens": 1, "duration_ms": 1}
    monkeypatch.setattr(llm, "chat_json", response)
    result = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_malformed"))
    assert result["quality"]["passed"] and result["what_happened"]["facts"]


def test_malformed_followup_uses_rules(client, company, monkeypatch):
    from app.agent import qa
    insight = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_question"))
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda *a: ({"claims": None}, {}))
    result = qa.answer(insight, company, "Покажи источники")
    assert result["mode"] == "rules" and result["claims"]
