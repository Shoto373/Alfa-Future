# Инфраструктура

## Локально — `compose.yaml`

Два сервиса: `backend` на 127.0.0.1:8000 и `frontend` на 127.0.0.1:3000. Контекст сборки — корень репозитория.

```bash
docker compose -f compose.yaml up --build -d
CASE_DATA_DIR=./контекст/data BANK_PDF_HOST_DIR=./контекст/<pdf> docker compose -f compose.yaml up --build -d   # реальные данные кейса
```

- `/data/case` (только чтение) — CSV кейса. Если CSV нет, используется синтетика из образа.
- `/data/bank_pdf` (только чтение) — PDF аналитики банка.
- Том `runtime` — профили, новости, карточки, отзывы, аудит. Переживает перезапуск. Не удаляйте его через `down -v` без необходимости.
- Healthcheck backend: `start_period` 120 с, потому что первая сборка профилей на полном наборе данных занимает около 20 с.
- `.env` подхватывается backend'ом: ключ LLM, RSS.

## Прод — `docker-compose.yml` (pointers-team.online)

Сервисы `backend`, `frontend` и `nginx` (HTTPS, Let's Encrypt). nginx отправляет `/api/`, `/healthz`, `/docs` и `/openapi.json` в backend, остальное — во frontend. Frontend собирается с `NEXT_PUBLIC_API_BASE_URL=https://pointers-team.online`.

CD (`.github/workflows/deploy.yml`) собирает образы `ghcr.io/dvajf/alfa:backend-<sha>` и `frontend-<sha>`, копирует compose, nginx и `deploy.sh` на сервер, затем `deploy.sh` выполняет pull, `up` и ждёт состояния healthy.

Данные кейса на сервере лежат вне репозитория: `~/app/case-data/csv` и `~/app/case-data/pdf`. Каталоги монтируются через `CASE_DATA_DIR` и `BANK_PDF_HOST_DIR`, по умолчанию берутся эти пути. Ключ LLM хранится в `~/app/.env`.
