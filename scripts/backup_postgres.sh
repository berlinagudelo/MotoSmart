#!/usr/bin/env bash
# Backup lógico de PostgreSQL para MotoSmart (Linux/macOS).
set -euo pipefail

OUTPUT_DIR="${MOTOSMART_BACKUP_DIR:-$(cd "$(dirname "$0")/.." && pwd)/backups}"
DATABASE="${PGDATABASE:-}"
DB_HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
USER_NAME="${PGUSER:-}"
RETENTION_DAYS="${MOTOSMART_BACKUP_RETENTION_DAYS:-30}"

[[ -n "$DATABASE" ]] || { echo "Define PGDATABASE." >&2; exit 1; }
[[ -n "$USER_NAME" ]] || { echo "Define PGUSER." >&2; exit 1; }
command -v pg_dump >/dev/null || { echo "pg_dump no está en PATH." >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BASE="motorsmart-${DATABASE}-${STAMP}"
DUMP="$OUTPUT_DIR/${BASE}.dump"

pg_dump --host="$DB_HOST" --port="$PORT" --username="$USER_NAME" \
  --dbname="$DATABASE" --format=custom --compress=9 \
  --no-owner --no-privileges --file="$DUMP"

( cd "$OUTPUT_DIR" && sha256sum "${BASE}.dump" > "${BASE}.dump.sha256" )
pg_restore --list "$DUMP" >/dev/null
echo "Backup verificado: $DUMP"

find "$OUTPUT_DIR" -maxdepth 1 -type f -name 'motorsmart-*.dump*' \
  -mtime "+${RETENTION_DAYS}" -print -delete || true
