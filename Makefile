.PHONY: up down up-local down-local up-prod down-prod db migrate test demo smoke check up-auth up-monitoring restore-test

up up-local:
	docker compose -f compose.yaml up -d --build

down down-local:
	docker compose -f compose.yaml down

up-prod:
	docker compose -f docker-compose.yml up -d --build

down-prod:
	docker compose -f docker-compose.yml down

db:
	docker compose -f compose.yaml up -d postgres

migrate:
	docker compose -f compose.yaml exec backend alembic upgrade head

test:
	docker compose -f compose.yaml --profile test run --rm tests

demo:
	docker compose -f compose.yaml exec backend python -m app.demo --rules

# Проверка запущенного сервиса под демо-учетками (app/smoke.py): ничего не создает, модель не вызывает.
smoke:
	docker compose -f compose.yaml exec -e SMOKE_EMAIL=demo@alfa.test -e SMOKE_OPERATOR_EMAIL=operator@alfa.test \
	  -e SMOKE_PASSWORD="$${DEMO_PASSWORD:-alfa-demo-2026}" -e SMOKE_OPERATOR_PASSWORD="$${DEMO_PASSWORD:-alfa-demo-2026}" \
	  backend python -m app.smoke --base-url http://nginx --front http://frontend:3000

# Перед выгрузкой: все backend-тесты и проверка запущенного сервиса.
check: test smoke

# Наблюдаемость: Grafana http://localhost:3001 (admin / GRAFANA_ADMIN_PASSWORD), Prometheus, алерты, трассы, бэкапы.
up-monitoring:
	OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4318 docker compose -f compose.yaml --profile monitoring up -d --build

restore-test:
	bash infra/backup/restore_test.sh

# Вход через Альфа-ID (демо-IdP Keycloak, OIDC): тот же стенд + keycloak, кнопка «Войти через Альфа-ID».
up-auth:
	OIDC_ISSUER=http://localhost:8180/realms/alfa OIDC_INTERNAL_ISSUER=http://keycloak:8080/realms/alfa \
	  docker compose -f compose.yaml --profile auth up -d --build
