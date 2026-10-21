# Приемка спринта 1

| | |
|---|---|
| Проверенная сборка | `main` @ `c6b572b` (PR #4, #5) + ветка `task/spr1-fixes` (убран 422 из `/openapi.json`, UI-проверки) |
| Дата | 2026-10-21 |
| ОС | Windows 11 Enterprise LTSC 2024 (10.0.26100) |
| Docker | 29.3.1, Compose из Docker Desktop |
| Локально | Python 3.14.3 (тесты), Node 24.17.0 / npm 11.13.0 (сборка frontend) |
| В образах | python:3.11-slim, node:20-alpine |
| Браузер | Chromium Headless Shell 140.0.7339.16 (Playwright 1.55.0) |

## Автоматические проверки

| Команда | Результат |
|---|---|
| `cd backend && python -m pytest -q` | **54 passed** (contracts, api, companies, analysis) |
| `python -m pytest backend/tests -q` (как в CI) | **54 passed** |
| `cd frontend && npm run typecheck` | без ошибок |
| `cd frontend && npm run build` | успешно, маршруты `/`, `/analytics` |
| `docker compose -f compose.yaml up --build -d` | оба сервиса собраны, `backend` и `frontend` — healthy |
| `curl -fsS http://localhost:8000/healthz` | `{"status":"ok","service":"backend"}` |
| `python tests/e2e/smoke.py --base-url http://localhost:8000` | **62 passed, 0 failed**, exit 0 |
| `docker compose stop backend` → `start` → smoke | **62 passed, 0 failed** |
| `docker compose restart backend` → smoke | **62 passed, 0 failed** |
| `/openapi.json` | коды ответов совпадают с `contracts/openapi.yaml` (без 422); сверяется в `test_openapi_routes_match_contract` |

Smoke-тест проверяет: healthz, список из двух синтетических компаний, 2 компании × 2 роли (поля и типы карточки, совпадение ID и роли, `schema_version`, `status`, `is_mock=true`, `bank_position=null`, уникальный `request_id`, упоминание об отсутствии LLM, источник `synthetic_fixture`), различимый `company_relevance` двух компаний, 404 для неизвестных company/event, 400 для неверной роли и лишнего поля, 413 для тела больше 64 КиБ.

Отказ `generate_insight` и тайм-аут проверяются API-тестами через подмену функции (`backend/tests/test_api.py`: `test_analysis_unavailable_returns_503`, `test_analysis_timeout_returns_504`, `test_unexpected_exception_returns_500`, `test_invalid_card_returns_500`, `test_context_mismatch_returns_500`). Публичного endpoint для искусственного отказа нет.

## UI-проверки

Выполнены в headless Chromium скриптом `tests/e2e/ui_check.py` против Docker-сборки (`http://localhost:3000`, реальный FastAPI). Шаг 11 — против `NEXT_PUBLIC_API_MOCK=empty npx next dev -p 3001`. Задержка ответа в шагах 4 и 7 создается внутри браузера оберткой над `fetch`; backend не меняется.

| # | Шаг | Ожидание | Результат |
|---|---|---|---|
| 1 | Открыть http://localhost:3000 | баннер «Демонстрационный макет…», переход по «Открыть новостную аналитику» | OK |
| 2 | Открыть аналитику | список из двух компаний загружается | OK |
| 3 | Метки | «Тестовые данные» и «Анализ без LLM» в заголовке раздела | OK |
| 4 | Компания 001, CFO → «Запустить анализ» | кнопка «Анализируем…» неактивна во время запроса; разделы «Факты», «Риски», «Возможности», «Действия», «Неопределенность», «Источники»; «Аналитика банка еще не подключена»; упомянут кредит | OK |
| 5 | Компания 002, CEO | проекция про депозитные инструменты, действия про планы финансирования | OK |
| 6 | Смена роли после результата | карточка очищается | OK |
| 7 | Смена компании во время запроса (ответ задержан на 2 с) | устаревший ответ не показывается, кнопка снова активна | OK |
| 8 | `docker compose stop backend` → «Запустить анализ» | «Нет связи с сервером…» и кнопка «Повторить» | OK |
| 10 | Перезагрузка страницы при остановленном backend | «Не удалось загрузить компании…» и «Повторить» | OK |
| 9 | `docker compose start backend`, healthy → «Повторить» | список загружается, анализ снова работает | OK |
| 11 | Пустой список (`NEXT_PUBLIC_API_MOCK=empty`) | «Список компаний пуст. Анализ недоступен.» и метка «Локальный mock API: empty» | OK |
| 12 | Ширина 375 px | нет горизонтальной прокрутки | OK |

Mock включается только переменной `NEXT_PUBLIC_API_MOCK` при локальной разработке. В Docker-сборке она не задается.

Не проверялось: другие браузеры (Firefox, Safari), реальные мобильные устройства, ручная визуальная оценка оформления.

## Дефекты и замечания

1. **В корне два compose-файла** (`compose.yaml` — спринт, `docker-compose.yml` — прод-деплой с nginx). Без `-f` Docker выбирает `compose.yaml` и выводит предупреждение. Владельцам инфраструктуры и деплоя: переименовать прод-файл (например, `docker-compose.prod.yml`) и обновить `.github/workflows/deploy.yml` и `deploy/deploy.sh`.
2. **CD деплоит не монолит спринта.** `deploy.yml` собирает корневой `Dockerfile` (`app/main.py` с Hello World), а не `backend/` + `frontend/`. Кроме того, CD запускается на каждом `pull_request` в `main`, то есть и на неслитых PR.
3. **Две копии requirements.** Корневой `requirements.txt` (для прод-образа) не совпадает с `backend/requirements.txt`.
4. Starlette предупреждает, что `httpx` в `TestClient` устарел (`StarletteDeprecationWarning`). На тесты не влияет.
5. **Процесс.** Задачи SPR1-00…05 сделаны одной интеграционной веткой, а не отдельными ветками и PR на каждую задачу, как предполагает план спринта.
6. **Исправлено в `task/spr1-fixes`:** FastAPI объявлял в `/openapi.json` ответ 422, хотя API возвращает 400 `INVALID_REQUEST`. Прежний тест сверял только маршруты; теперь сверяет и коды ответов.
