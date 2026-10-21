# Контракт 1.0.0

Контракт генерируется из кода (`cd backend && python scripts/gen_contracts.py`), а `backend/tests/test_contracts.py` проверяет, что файлы не расходятся с кодом:

- `openapi.json` — маршруты, параметры, коды ответов (интерактивно — `/docs` на backend);
- `schemas/common.json` — JSON Schema моделей из `backend/app/schemas.py`;
- `examples/` — реальные ответы агента на синтетических данных.

## Маршруты

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/healthz` | готовность |
| GET | `/api/v1/meta` | данные, база знаний, статус LLM, роли, темы |
| GET | `/api/v1/companies?q=&sector=&limit=&offset=` | поиск по профилям крупного бизнеса |
| GET | `/api/v1/companies/{id}` | профиль и экспозиции |
| GET | `/api/v1/feed?company_id=&role=&topic=` | персональная лента с причинами релевантности |
| GET/POST | `/api/v1/news/{id}`, `/api/v1/news` | новость; добавить текст или ссылку |
| POST | `/api/v1/news/refresh` | опрос RSS |
| POST | `/api/v1/insights` | разбор новости агентом (кэшируется; `force_refresh` пересчитывает) |
| GET | `/api/v1/insights/{id}` | карточка |
| POST | `/api/v1/insights/{id}/questions` | уточняющий вопрос |
| POST | `/api/v1/feedback` | оценка раздела |
| GET | `/api/v1/metrics`, `/api/v1/audit` | метрики качества, журнал инструментов |
| GET | `/api/v1/analytics`, `/api/v1/analytics/{doc}/pdf` | материалы банка, первоисточник |

## Ключевые правила

- `Claim.origin`: `fact` (новость), `client_data` (профиль), `bank` (тезис банка, только `source_id` вида `bank:*`), `ai` (вывод).
- У каждого утверждения есть `source_ids` из `Insight.sources`.
- Ошибки: `{"error": {"code", "message", "request_id", "retryable"}}`. Коды: 400 `INVALID_REQUEST` (вместо 422), 404 `*_NOT_FOUND`, 413 `REQUEST_TOO_LARGE`, 422 `FETCH_FAILED`, 500 `INTERNAL_ERROR` и `INVALID_ANALYSIS_RESULT`, 503 `ANALYSIS_UNAVAILABLE` и `DATA_UNAVAILABLE`, 504 `ANALYSIS_TIMEOUT`. Флаг `retryable` равен true только для 503 и 504.
- Лишние поля в запросах запрещены, тело запроса — до 64 КиБ.
