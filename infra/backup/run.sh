#!/usr/bin/env bash
# Сервис backup: бэкап сразу после старта и затем раз в BACKUP_INTERVAL_HOURS часов (по умолчанию сутки);
# проверка восстановления — раз в RESTORE_TEST_DAYS дней (по умолчанию неделя). Ошибка не останавливает сервис:
# ее видно по метрикам и алертам «бэкап старше 26 ч».
set -uo pipefail
INTERVAL=$(( ${BACKUP_INTERVAL_HOURS:-24} * 3600 ))
RESTORE_EVERY=$(( ${RESTORE_TEST_DAYS:-7} * 86400 ))
last_restore=0
until pg_isready -q; do sleep 2; done
while true; do
  /infra/backup/backup.sh || echo "backup failed" >&2
  if [ $(( $(date +%s) - last_restore )) -ge "$RESTORE_EVERY" ]; then
    /infra/backup/restore_test.sh && last_restore=$(date +%s) || echo "restore test failed" >&2
  fi
  sleep "$INTERVAL"
done
