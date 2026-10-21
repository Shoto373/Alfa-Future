# Контракт 0.1.0

Публичный контракт:

- `openapi.yaml` — маршруты и коды ответов;
- `schemas/common.json` — JSON Schema тел (генерируется из `backend/app/schemas.py`, сверяется в `backend/tests/test_contracts.py`);
- `examples/` — валидные примеры: `companies.json`, `event.json`, `insight_request.json`, `insight.json`, `error.json`. Каталог используется как `FIXTURES_DIR`.

Фактический `/openapi.json` backend должен содержать те же маршруты и методы.

## Внутренние сигнатуры

```python
# backend/app/schemas.py
Role = Literal["ceo", "cfo"]
class CompanyProfile, Event, InsightRequest, Source, Insight, ErrorDetail, ErrorResponse

# backend/app/errors.py
class AnalysisUnavailable(Exception)    # API -> 503 ANALYSIS_UNAVAILABLE
class InvalidAnalysisResult(Exception)  # API -> 500 INVALID_ANALYSIS_RESULT

# backend/app/analysis/service.py
async def generate_insight(company: CompanyProfile, role: Role, event: Event, request_id: str) -> Insight

# backend/app/companies/repository.py
def get_company(company_id: str) -> CompanyProfile | None
def get_event(event_id: str) -> Event | None
```

`generate_insight` вызывается только внутри процесса. Модуль анализа не ищет компании, не читает fixtures и не открывает HTTP endpoint. API создает `request_id`, ограничивает вызов `ANALYSIS_TIMEOUT_SECONDS` и проверяет, что `request_id`, `company_id`, `event_id`, `role` в результате совпадают с запросом.

## Правила

- Все поля обязательны, массивы могут быть пустыми; `null` означает «неизвестно», а не `false`.
- Лишние поля в запросах запрещены (`additionalProperties: false`).
- `is_synthetic: true`, `is_mock: true`, `bank_position: null`, `sources[].kind: "synthetic_fixture"`.

## Перегенерация схемы

Схема `schemas/common.json` строится функцией `pydantic.json_schema.models_json_schema` по моделям из `schemas.py` (плюс `CompanyList` и `Healthz`). Если модели меняются, обновите схему и примеры; `test_contracts.py` упадет при расхождении.
