import json

from jsonschema import Draft202012Validator

from app import schemas
from tests.conftest import REPO

CONTRACTS = REPO / "contracts"


def load(path: str):
    return json.loads((CONTRACTS / path).read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({**load("schemas/common.json"), "$ref": f"#/$defs/{name}"})


def test_common_schema_is_up_to_date():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", REPO / "backend" / "scripts" / "gen_contracts.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert load("schemas/common.json") == json.loads(json.dumps(gen.common_schema(), ensure_ascii=False)), \
        "contracts/schemas/common.json устарел: запустите backend/scripts/gen_contracts.py"


def test_openapi_is_up_to_date(client):
    from app.main import app
    assert load("openapi.json") == json.loads(json.dumps(app.openapi(), ensure_ascii=False)), \
        "contracts/openapi.json устарел: запустите backend/scripts/gen_contracts.py"
    for ops in app.openapi()["paths"].values():
        for op in ops.values():
            assert "422" not in op["responses"], "API отвечает 400 INVALID_REQUEST, а не 422"


def test_examples_validate():
    for name, model in [("insight_request.json", "InsightRequest"), ("insight.json", "Insight"),
                        ("answer.json", "Answer"), ("error.json", "ErrorResponse"), ("news_create.json", "NewsCreateRequest")]:
        data = load(f"examples/{name}")
        validator(model).validate(data)
        getattr(schemas, model).model_validate(data)


def test_example_insight_separates_origins():
    ins = load("examples/insight.json")
    origins = {c["origin"] for sec in ("why_important", "risks", "opportunities", "actions") for c in ins[sec]}
    assert "client_data" in origins and "ai" in origins
    assert all(c["origin"] == "bank" for c in ins["bank_view"]["theses"])
