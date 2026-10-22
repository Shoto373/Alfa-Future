#!/usr/bin/env bash
# Runs on the SERVER after the images were pushed to GHCR.
set -euo pipefail
cd "$(dirname "$0")/.."          # ~/app, where docker-compose.yml lives

: "${BACKEND_IMAGE:?BACKEND_IMAGE not set}"
: "${FRONTEND_IMAGE:?FRONTEND_IMAGE not set}"
: "${GHCR_TOKEN:?GHCR_TOKEN not set}"

# Do not let an exported empty value override the password saved in .env.
if [ -z "${POSTGRES_PASSWORD:-}" ]; then unset POSTGRES_PASSWORD; fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "!! Python 3 is required on the server to prepare deployment configuration"
  exit 1
fi
python3 deploy/prepare_env.py
docker compose config --quiet

echo "==> Deploying $BACKEND_IMAGE + $FRONTEND_IMAGE"
echo "$GHCR_TOKEN" | docker login ghcr.io -u "${ACTOR:-ci}" --password-stdin

export BACKEND_IMAGE FRONTEND_IMAGE
docker compose pull backend frontend
docker compose up -d --no-build --remove-orphans

# Wait until backend and frontend report healthy before cleaning up old images.
healthy() {
  [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$1" 2>/dev/null)" = "healthy" ]
}
for i in $(seq 1 45); do
  healthy alfa-backend && healthy alfa-frontend && break
  sleep 2
done

if ! healthy alfa-backend || ! healthy alfa-frontend; then
  echo "!! Containers not healthy, logs:"
  docker compose ps
  docker logs --tail=50 alfa-backend || true
  docker logs --tail=50 alfa-frontend || true
  exit 1
fi

# nginx resolves upstreams per request; reload just in case config changed.
docker exec alfa-nginx nginx -s reload || docker compose restart nginx

docker image prune -af --filter "until=168h" >/dev/null
docker logout ghcr.io
echo "==> Deployed OK"
