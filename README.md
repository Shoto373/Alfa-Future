# Альфа.Пульс — спринт 1

Техническая основа сервиса новостной аналитики для хакатона Альфа-Банка. Пользователь выбирает компанию и роль (CEO/CFO), запускает анализ учебного события и получает **явно тестовую** карточку: риски, возможности, действия, неопределенность и источники.

Это не готовое решение кейса: данные синтетические, LLM не вызывается, аналитика банка не подключена.

## Архитектура

```
Браузер ──► frontend (Next.js, :3000)
   │
   └─────► backend (FastAPI, :8000) ──► app.analysis.generate_insight()  (вызов Python-функции)
                       │
                       └── contracts/examples/*.json (FIXTURES_DIR, только чтение)
```

Ровно два сервиса Docker Compose: `backend` и `frontend`. Браузер обращается к backend напрямую по `NEXT_PUBLIC_API_BASE_URL`. Отдельного ML-сервиса, БД, очередей и авторизации нет.

| Каталог | Содержимое |
|---|---|
| `backend/` | FastAPI-монолит: `api/` (маршруты, ошибки, CORS, лимит тела), `companies/` (fixtures), `analysis/` (детерминированная карточка) |
| `frontend/` | Next.js / React / TypeScript: главный экран демо и раздел «Новостная аналитика» |
| `contracts/` | OpenAPI, JSON Schema, примеры — публичный контракт 0.1.0 |
| `infra/` | описание Docker-окружения |
| `tests/e2e/` | сквозной smoke-тест |
| `docs/sprint-01/` | протокол приемки |

Правила владения файлами — в [AGENTS.md](AGENTS.md).

## Конфигурация

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `FIXTURES_DIR` | `contracts/examples` (в Docker `/app/contracts/examples`) | каталог synthetic fixtures |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | единственный origin для CORS |
| `ANALYSIS_TIMEOUT_SECONDS` | `5` | тайм-аут вызова анализа (504) |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | адрес API для браузера, задается **при сборке** frontend |
| `NEXT_PUBLIC_API_MOCK` | не задан | только для локальной разработки: `ok`, `empty`, `error`, `slow` |

Пример — в `.env.example`. Ключи LLM не используются.

## Запуск

Нужен только Docker:

```bash
docker compose up --build -d
docker compose ps                     # оба сервиса healthy
curl -fsS http://localhost:8000/healthz
```

Откройте http://localhost:3000 → «Открыть новостную аналитику». Порты опубликованы только на `127.0.0.1`.

> В корне есть также `docker-compose.yml` прод-деплоя (nginx + HTTPS). Docker выбирает `compose.yaml` и выводит предупреждение. Явный вариант: `docker compose -f compose.yaml up --build -d`.

Локально без Docker:

```bash
cd backend && python -m pip install -r requirements.txt && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd frontend && npm ci && npm run dev
```

## Тесты

```bash
cd backend && python -m pytest -q                         # контракты, API, компании, анализ
cd frontend && npm ci && npm run typecheck && npm run build
python tests/e2e/smoke.py --base-url http://localhost:8000  # при запущенном backend
python tests/e2e/ui_check.py                                # UI в Chromium; нужен playwright, см. docstring
```

Smoke-тест использует только стандартную библиотеку Python и возвращает ненулевой код выхода при любой ошибке.

## API

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/healthz` | `{"status":"ok","service":"backend"}` |
| GET | `/api/v1/companies` | `{"items": CompanyProfile[]}` |
| POST | `/api/v1/insights` | `Insight` (синхронно, HTTP 200) |

Пример: `{"company_id":"demo_company_001","role":"cfo","event_id":"demo_event_001"}`.

Ошибки возвращаются в формате `{"error":{"code","message","request_id","retryable"}}`: 400 `INVALID_REQUEST`, 404 `COMPANY_NOT_FOUND`/`EVENT_NOT_FOUND`, 413 `REQUEST_TOO_LARGE` (тело больше 64 КиБ), 500 `INTERNAL_ERROR`/`INVALID_ANALYSIS_RESULT`, 503 `ANALYSIS_UNAVAILABLE`, 504 `ANALYSIS_TIMEOUT`. Подробности — `contracts/openapi.yaml`, интерактивно — http://localhost:8000/docs.

## Пользовательский сценарий

1. Главный экран демо → «Новостная аналитика».
2. Выбор компании (`Демо ПАО Северная Промышленность` — есть кредит; `Демо ООО Южный Ритейл` — есть депозит) и роли CEO/CFO.
3. «Запустить анализ» → карточка с метками «Тестовые данные» и «Анализ без LLM»; позиция банка — «Аналитика банка еще не подключена».
4. При смене компании или роли карточка очищается, устаревший ответ игнорируется.
5. При ошибке backend показывается сообщение и кнопка «Повторить».

## Ограничения спринта 1

- Только синтетические fixtures: одно событие, две компании. Реальных CSV/PDF, новостей и персональных данных нет.
- Карточка строится детерминированными правилами; LLM, агентный цикл и аналитика банка не подключены.
- Нет БД, истории, авторизации и чата.
- Тайм-ауты (5 с анализ, 10 с браузер) и лимит тела 64 КиБ предварительные.

Дедлайн хакатона — 26 октября 2026.
