"""Генерирует публичный контракт из кода: contracts/openapi.json, schemas/common.json, examples/*.

    cd backend && python scripts/gen_contracts.py

test_contracts.py падает, если сгенерированные файлы расходятся с кодом.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("RUNTIME_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATA_DIR", str(ROOT / "data" / "synthetic"))
os.environ.pop("LLM_API_KEY", None)

from pydantic.json_schema import models_json_schema  # noqa: E402

from app import schemas  # noqa: E402

MODELS = [schemas.InsightRequest, schemas.QuestionRequest, schemas.NewsCreateRequest, schemas.FeedbackRequest,
          schemas.Insight, schemas.Answer, schemas.ErrorResponse]


def common_schema() -> dict:
    _, defs = models_json_schema([(m, "validation") for m in MODELS], ref_template="#/$defs/{model}")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": f"Alfa Pulse contract {schemas.SCHEMA_VERSION}", **defs}


def openapi() -> dict:
    from app.main import app
    return app.openapi()


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    out = ROOT / "contracts"
    write(out / "schemas" / "common.json", common_schema())
    write(out / "openapi.json", openapi())

    from app.agent import orchestrator, qa
    from app.companies import profiles
    from app.news import store
    company = next(c for c in profiles._load()["companies"] if c["products"]["loans"])
    request = {"company_id": company["company_id"], "role": "cfo", "news_id": "seed-rate-hold"}
    insight = asyncio.run(orchestrator.run(company, "cfo", store.get("seed-rate-hold"), "req_example"))
    answer = qa.answer(insight, company, "Какие источники использованы?")
    error = {"error": {"code": "ANALYSIS_UNAVAILABLE", "message": "Анализ временно недоступен",
                       "request_id": "req_example_2", "retryable": True}}
    for name, data in [("insight_request.json", request), ("insight.json", insight), ("answer.json", answer),
                       ("error.json", error), ("news_create.json", {"text": "Минфин объявил о росте НДС с 1 января 2027 года."})]:
        write(out / "examples" / name, data)
    print("contracts regenerated")


if __name__ == "__main__":
    main()
