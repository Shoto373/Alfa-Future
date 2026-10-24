"""Характеризационные снимки: переработка кода (SPR2-01) не меняет разборы ни на байт.

Режим правил — 2 компании (металлург и автодилер) × 3 роли × 4 новости демо-ленты.
Режим модели — 2 компании × 2 роли × 2 новости на записанных ответах модели (сеть не вызывается).
Разбор нормализуется: без идентификаторов, времени и длительностей. Снимки — в fixtures/characterization.

Обновить снимки (только при намеренном изменении разборов, с просмотром diff):
    UPDATE_CHARACTERIZATION=1 python -m pytest tests/test_characterization.py
"""

import asyncio
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app import llm, ranking
from app.agent import orchestrator, prompts, review
from app.companies import profiles
from app.knowledge import kb
from app.news import store

SNAPSHOTS = Path(__file__).with_name("fixtures") / "characterization"
SECTORS = ("metallurgy", "auto")
ROLES = ("cfo", "ceo", "owner")
NEWS = ("seed-rate-hold", "seed-inflation-week", "seed-fuel-prices", "seed-autoloan-limits")
VOLATILE = {"insight_id", "request_id", "created_at", "duration_ms", "total_duration_ms", "ts", "trace_id"}
TIMING = re.compile(r"\d+(?:[.,]\d+)? мс")
FIXED_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


class FrozenDate(date):
    """Свежесть тезисов банка (kb._recency) считается от «сегодня» — в снимках день зафиксирован."""

    @classmethod
    def today(cls):
        return cls(FIXED_NOW.year, FIXED_NOW.month, FIXED_NOW.day)


def freeze_clock(monkeypatch) -> None:
    """Снимок не должен зависеть от даты запуска: лента и порядок тезисов банка стареют со временем."""
    monkeypatch.setattr(ranking, "NOW_OVERRIDE", FIXED_NOW)
    monkeypatch.setattr(kb, "date", FrozenDate)


def normalize(value):
    if isinstance(value, dict):
        # output шага, где был только trace_id (наблюдаемость, SPR3-05), сравнивается как пустой — как до него.
        return {k: (None if k == "output" and v and set(v) == {"trace_id"} else normalize(v))
                for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        return TIMING.sub("N мс", value)  # замер времени в описании шага трассы
    return value


def company_of(sector: str) -> dict:
    companies = [c for c in profiles._load()["companies"] if c["sector"] == sector]
    return max(companies, key=lambda c: c.get("revenue") or 0)


def recorded_model(system: str, user: str, model_kind: str = "compose", max_tokens: int = 2000) -> tuple[dict, dict]:
    """Записанные ответы модели: детерминированы по входу и проходят весь путь агента с LLM —
    план, черновик с одним заведомо неверным выводом, его исправление и смысловую проверку."""
    payload = json.loads(user) if user.startswith("{") else {}
    meta = {"model": f"recorded/{model_kind}", "tokens": 100, "duration_ms": 1.0}
    if system == prompts.PLAN_SYSTEM:
        topics = payload["news"]["news_topics"][:1]
        return {"queries": [{"query": payload["news"]["title"], "why": "уточнить прогноз банка", "topics": topics}]}, meta
    if system == prompts.COMPOSE_SYSTEM:
        news_src = next(s["source_id"] for s in payload["sources"] if s["kind"] == "news")
        bank = [s["source_id"] for s in payload["sources"] if s["kind"] == "bank_analytics"][:1]
        feature = (payload["exposures"] or [{"feature": "sector"}])[0]["feature"]
        claim = lambda text, ids: {"text": text, "origin": "ai", "source_ids": ids, "features": [feature]}  # noqa: E731
        return {
            "why_important": [claim("Событие касается компании через ее профиль и операции.", [news_src, "client:profile"])],
            # Число не из источников — проверка его ловит, модель исправляет.
            "risks": [claim("Расходы компании могут вырасти на 99% из-за события.", [news_src, "client:profile"])],
            "opportunities": [claim("Компания может пересмотреть условия финансирования.", [news_src] + bank)],
            "actions": [claim("Обсудить с банком влияние события на план финансирования.", [news_src, "client:profile"])],
            "questions": ["Какая доля обязательств компании зависит от ставки?"],
        }, meta
    if system == prompts.REPAIR_SYSTEM:
        return {"claims": [{"id": c["id"], "text": "Расходы компании могут вырасти из-за события.", "origin": "ai",
                            "source_ids": c.get("source_ids") or [], "features": c.get("features") or []}
                           for c in payload["claims"]]}, meta
    if system == review.REVIEW_SYSTEM:  # критик снимает первый вывод AI, остальные подтверждает
        return {"verdicts": [{"i": c["i"], "verdict": "unsupported" if n == 0 else "supported", "reason": "нет опоры в источниках"}
                             for n, c in enumerate(payload["claims"])]}, meta
    raise AssertionError(f"неожиданный вызов модели: {model_kind}")


def check_snapshot(name: str, actual: list[dict]) -> None:
    path = SNAPSHOTS / f"{name}.json"
    text = json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_CHARACTERIZATION") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.exists(), f"нет снимка {path.name}: UPDATE_CHARACTERIZATION=1"
    assert text == path.read_text(encoding="utf-8"), f"разбор изменился: {path.name}"


@pytest.mark.parametrize("role", ("cfo", "owner"))
@pytest.mark.parametrize("sector", SECTORS)
def test_llm_insights_match_snapshot(raw_client, monkeypatch, sector, role):
    """Путь с моделью на записанных ответах: план → черновик модели → исправление → смысловая проверка или откат."""
    freeze_clock(monkeypatch)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", recorded_model)
    company = company_of(sector)
    actual = [normalize(asyncio.run(orchestrator.run(company, role, store.get(news_id), "req_characterization")))
              for news_id in NEWS[:2]]
    # Модель участвовала в каждом разборе; итог — ее версия или безопасный откат к правилам, если проверки не пройдены.
    assert all(any(s["name"] == "llm_compose" for s in ins["trace"]) for ins in actual)
    check_snapshot(f"llm-{sector}-{role}", actual)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("sector", SECTORS)
def test_insights_match_snapshot(raw_client, monkeypatch, sector, role):
    freeze_clock(monkeypatch)
    company = company_of(sector)
    actual = []
    for news_id in NEWS:
        insight = asyncio.run(orchestrator.run(company, role, store.get(news_id), "req_characterization", use_llm=False))
        actual.append(normalize(insight))
    path = SNAPSHOTS / f"{sector}-{role}.json"
    text = json.dumps(actual, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_CHARACTERIZATION") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.exists(), f"нет снимка {path.name}: UPDATE_CHARACTERIZATION=1"
    assert text == path.read_text(encoding="utf-8"), f"разбор изменился: {path.name}"
