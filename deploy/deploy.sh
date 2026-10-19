#!/usr/bin/env bash
# Runs on the SERVER after the image was pushed to GHCR.
set -euo pipefail
cd "$(dirname "$0")/.."          # ~/app, where docker-compose.prod.yml lives

: "${IMAGE:?IMAGE not set}"
: "${GHCR_TOKEN:?GHCR_TOKEN not set}"

touch .env

echo "==> Deploying $IMAGE"
echo "$GHCR_TOKEN" | docker login ghcr.io -u "${ACTOR:-ci}" --password-stdin

docker pull "$IMAGE"
docker stop alfa-app 2>/dev/null || true
docker rm alfa-app 2>/dev/null || true
docker stop alfa-nginx 2>/dev/null || true
docker rm alfa-nginx 2>/dev/null || true

docker run -d \
  --name alfa-app \
  --restart unless-stopped \
  -p 80:8000 \
  -p 8000:8000 \
  --env-file .env \
  "$IMAGE"

# Wait until the container reports running before cleaning up old images.
for i in $(seq 1 30); do
  status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' alfa-app 2>/dev/null || echo starting)
  [ "$status" = "healthy" ] && break
  [ "$status" = "running" ] && [ "$i" -ge 3 ] && break
  sleep 2
done

if [ "$status" != "healthy" ] && [ "$status" != "running" ]; then
  echo "!! Container not healthy (status=$status), logs:"
  docker logs --tail=50 alfa-app
  exit 1
fi

docker image prune -af --filter "until=168h" >/dev/null
docker logout ghcr.io
echo "==> Deployed OK ($IMAGE)"
