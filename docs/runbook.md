# Runbook Альфа.Пульса

Что смотреть и что делать при инцидентах. Наблюдаемость — профиль `monitoring` в `compose.yaml` (SPR3-05).

## Запуск мониторинга

```bash
make up-monitoring
```

| Что | Где |
|---|---|
| Grafana: дашборды «Сервис», «Агент и LLM», «Воркер» | http://localhost:3001 (admin / `GRAFANA_ADMIN_PASSWORD`, локально `alfa-demo-2026`) |
| Prometheus: метрики, алерты | http://localhost:9090 |
| Метрики одного экземпляра API | `curl -s localhost:8000/metrics \| grep alfa_` |
| Трассы разборов | Grafana → Explore → Tempo; `trace_id` — в `Insight.trace[*].output.trace_id` и в логе запроса |
| Логи | `docker compose logs backend worker` — JSON: `request_id`, `user` (псевдоним), `company_id`, `route`, `status`, `duration_ms` |

Телеметрия не уходит во внешние сервисы: Prometheus, Tempo и Grafana работают в той же сети. Логи не содержат текстов новостей, профилей, тел запросов и идентификаторов пользователей (только псевдоним `user` — хэш).

`/metrics` не публикуется nginx в production. При заданном `METRICS_TOKEN` для `/metrics` и приемника алертов нужен заголовок `Authorization: Bearer <токен>`.

## Алерты

Алерты приходят в Telegram-канал команды: Alertmanager → `POST /internal/alerts` в backend → бот (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Без бота алерт пишется в лог backend (`alert firing …`).

Проверить канал можно тестовым алертом:

```bash
docker compose exec alertmanager wget -qO- --header "Content-Type: application/json" \
  --post-data '[{"labels":{"alertname":"TestAlert"},"annotations":{"summary":"Проверка канала"}}]' \
  http://localhost:9093/api/v2/alerts
```

### Бюджет LLM

`LLMBudgetOver80`: потрачено и зарезервировано больше 80% дневного лимита (`alfa_llm_budget_spent_ratio`).

1. Дашборд «Агент и LLM»: какая статья тратит — разборы пользователей, конвейер (`PIPELINE_LLM_SHARE`) или распознавание аналитики (`budget:kb_ingest`).
2. Если причина — конвейер, временно уменьшить `PIPELINE_LLM_PER_CYCLE` или выключить AI-разборы заранее у компаний.
3. При подозрении на утечку ключа — выключатель AI на странице «Качество» (`POST /api/v1/ops/llm {"paused": true}`). Разборы продолжаются на правилах. Ключ не перевыпускается, поэтому главное — остановить расход.
4. Лимит сбрасывается в 03:00 по Москве.

### Медленные разборы

`InsightsSlowP95`: p95 `POST /api/v1/insights` выше 30 с в течение 10 минут.

1. «Агент и LLM» → «p95 этапов агента»: долгий этап `compose` или `check` — значит, медленно отвечает модель. Шлюз переключается на запасной адрес (`LLM_FALLBACK_BASE_URL`) сам.
2. Трасса медленного разбора в Tempo покажет, какой шаг занял время.
3. Временная мера — `LLM_REASONING_COMPOSE=off` (черновик без рассуждений быстрее) или выключатель AI.

### Ошибки 5xx

`HTTP5xxOver1Percent`: доля ответов 5xx выше 1% за 5 минут.

1. «Сервис» → маршрут с ошибками. Логи: `docker compose logs backend | grep '"status": 5'`, по `request_id` найти исключение.
2. Проверить PostgreSQL (`docker compose ps postgres`) и Redis. Без Redis API работает (кэш в памяти), без PostgreSQL — нет.
3. Один экземпляр API упал — nginx отправляет запросы на второй (`proxy_next_upstream`). Перезапуск: `docker compose restart backend`.

### Лента не обновляется

`NewsLagOver30m`: источники новостей не отвечали успешно больше 30 минут (`alfa_news_lag_seconds`).

1. «Воркер»: жив ли воркер (`alfa_worker_heartbeat_age_seconds` < 120), нет ли мертвых задач (`alfa_jobs{status="dead"}`).
2. «Ошибки источников»: падает один источник или все. Все сразу — сеть или DNS на сервере; один — сайт источника.
3. Воркер не работает — `docker compose restart worker`. Накопленные задачи выполнятся после старта, API все это время отвечает.

### Бэкап

`BackupOlderThan26h`: последний успешный бэкап старше 26 часов или метрики нет.

1. `docker compose logs backup` — ошибка `pg_dump` (место на диске, доступ к базе).
2. Запустить вручную: `docker compose exec backup /infra/backup/backup.sh`.

## Бэкап и восстановление

Сервис `backup` (профиль `monitoring`): `pg_dump` в формате custom сразу после старта и затем раз в сутки (`BACKUP_INTERVAL_HOURS`). Файлы хранятся в томе `backups` 14 дней (`BACKUP_KEEP_DAYS`). Время последнего бэкапа и версия миграций записываются в `app_state.backup_last`.

Раз в неделю (`RESTORE_TEST_DAYS`) последний бэкап разворачивается в отдельную базу `alfa_restore_test` и проверяется: версия миграций совпадает с версией на момент бэкапа, таблицы `news`, `bank_theses`, `bank_documents`, `companies` не пусты. Затем проверочная база удаляется. Результат — `app_state.restore_test_last` и метрика `alfa_restore_test_last_success_timestamp_seconds`.

Проверка вручную:

```bash
make restore-test
```

Проверено 24.10.2026 на локальном стенде: восстановление заняло 1–2 с (цель — не дольше 15 минут), миграции 0010, 297 новостей, 43 тезиса, 124 компании, 40 пользователей.

### Восстановление рабочей базы

1. Остановить запись: `docker compose stop backend worker`.
2. Выбрать файл: `docker compose exec backup ls -1t /backups`.
3. Восстановить в рабочую базу (данные после бэкапа будут потеряны):

   ```bash
   docker compose exec backup sh -c 'pg_restore --clean --if-exists --no-owner -d alfa /backups/<файл>.dump'
   ```

4. Запустить сервис: `docker compose start backend worker`. Миграции, если бэкап старше схемы, применятся при старте.
5. Проверить: `make smoke`.

## Production

В `docker-compose.yml` мониторинг и бэкап пока не включены. Для пилота сервисы `prometheus`, `alertmanager`, `tempo`, `grafana` и `backup` переносятся из `compose.yaml` с теми же файлами `infra/`. Нужно задать `METRICS_TOKEN`, `GRAFANA_ADMIN_PASSWORD`, бота Telegram и вынести том `backups` на отдельный диск или в объектное хранилище банка.
