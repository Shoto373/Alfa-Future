# Правила для участников и агентов

Архитектура спринта 1: Next.js (`frontend/`) → один FastAPI backend (`backend/`) → внутренний модуль анализа (вызов Python-функции). Без отдельного ML-сервиса, БД, LLM и авторизации. Только синтетические данные.

## Владение файлами

| Зона | Файлы | Владелец |
|---|---|---|
| Каркас и контракты (SPR1-00) | `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/errors.py`, `backend/requirements.txt`, `backend/.python-version`, `contracts/**`, `AGENTS.md`, `.gitignore`, `backend/tests/test_contracts.py` | владелец каркаса |
| API и компании (SPR1-01) | `backend/app/api/**`, `backend/app/companies/**`, `backend/tests/test_api.py`, `backend/tests/test_companies.py` | SPR1-01 |
| Интерфейс (SPR1-02) | `frontend/**`, кроме `frontend/Dockerfile` и `frontend/.dockerignore` | SPR1-02 |
| Анализ (SPR1-03) | `backend/app/analysis/**`, `backend/tests/test_analysis.py` | SPR1-03 |
| Docker и окружение (SPR1-04) | `infra/**`, `compose.yaml`, `.env.example`, `.dockerignore`, `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore` | SPR1-04 |
| Приемка и документация (SPR1-05) | `tests/e2e/**`, `docs/sprint-01/**`, `README.md`, `THIRD_PARTY_NOTICES` | SPR1-05 |

Файлы каркаса после baseline меняет только их владелец через интегратора. Изменение вне своей зоны — точный запрос интегратору.

Файлы вне таблицы (`app/`, корневые `Dockerfile`, `requirements.txt`, `docker-compose.yml`, `nginx/`, `deploy/`, `.github/`) относятся к ранее созданному прод-деплою и не удаляются без отдельного согласования.

## Правила работы

- Перед работой: `git status --short --branch`, `git log -1 --oneline`, прочитать этот файл и `contracts/`.
- Не делать `reset --hard`, `git clean`, force push и merge в `main` без интегратора.
- Не коммитить `.env`, ключи, реальные CSV/PDF и персональные данные.
- Новая зависимость — запрос владельцу `requirements.txt` / `package.json` с обоснованием.
- Противоречие с контрактом показать до реализации.
- Не заявлять тесты пройденными без запуска.

## Проверки

```bash
cd backend && python -m pytest -q
cd frontend && npm ci && npm run typecheck && npm run build
docker compose up --build -d && python tests/e2e/smoke.py --base-url http://localhost:8000
```
