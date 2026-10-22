.PHONY: up down up-local down-local up-prod down-prod db migrate test demo

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

