#!/usr/bin/env bash
# Prueba de restauración en una base temporal. No toca producción.
set -euo pipefail

BACKUP="${1:-}"
DB_HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
USER_NAME="${PGUSER:-}"
KEEP="${KEEP_DATABASE:-no}"

[[ -n "$BACKUP" && -f "$BACKUP" ]] || { echo "Uso: $0 backup.dump" >&2; exit 1; }
[[ -n "$USER_NAME" ]] || { echo "Define PGUSER." >&2; exit 1; }

TEMP_DB="motorsmart_verify_$(date +%s)_$RANDOM"
cleanup() {
  if [[ "$KEEP" != "si" ]]; then
    dropdb --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" --if-exists "$TEMP_DB"
  else
    echo "Base temporal conservada: $TEMP_DB"
  fi
}
trap cleanup EXIT

createdb --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" "$TEMP_DB"
pg_restore --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" \
  --dbname="$TEMP_DB" --no-owner --no-privileges --exit-on-error "$BACKUP"
TALLERES="$(psql --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" \
  --dbname="$TEMP_DB" --tuples-only --no-align \
  --command='SELECT count(*) FROM talleres;')"
echo "Restauración verificada. Talleres restaurados: $TALLERES"
