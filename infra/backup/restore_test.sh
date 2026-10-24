#!/usr/bin/env bash
# Проверка восстановления (SPR3-05): последний бэкап разворачивается в отдельную БД ${PGDATABASE}_restore_test,
# затем smoke-проверки: версия миграций как в рабочей базе, ключевые таблицы не пусты. Результат и время
# восстановления — в app_state (метрика alfa_restore_test_last_success_timestamp_seconds). Цель — не дольше 15 минут.
# С хоста: bash infra/backup/restore_test.sh — скрипт сам выполнится в контейнере backup (профиль monitoring).
set -euo pipefail
if [ -z "${PGHOST:-}" ]; then
  # MSYS_NO_PATHCONV: Git Bash в Windows не подменяет путь внутри контейнера на путь Windows.
  MSYS_NO_PATHCONV=1 exec docker compose -f "$(dirname "$0")/../../compose.yaml" --profile monitoring exec -T backup /infra/backup/restore_test.sh
fi
DIR="${BACKUP_DIR:-/backups}"
TARGET="${PGDATABASE}_restore_test"
latest="$(ls -1t "$DIR"/"${PGDATABASE}"-*.dump 2>/dev/null | head -n1 || true)"
[ -n "$latest" ] || { echo "нет бэкапов в $DIR" >&2; exit 1; }
started=$(date +%s)
psql -v ON_ERROR_STOP=1 -q postgres -c "DROP DATABASE IF EXISTS \"$TARGET\";" -c "CREATE DATABASE \"$TARGET\";"
psql -v ON_ERROR_STOP=1 -q "$TARGET" -c "CREATE EXTENSION IF NOT EXISTS vector;"
pg_restore --no-owner --exit-on-error --dbname="$TARGET" "$latest"
seconds=$(( $(date +%s) - started ))

q() { psql -At -v ON_ERROR_STOP=1 "$1" -c "$2"; }
# Ожидаемая версия — записанная при бэкапе (схема могла обновиться после него).
source_rev="$(cat "$latest.alembic" 2>/dev/null || q "$PGDATABASE" 'SELECT version_num FROM alembic_version')"
restored_rev="$(q "$TARGET" 'SELECT version_num FROM alembic_version')"
[ "$source_rev" = "$restored_rev" ] || { echo "версия миграций $restored_rev, ожидалась $source_rev" >&2; exit 1; }
for table in news bank_theses bank_documents companies; do
  n="$(q "$TARGET" "SELECT count(*) FROM $table")"
  [ "$n" -gt 0 ] || { echo "таблица $table пуста после восстановления" >&2; exit 1; }
  echo "  $table: $n"
done
users="$(q "$TARGET" 'SELECT count(*) FROM users')"
q postgres "DROP DATABASE \"$TARGET\";" >/dev/null
psql -v ON_ERROR_STOP=1 -q "$PGDATABASE" <<SQL
INSERT INTO app_state (key, payload, updated_at)
VALUES ('restore_test_last', jsonb_build_object('at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'file', '$(basename "$latest")', 'seconds', $seconds, 'alembic', '$restored_rev', 'users', $users), now())
ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now();
SQL
echo "restore ok: $(basename "$latest") за ${seconds}s, миграции $restored_rev, пользователей $users"
