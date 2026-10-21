# Правила для участников и агентов

Архитектура: Next.js (`frontend/`) → один FastAPI backend (`backend/`): профили компаний, новости, база знаний банка, ранжирование и агент — модули одного процесса. LLM — только модели кейса и только через `backend/app/agent/llm.py`. Данные кейса (`контекст/`, реальные CSV/PDF) в Git не попадают.

## Владение файлами

| Зона | Файлы | Владелец |
|---|---|---|
| Каркас и контракты (SPR1-00) | `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/errors.py`, `backend/requirements.txt`, `backend/.python-version`, `contracts/**`, `AGENTS.md`, `.gitignore`, `backend/tests/test_contracts.py` | владелец каркаса |
| API и данные компаний | `backend/app/api/**`, `backend/app/companies/**`, `backend/tests/test_api.py`, `backend/tests/test_data_pipeline.py` | API / данные |
| Новости и база знаний | `backend/app/news/**`, `backend/app/knowledge/**`, `backend/tests/test_news.py` | контент |
| Интерфейс (SPR1-02) | `frontend/**`, кроме `frontend/Dockerfile` и `frontend/.dockerignore` | SPR1-02 |
| Агент и ранжирование | `backend/app/agent/**`, `backend/app/ranking.py`, `backend/app/storage.py`, `backend/tests/test_agent.py` | AI |
| Docker и окружение (SPR1-04) | `infra/**`, `compose.yaml`, `.env.example`, `.dockerignore`, `backend/Dockerfile`, `backend/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore` | SPR1-04 |
| Приемка и документация | `tests/e2e/**`, `docs/**`, `README.md`, `THIRD_PARTY_NOTICES` | QA |

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
