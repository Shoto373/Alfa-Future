# Приемка спринта 1

| | |
|---|---|
| Integration commit | `5fda627` (ветка `task/spr1-integration`, база `main` @ `bcf785d`) |
| Дата | 2026-10-21 |
| ОС | Windows 11 Enterprise LTSC 2024 (10.0.26100) |
| Docker | 29.3.1, Compose из Docker Desktop |
| Локально | Python 3.14.3 (тесты), Node 24.17.0 / npm 11.13.0 (сборка frontend) |
| В образах | python:3.11-slim, node:20-alpine |

## Автоматические проверки

| Команда | Результат |
|---|---|
| `cd backend && python -m pytest -q` | **54 passed** (contracts, api, companies, analysis) |
| `python -m pytest backend/tests -q` (как в CI) | **54 passed** |
| `cd frontend && npm run typecheck` | без ошибок |
| `cd frontend && npm run build` | успешно, маршруты `/`, `/analytics` |
| `docker compose config --quiet` | OK (предупреждение о двух compose-файлах, см. дефекты) |
| `docker compose up --build -d` | оба сервиса собраны, `backend` и `frontend` — healthy |
| `curl -fsS http://localhost:8000/healthz` | `{"status":"ok","service":"backend"}` |
| `curl -fsS http://localhost:3000/` | HTTP 200 |
| `python tests/e2e/smoke.py --base-url http://localhost:8000` | **62 passed, 0 failed**, exit 0 |
| `docker compose stop backend` | frontend продолжает отдавать страницы (HTTP 200); backend — connection refused |
| `docker compose start backend` → smoke | **62 passed, 0 failed** |
| `docker compose restart backend` → smoke | **62 passed, 0 failed** |

Smoke-тест проверяет: healthz, список из двух синтетических компаний, 2 компании × 2 роли (поля и типы карточки, совпадение ID и роли, `schema_version`, `status`, `is_mock=true`, `bank_position=null`, уникальный `request_id`, упоминание об отсутствии LLM, источник `synthetic_fixture`), различимый `company_relevance` двух компаний, 404 для неизвестных company/event, 400 для неверной роли и лишнего поля, 413 для тела больше 64 КиБ.

Отказ `generate_insight` и тайм-аут проверяются API-тестами через подмену функции (`backend/tests/test_api.py`: `test_analysis_unavailable_returns_503`, `test_analysis_timeout_returns_504`, `test_unexpected_exception_returns_500`, `test_invalid_card_returns_500`, `test_context_mismatch_returns_500`). Публичного endpoint для искусственного отказа нет.

## Ручные UI-проверки

**Статус: в браузере не выполнялись** (во время приемки браузерных инструментов не было). Проверено только, что страницы `/` и `/analytics` отдаются с HTTP 200 и содержат раздел «Новостная аналитика». Перед сдачей пройдите чек-лист в браузере и впишите сюда браузер и версию.

| # | Шаг | Ожидание | Результат |
|---|---|---|---|
| 1 | Открыть http://localhost:3000 | баннер «Демонстрационный макет…», кнопка «Открыть новостную аналитику» | — |
| 2 | Открыть аналитику | сначала «Загружаем список компаний…», затем две компании | — |
| 3 | Метки | «Тестовые данные» и «Анализ без LLM» видны всегда | — |
| 4 | Компания 001, CFO → «Запустить анализ» | кнопка неактивна во время запроса; карточка: факты, риски, возможности, действия, неопределенность, источники; «Аналитика банка еще не подключена» | — |
| 5 | Компания 002, CEO | другой `company_relevance` (депозит), действия про планы финансирования | — |
| 6 | Смена компании/роли после результата | карточка очищается | — |
| 7 | Смена выбора во время запроса | старый ответ не показывается (`NEXT_PUBLIC_API_MOCK=slow` для наглядности) | — |
| 8 | `docker compose stop backend` → «Запустить анализ» | «Нет связи с сервером…» и кнопка «Повторить» (HTTP 503 не гарантируется — это сетевая ошибка) | — |
| 9 | `docker compose start backend`, дождаться healthy → «Повторить» | карточка появляется | — |
| 10 | Перезагрузить страницу при остановленном backend | ошибка загрузки списка и «Повторить» | — |
| 11 | Пустой список: `cd frontend && NEXT_PUBLIC_API_MOCK=empty npm run dev` | «Список компаний пуст. Анализ недоступен.» и метка «Локальный mock API» | — |

Mock включается только переменной `NEXT_PUBLIC_API_MOCK` при локальной разработке. В Docker-сборке она не задается.

## Дефекты и замечания

1. **В корне два compose-файла** (`compose.yaml` — спринт, `docker-compose.yml` — прод-деплой с nginx). Docker выбирает `compose.yaml` и выводит предупреждение. Владельцам инфраструктуры и деплоя: переименовать прод-файл (например, `docker-compose.prod.yml`) и обновить `.github/workflows/deploy.yml` и `deploy/deploy.sh`.
2. **CD деплоит не монолит спринта.** `deploy.yml` собирает корневой `Dockerfile` (`app/main.py` с Hello World), а не `backend/` + `frontend/`. Кроме того, CD запускается на каждом `pull_request` в `main`, то есть и на неслитых PR.
3. **Две копии requirements.** Корневой `requirements.txt` (для прод-образа) не совпадает с `backend/requirements.txt`.
4. Starlette предупреждает, что `httpx` в `TestClient` устарел (`StarletteDeprecationWarning`). На тесты не влияет.
5. `contracts/examples/event.json` упоминает «Банк России» как учебный контекст. Само событие синтетическое.
