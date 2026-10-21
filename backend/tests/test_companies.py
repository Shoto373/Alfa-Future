import json

import pytest

from app.companies import repository


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURES_DIR", str(tmp_path))
    return tmp_path


def test_default_fixtures_contain_two_companies(monkeypatch):
    monkeypatch.delenv("FIXTURES_DIR", raising=False)
    companies = repository.load_companies()
    assert [c.company_id for c in companies] == ["demo_company_001", "demo_company_002"]
    assert repository.get_company("demo_company_002").has_deposit is True
    assert repository.get_event("demo_event_001").is_synthetic is True


def test_unknown_ids_return_none(monkeypatch):
    monkeypatch.delenv("FIXTURES_DIR", raising=False)
    assert repository.get_company("missing") is None
    assert repository.get_event("missing") is None


def test_missing_fixtures_raise(fixtures):
    with pytest.raises(repository.FixturesError):
        repository.load_companies()


@pytest.mark.parametrize(
    "content",
    ["{not json", json.dumps([]), json.dumps({"items": [{"company_id": "x"}]})],
    ids=["broken-json", "not-object", "invalid-profile"],
)
def test_corrupted_companies_raise(fixtures, content):
    (fixtures / "companies.json").write_text(content, encoding="utf-8")
    with pytest.raises(repository.FixturesError):
        repository.load_companies()


def test_duplicate_company_ids_raise(fixtures):
    item = {
        "company_id": "a", "display_name": "Демо", "industry_name": "x",
        "region": None, "has_credit": None, "has_deposit": None, "is_synthetic": True,
    }
    (fixtures / "companies.json").write_text(json.dumps({"items": [item, item]}), encoding="utf-8")
    with pytest.raises(repository.FixturesError):
        repository.load_companies()


def test_corrupted_event_raises(fixtures):
    (fixtures / "event.json").write_text(json.dumps({"event_id": "e"}), encoding="utf-8")
    with pytest.raises(repository.FixturesError):
        repository.load_events()
