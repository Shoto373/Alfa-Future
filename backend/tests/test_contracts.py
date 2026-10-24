"""Контракт API 1.x, формат разбора 1.0.0 (SPR3-00): файл контракта совпадает со схемами, закрепленные примеры 1.0.0 валидны
для текущих схем (обратная совместимость), каждый ответ несет X-API-Version, каталог ошибок полон."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.api.errors import MESSAGES
from app.auth.schemas import User
from app.errors import STATUS
from app.schemas import API_VERSION, SCHEMA_VERSION, Answer, ErrorResponse, Insight

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
EXAMPLES = {"Insight": Insight, "Answer": Answer, "ErrorResponse": ErrorResponse, "User": User}

needs_repo = pytest.mark.skipif(not CONTRACTS.exists(), reason="в тестовом образе (make test) нет contracts/; проверка идет в CI")


def _gen_contracts():
    spec = importlib.util.spec_from_file_location("gen_contracts", Path(__file__).resolve().parents[1] / "tools" / "gen_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_version_is_1_0_0():
    assert SCHEMA_VERSION == "1.0.0", "формат разбора не менялся"
    assert API_VERSION == "1.2.0", "адреса добавлены аддитивно — минорная версия контракта"


@needs_repo
def test_openapi_file_matches_schemas():
    assert (CONTRACTS / "openapi.json").read_text(encoding="utf-8") == _gen_contracts().render(), \
        "contracts/openapi.json устарел: cd backend && python tools/gen_contracts.py"


@needs_repo
@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_1_0_0_stay_valid(name):
    """Пример 1.0.0 должен проходить текущую схему: удаление поля или новое обязательное поле его ломают."""
    example = json.loads((CONTRACTS / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    EXAMPLES[name].model_validate(example)


def test_every_response_has_api_version(raw_client):
    for path in ("/api/v1/meta", "/api/v1/auth/me", "/healthz"):
        assert raw_client.get(path).headers["x-api-version"] == API_VERSION


@needs_repo
def test_error_catalog_lists_every_code():
    doc = (ROOT / "docs" / "api-versioning.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| `([A-Z_]+)` \| (\d{3}) \|", doc, re.M))
    assert rows == {code: str(status) for code, status in STATUS.items()}, "каталог ошибок в docs/api-versioning.md устарел"
    assert set(MESSAGES) == set(STATUS)
