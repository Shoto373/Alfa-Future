"""Характеризационные снимки: переработка кода (SPR2-01) не меняет разборы ни на байт.

Шесть сценариев — 2 компании (металлург и автодилер) × 3 роли, режим правил, четыре новости демо-ленты.
Разбор нормализуется: без идентификаторов, времени и длительностей. Снимки — в fixtures/characterization.

Обновить снимки (только при намеренном изменении разборов, с просмотром diff):
    UPDATE_CHARACTERIZATION=1 python -m pytest tests/test_characterization.py
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import ranking
from app.agent import orchestrator
from app.companies import profiles
from app.news import store

SNAPSHOTS = Path(__file__).with_name("fixtures") / "characterization"
SECTORS = ("metallurgy", "auto")
ROLES = ("cfo", "ceo", "owner")
NEWS = ("seed-rate-hold", "seed-inflation-week", "seed-fuel-prices", "seed-autoloan-limits")
VOLATILE = {"insight_id", "request_id", "created_at", "duration_ms", "total_duration_ms", "ts"}
TIMING = re.compile(r"\d+(?:[.,]\d+)? мс")
FIXED_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        return TIMING.sub("N мс", value)  # замер времени в описании шага трассы
    return value


def company_of(sector: str) -> dict:
    companies = [c for c in profiles._load()["companies"] if c["sector"] == sector]
    return max(companies, key=lambda c: c.get("revenue") or 0)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("sector", SECTORS)
def test_insights_match_snapshot(raw_client, monkeypatch, sector, role):
    monkeypatch.setattr(ranking, "NOW_OVERRIDE", FIXED_NOW)
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
