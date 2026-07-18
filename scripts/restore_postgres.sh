#!/bin/sh
set -eu

: "${TARGET_POSTGRES_DSN:?TARGET_POSTGRES_DSN is required}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"
: "${ALLOW_EMPTY_DATABASE_RESTORE:?Set ALLOW_EMPTY_DATABASE_RESTORE=YES}"

if [ "$ALLOW_EMPTY_DATABASE_RESTORE" != "YES" ]; then
  printf '%s\n' "Refusing restore without ALLOW_EMPTY_DATABASE_RESTORE=YES" >&2
  exit 2
fi
if [ ! -r "$BACKUP_FILE" ]; then
  printf 'Backup is not readable: %s\n' "$BACKUP_FILE" >&2
  exit 2
fi

checksum_file="${BACKUP_FILE}.sha256"
if [ -r "$checksum_file" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$checksum_file")")
  else
    expected=$(awk '{print $1}' "$checksum_file")
    actual=$(shasum -a 256 "$BACKUP_FILE" | awk '{print $1}')
    [ "$expected" = "$actual" ] || {
      printf '%s\n' "Backup checksum mismatch" >&2
      exit 2
    }
  fi
fi

table_count=$(
  psql "$TARGET_POSTGRES_DSN" \
    --no-psqlrc \
    --tuples-only \
    --no-align \
    --set=ON_ERROR_STOP=1 \
    --command="SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public';"
)
if [ "$table_count" != "0" ]; then
  printf 'Target database is not empty (%s public tables)\n' "$table_count" >&2
  exit 2
fi

pg_restore \
  --dbname="$TARGET_POSTGRES_DSN" \
  --exit-on-error \
  --no-owner \
  --no-acl \
  "$BACKUP_FILE"

psql "$TARGET_POSTGRES_DSN" \
  --no-psqlrc \
  --set=ON_ERROR_STOP=1 \
  --command="SELECT count(*) AS pricing_runs FROM pricing_runs;" \
  --command="SELECT count(*) AS recommendations FROM pricing_recommendations;" \
  --command="SELECT count(*) AS raw_captures FROM raw_market_captures;"
