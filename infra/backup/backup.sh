#!/usr/bin/env bash
# Бэкап PostgreSQL (SPR3-05): pg_dump в формате custom, ротация BACKUP_KEEP_DAYS дней,
# отметка об успехе — в app_state (метрика alfa_backup_last_success_timestamp_seconds, алерт «бэкап старше 26 ч»).
set -euo pipefail
: "${PGHOST:?}" "${PGDATABASE:?}" "${PGUSER:?}"
DIR="${BACKUP_DIR:-/backups}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$DIR"
stamp="$(date -u +%Y%m%d-%H%M%S)"
file="$DIR/${PGDATABASE}-${stamp}.dump"
started=$(date +%s)
pg_dump --format=custom --compress=6 --no-owner --file="$file.part" "$PGDATABASE"
mv "$file.part" "$file"
size=$(stat -c %s "$file")
find "$DIR" -name "${PGDATABASE}-*.dump*" -mtime "+$KEEP" -delete
seconds=$(( $(date +%s) - started ))
# Версия миграций в момент бэкапа: проверка восстановления сравнивает с ней, а не с текущей базой.
alembic="$(psql -At "$PGDATABASE" -c 'SELECT version_num FROM alembic_version')"
printf '%s
' "$alembic" > "$file.alembic"
psql -v ON_ERROR_STOP=1 -q "$PGDATABASE" <<SQL
INSERT INTO app_state (key, payload, updated_at)
VALUES ('backup_last', jsonb_build_object('at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"'),
        'file', '$(basename "$file")', 'bytes', $size, 'seconds', $seconds, 'alembic', '$alembic'), now())
ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now();
SQL
echo "backup ok: $file ($size bytes, ${seconds}s)"
