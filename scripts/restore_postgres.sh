#!/usr/bin/env bash
# Restaura un backup en la base indicada. Exige CONFIRMAR=si.
set -euo pipefail

BACKUP="${1:-}"
DATABASE="${2:-}"
DB_HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
USER_NAME="${PGUSER:-}"

[[ "${CONFIRMAR:-}" == "si" ]] || { echo "Ejecuta con CONFIRMAR=si." >&2; exit 1; }
[[ -n "$BACKUP" && -f "$BACKUP" ]] || { echo "Uso: $0 backup.dump base" >&2; exit 1; }
[[ -n "$DATABASE" ]] || { echo "Falta el nombre de la base." >&2; exit 1; }

if [[ -f "${BACKUP}.sha256" ]]; then
  ( cd "$(dirname "$BACKUP")" && sha256sum --check "$(basename "$BACKUP").sha256" )
fi

pg_restore --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" \
  --dbname="$DATABASE" --clean --if-exists --no-owner --no-privileges \
  --exit-on-error "$BACKUP"
echo "Restauración completada. Aplica migraciones con: alembic upgrade head"
