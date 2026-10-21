"""Чтение синтетических fixtures (companies.json, event.json) из FIXTURES_DIR.

Модуль не подменяет поврежденные данные пустым списком: любая ошибка
чтения или валидации поднимает FixturesError, которую API превращает в 500.
"""

import json
import os
from pathlib import Path

from pydantic import ValidationError

from app.schemas import CompanyProfile, Event

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "contracts" / "examples"


class FixturesError(Exception):
    """Fixtures отсутствуют или не соответствуют контракту."""


def fixtures_dir() -> Path:
    value = os.environ.get("FIXTURES_DIR")
    return Path(value) if value else DEFAULT_FIXTURES_DIR


def _read_json(name: str) -> object:
    path = fixtures_dir() / name
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise FixturesError(f"Не удалось прочитать fixture {name}") from exc


def load_companies() -> list[CompanyProfile]:
    data = _read_json("companies.json")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise FixturesError("companies.json должен содержать объект с массивом items")
    try:
        companies = [CompanyProfile.model_validate(item) for item in data["items"]]
    except ValidationError as exc:
        raise FixturesError("companies.json не соответствует схеме CompanyProfile") from exc
    ids = [c.company_id for c in companies]
    if len(ids) != len(set(ids)):
        raise FixturesError("companies.json содержит повторяющиеся company_id")
    return companies


def load_events() -> list[Event]:
    data = _read_json("event.json")
    items = data if isinstance(data, list) else [data]
    try:
        return [Event.model_validate(item) for item in items]
    except ValidationError as exc:
        raise FixturesError("event.json не соответствует схеме Event") from exc


def get_company(company_id: str) -> CompanyProfile | None:
    return next((c for c in load_companies() if c.company_id == company_id), None)


def get_event(event_id: str) -> Event | None:
    return next((e for e in load_events() if e.event_id == event_id), None)
