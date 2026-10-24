"""Отрасли, темы и действия как данные (SPR4-00): валидатор, публикация без деплоя, превью и откат.

Эквивалентность YAML и прежних словарей в коде доказывают характеризационные тесты ленты и разборов
(tests/test_characterization.py) — они не менялись и проходят на конфигурации из YAML."""

import pytest
import yaml

from app import ranking
from app.companies import profiles
from app.domain_config import loader, runtime
from app.domain_config.validate import validate_texts
from app.news import store
from app.news.taxonomy import TOPICS
from app.worker import runner

API = "/api/v1/admin/config"


@pytest.fixture(autouse=True)
def restore_config():
    """Публикация в тесте меняет словари процесса — после теста возвращаем конфигурацию из репозитория."""
    yield
    loader.load_files()
    loader._checked.update(at=0.0, rev=None)


def _texts() -> dict[str, str]:
    return loader.file_texts()


def _edit(texts: dict, doc: str, change) -> dict:
    data = yaml.safe_load(texts[doc])
    change(data)
    return {**texts, doc: yaml.safe_dump(data, allow_unicode=True, sort_keys=False)}


def _errors(texts: dict) -> list[str]:
    return [f"{i.path}: {i.message}" for i in validate_texts(texts)[1] if i.level == "error"]


def test_repository_config_is_valid_and_active():
    assert _errors(_texts()) == []
    assert runtime.signature() and "key_rate" in TOPICS and TOPICS is runtime.TOPICS


def test_validator_catches_flipped_sector_sign():
    flipped = _edit(_texts(), "sectors", lambda d: d["sectors"]["construction"]["sensitivity"]["key_rate"].update(sign=1))
    errors = _errors(flipped)
    assert any("sectors.construction.sensitivity.key_rate" in e and "знак" in e for e in errors), errors


def test_validator_catches_flipped_direction_convention():
    flipped = _edit(_texts(), "topics", lambda d: d["topics"]["key_rate"]["direction_value"].update(up=-1, down=1))
    assert any("topics.key_rate.direction_value" in e for e in _errors(flipped))


@pytest.mark.parametrize("doc,change,expected", [
    ("topics", lambda d: d["topics"]["fx"]["actions"]["cfo"].append({"text": "Захеджировать 50% валютной выручки"}), "Число"),
    ("sectors", lambda d: d["sectors"]["retail"]["sensitivity"].update(no_such_topic={"sign": 1, "why": "проверка"}), "нет в topics"),
    ("sectors", lambda d: d["sectors"]["retail"]["okved"].append("41"), "уже у отрасли"),
    ("sectors", lambda d: d["sectors"]["retail"]["sensitivity"]["fx"].update(sign=2), "sign"),
    ("topics", lambda d: d["topics"]["fx"]["actions"].update(director=[{"text": "Неизвестная роль в действиях"}]), "роль"),
])
def test_validator_rejects_bad_config(doc, change, expected):
    assert any(expected in e for e in _errors(_edit(_texts(), doc, change)))


def test_yaml_syntax_error_is_reported_with_line():
    issues = validate_texts({**_texts(), "language": "countries: [\n  - broken"})[1]
    assert any(i.doc == "language" and "YAML" in i.message for i in issues)


def _agro_topics(texts: dict) -> dict:
    """Сценарий приемки: аналитик добавляет «погоду» и «экспортные пошлины на зерно» для сельского хозяйства."""
    def topics(d):
        d["topics"]["weather"] = {
            "name": "Погода и урожай", "importance": 0.8, "stems": ["засух", "заморозк", "неурожа", "ливн", "град"],
            "meanings": ["Засуха или заморозки погубили урожай"], "up_means": "погодные риски растут",
            "direction_value": {"up": 1, "hold": 0, "down": -1},
            "effect": {"risk": "погода снижает урожай и выручку", "opportunity": "хороший урожай поддерживает выручку"},
            "actions": {"default": [{"text": "Проверить страхование урожая и запас по контрактам на поставку зерна"}]},
            "question": "Застрахован ли урожай от погодных рисков?"}
        d["topics"]["grain_export_duties"] = {
            "name": "Экспортные пошлины на зерно", "importance": 0.8, "stems": ["пошлин на зерн", "экспортн пошлин на пшениц"],
            "meanings": ["Правительство изменило экспортную пошлину на пшеницу"], "up_means": "пошлины растут",
            "direction_value": {"up": 1, "hold": 0, "down": -1},
            "effect": {"risk": "экспортная выручка снижается на величину пошлины", "opportunity": "экспорт зерна становится выгоднее"},
            "actions": {"default": [{"text": "Пересчитать экономику экспортных контрактов с учетом пошлины"}]}}

    def sectors(d):
        d["topic_order"] += ["weather", "grain_export_duties"]
        d["sectors"]["agriculture_food"]["sensitivity"]["weather"] = {"sign": -1, "why": "засуха и заморозки снижают урожай"}
        d["sectors"]["agriculture_food"]["sensitivity"]["grain_export_duties"] = {"sign": -1, "why": "пошлина уменьшает экспортную выручку"}
        d["control_cases"].append({"topic": "weather", "sector": "agriculture_food", "direction": "up", "expect": "risk"})
    return _edit(_edit(texts, "topics", topics), "sectors", sectors)


def _agro_company() -> str:
    return next(c["company_id"] for c in profiles.list_companies(limit=10**6)[1] if c["sector"] == "agriculture_food")


def test_new_topics_change_agro_feed_without_deploy(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com")
    texts = _agro_topics(_texts())
    published = client.post(f"{API}/publish", json={**texts, "note": "Агросектор: погода и пошлины"})
    assert published.status_code == 200, published.text
    assert runner.Worker("cfg").run_one(), "переклассификация новостей — задача воркера"
    assert "weather" in TOPICS and runtime.version() == published.json()["id"]

    item = store.make_item("Засуха и заморозки привели к неурожаю зерна на юге России",
                           "Засуха и ранние заморозки привели к неурожаю зерна: аграрии юга потеряли до трети урожая пшеницы, "
                           "цены на зерно выросли.", "Тест")
    store.add(item)
    assert {t["topic"] for t in item["classification"]["topics"]} >= {"weather"}
    feed = ranking.feed(store.all_items(), _agro_company(), "cfo", None, 50)
    hit = next(r for r in feed if r["news"]["news_id"] == item["news_id"])
    assert any("засуха и заморозки снижают урожай" in r["text"].lower() for r in hit["relevance"]["reasons"]),         "причина — из новой чувствительности"

    versions = client.get(API).json()["versions"]
    assert versions[0]["status"] == "published" and versions[0]["note"] == "Агросектор: погода и пошлины"
    back = client.post(f"{API}/versions/{versions[0]['id']}/rollback")
    assert back.status_code == 200


def test_invalid_config_is_not_published(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com")
    flipped = _edit(_texts(), "sectors", lambda d: d["sectors"]["construction"]["sensitivity"]["key_rate"].update(sign=1))
    assert client.post(f"{API}/validate", json=flipped).json()["ok"] is False
    assert client.post(f"{API}/publish", json={**flipped, "note": "x"}).status_code == 400
    assert client.get(API).json()["versions"] == [], "невалидная версия не сохраняется"


def test_only_bank_staff(client):
    assert client.get(API).status_code == 403


def test_preview_shows_feed_change_without_publishing(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com")
    signature = runtime.signature()
    r = client.post(f"{API}/preview", json={**_agro_topics(_texts()), "company_id": _agro_company(), "role": "cfo"})
    assert r.status_code == 202
    assert runner.Worker("cfg").run_one()
    result = client.get(f"{API}/preview/{r.json()['id']}").json()
    assert result["status"] == "ready" and len(result["before"]) > 0 and "after" in result
    assert runtime.signature() == signature and "weather" not in TOPICS, "превью не меняет действующую конфигурацию"


def test_published_version_reaches_other_process():
    texts = _agro_topics(_texts())
    loader.publish(texts, "analyst@example.com", "из другого процесса")
    loader.load_files()  # «другой процесс»: еще на файлах и не видел новой ревизии
    loader._checked.update(at=0.0, rev=None)
    assert "weather" not in TOPICS
    assert loader.refresh() is True and "weather" in TOPICS, "версия из базы применяется без перезапуска"
