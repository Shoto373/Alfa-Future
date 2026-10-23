#!/usr/bin/env bash
# Установка GitOps-агента на сервер (один раз; повторный запуск безопасен).
#
#   sudo GHCR_USER=dvaJf bash deploy/gitops/install.sh < ghcr-token
#
# Что нужно заранее:
#   - deploy key (только чтение) добавлен в репозиторий: публичная часть /root/.ssh/alfa_gitops.pub
#     (скрипт создаст ключ и остановится, если его еще нет в GitHub);
#   - в репозитории есть ветка `deploy` (ее создает CI после первого зеленого push в main);
#   - /etc/alfa-monitor.env с TG_TOKEN и TG_CHAT_ID (общий бот с мониторингом).
# Токен GHCR (read:packages) читается из stdin и сохраняется только в /root/.docker.
set -euo pipefail

REPO_SSH="${REPO_SSH:-git@github.com:dvaJf/alfa.git}"
REPO_DIR="${REPO_DIR:-/opt/alfa-gitops/repo}"
APP_DIR="${APP_DIR:-/home/egor/app}"
HERE="$(cd "$(dirname "$0")" && pwd)"
KEY=/root/.ssh/alfa_gitops

[ "$(id -u)" = 0 ] || { echo "запустите через sudo"; exit 1; }

# 1. Deploy key для чтения ветки deploy.
install -d -m 700 /root/.ssh
[ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -C "alfa-gitops@$(hostname)" -f "$KEY"
# Ключи хоста github.com — из официального API, а не «доверие при первом подключении».
curl -fsS -m 20 https://api.github.com/meta \
  | python3 -c 'import json,sys; [print("github.com", k) for k in json.load(sys.stdin)["ssh_keys"]]' > /root/.ssh/known_hosts_github
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=/root/.ssh/known_hosts_github -o StrictHostKeyChecking=yes"
if ! git ls-remote --heads "$REPO_SSH" deploy >/dev/null 2>&1; then
  echo "Нет доступа к $REPO_SSH или ветки deploy. Добавьте deploy key (read-only):"
  cat "$KEY.pub"
  exit 2
fi

# 2. Клон ветки deploy.
if [ ! -d "$REPO_DIR/.git" ]; then
  install -d -m 755 "$(dirname "$REPO_DIR")"
  git clone -q --single-branch --branch deploy "$REPO_SSH" "$REPO_DIR"
fi
git -C "$REPO_DIR" config core.sshCommand "$GIT_SSH_COMMAND"

# 3. Вход в GHCR (приватные образы).
if [ ! -t 0 ]; then
  token=$(cat)
  if [ -n "$token" ]; then
    printf '%s' "$token" | docker login ghcr.io -u "${GHCR_USER:?GHCR_USER}" --password-stdin >/dev/null
    echo "ghcr: вход выполнен"
  fi
fi

# 4. Текущее состояние прода как «прежняя версия» для первого отката.
if [ ! -f "$APP_DIR/release.env" ] && docker inspect alfa-backend >/dev/null 2>&1; then
  {
    echo "BACKEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' alfa-backend)"
    echo "FRONTEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' alfa-frontend)"
  } > "$APP_DIR/release.env"
  chown --reference="$APP_DIR" "$APP_DIR/release.env"
fi

# 5. Мониторинг молчит во время выкатки (контейнеры перезапускаются), но не дольше 15 минут.
MON=/usr/local/bin/alfa-monitor
if [ -f "$MON" ] && ! grep -q alfa-maintenance "$MON"; then
  sed -i '/^STATE_DIR=/i # Идет выкатка (alfa-gitops): проверки на паузе, но не дольше 15 минут.\nif [ -f /run/alfa-maintenance ] \&\& [ $(( $(date +%s) - $(stat -c %Y /run/alfa-maintenance) )) -lt 900 ]; then exit 0; fi\n' "$MON"
  bash -n "$MON"
fi

# 6. Агент и таймер.
install -m 755 "$HERE/alfa-gitops" /usr/local/bin/alfa-gitops
install -m 644 "$HERE/alfa-gitops.service" "$HERE/alfa-gitops.timer" /etc/systemd/system/
install -d -m 755 /var/lib/alfa-gitops /var/backups/alfa
systemctl daemon-reload
systemctl enable --now alfa-gitops.timer
echo "alfa-gitops установлен: $(systemctl is-active alfa-gitops.timer)"
