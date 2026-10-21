# Инфраструктура и окружение (SPR1-04)

В рамках первого спринта архитектура разворачивается через единый файл `compose.yaml`, состоящий ровно из двух сервисов монолита: `backend` и `frontend`.

## 1. Состав сервисов и порты

| Сервис | Описание | Порт на хосте | Внутренний порт |
|---|---|---|---|
| `backend` | Python / FastAPI монолит (Uvicorn) | `127.0.0.1:8000` | `8000` |
| `frontend` | TypeScript / React / Next.js | `127.0.0.1:3000` | `3000` |

* Все порты публикуются исключительно на `127.0.0.1` (localhost).
* Контекст сборки Docker для обоих сервисов — корень репозитория.

## 2. Переменные окружения и конфигурация

* `FIXTURES_DIR`: каталог с синтетическими фикстурами (`/app/contracts/examples`), монтируется в `backend` в режиме только для чтения (`:ro`).
* `FRONTEND_ORIGIN`: разрешенный адрес для CORS (`http://localhost:3000`).
* `ANALYSIS_TIMEOUT_SECONDS`: предельное время ожидания вызова внутреннего анализа (5 секунд).
* `NEXT_PUBLIC_API_BASE_URL`: передается в `frontend` на этапе сборки как build argument (`http://localhost:8000`). Браузер клиента обращается к API напрямую на localhost, не используя внутренние имена Docker-сети.

## 3. Проверка работоспособности (Readiness & Healthchecks)

* **Backend Healthcheck:**
  Выполняется встроенным Python-скриптом (urllib), проверяющим `GET /healthz`. Не зависит от наличия утилиты `curl` в slim-образе.
* **Frontend Healthcheck:**
  Выполняется через Node.js `fetch('http://127.0.0.1:3000/')`.
* `frontend` ожидает успешного состояния `service_healthy` от `backend` перед запуском.

## 4. Команды для сборки и запуска

```bash
# 1. Валидация конфигурации Compose
docker compose config --quiet

# 2. Сборка и фоновый запуск двух сервисов
docker compose up --build -d

# 3. Проверка статуса контейнеров
docker compose ps

# 4. Проверка доступности backend
curl -fsS http://localhost:8000/healthz

# 5. Проверка доступности frontend
curl -fsS http://localhost:3000/

# 6. Остановка сервисов (без удаления томов)
docker compose stop
```

## 5. Ограничения первого спринта

* Нет внешних баз данных (PostgreSQL), Redis и очередей сообщений (Celery/RabbitMQ).
* Синтетические данные читаются исключительно из локальных фикстур `contracts/examples/`.
* Вызовы внешних LLM API отсутствуют, LLM-ключи в окружении не используются.
