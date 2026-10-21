import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from pydantic.json_schema import models_json_schema

from app.main import app
from app.schemas import CompanyProfile, ErrorResponse, Event, Insight, InsightRequest, Source

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "schemas" / "common.json").read_text(encoding="utf-8"))
MODELS = [CompanyProfile, Event, InsightRequest, Source, Insight, ErrorResponse]


def load_example(name: str):
    return json.loads((CONTRACTS / "examples" / name).read_text(encoding="utf-8"))


def validator(definition: str) -> Draft202012Validator:
    return Draft202012Validator({**SCHEMA, "$ref": f"#/$defs/{definition}"})


EXAMPLES = [
    ("companies.json", "CompanyList", None),
    ("event.json", "Event", Event),
    ("insight_request.json", "InsightRequest", InsightRequest),
    ("insight.json", "Insight", Insight),
    ("error.json", "ErrorResponse", ErrorResponse),
]


@pytest.mark.parametrize("name,definition,model", EXAMPLES)
def test_examples_match_schema_and_models(name, definition, model):
    data = load_example(name)
    validator(definition).validate(data)
    if model is not None:
        model.model_validate(data)


def test_company_examples_validate_as_models():
    items = load_example("companies.json")["items"]
    profiles = [CompanyProfile.model_validate(item) for item in items]
    by_id = {p.company_id: p for p in profiles}
    assert by_id["demo_company_001"].has_credit is True
    assert by_id["demo_company_001"].has_deposit is False
    assert by_id["demo_company_002"].has_credit is False
    assert by_id["demo_company_002"].has_deposit is True
    assert all(p.display_name.startswith("Демо") for p in profiles)


def test_public_schema_matches_pydantic_models():
    _, generated = models_json_schema([(m, "validation") for m in MODELS], ref_template="#/$defs/{model}")
    for name, definition in generated["$defs"].items():
        assert SCHEMA["$defs"][name] == definition, f"contracts/schemas/common.json устарел для {name}"


def valid_request() -> dict:
    return load_example("insight_request.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(role="cto"),
        lambda r: r.update(extra_field=1),
        lambda r: r.pop("event_id"),
        lambda r: r.update(company_id=""),
    ],
    ids=["wrong-role", "extra-field", "missing-field", "empty-id"],
)
def test_invalid_requests_are_rejected(mutate):
    request = valid_request()
    mutate(request)
    with pytest.raises(ValidationError):
        InsightRequest.model_validate(request)
    assert list(validator("InsightRequest").iter_errors(request))


def test_profile_requires_all_fields_and_allows_null():
    profile = load_example("companies.json")["items"][0]
    CompanyProfile.model_validate({**profile, "region": None, "has_credit": None, "has_deposit": None})
    incomplete = dict(profile)
    incomplete.pop("region")
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate(incomplete)
    assert list(validator("CompanyProfile").iter_errors(incomplete))


def test_insight_requires_mock_flags():
    insight = load_example("insight.json")
    for field, value in [("is_mock", False), ("bank_position", "x"), ("schema_version", "0.2.0")]:
        with pytest.raises(ValidationError):
            Insight.model_validate({**insight, field: value})


def test_healthz():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend"}


def test_openapi_routes_match_contract():
    contract = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"))
    actual = app.openapi()

    def routes(spec):
        return {(path, method) for path, ops in spec["paths"].items() for method in ops}

    assert routes(contract) == routes(actual)
    for path, ops in contract["paths"].items():
        for method, op in ops.items():
            assert set(op["responses"]) == set(actual["paths"][path][method]["responses"]), (path, method)
    assert "HTTPValidationError" not in actual.get("components", {}).get("schemas", {})
