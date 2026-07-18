#!/bin/sh
set -eu

: "${POSTGRES_DSN:?POSTGRES_DSN is required}"

BACKUP_DIR=${BACKUP_DIR:-./backups}
timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
backup_path="${BACKUP_DIR}/marko-${timestamp}.dump"
temporary_path="${backup_path}.partial"

umask 077
mkdir -p "$BACKUP_DIR"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

pg_dump \
  --dbname="$POSTGRES_DSN" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-acl \
  --file="$temporary_path"

pg_restore --list "$temporary_path" >/dev/null
mv "$temporary_path" "$backup_path"

if command -v sha256sum >/dev/null 2>&1; then
  (
    cd "$BACKUP_DIR"
    sha256sum "$(basename "$backup_path")" >"$(basename "$backup_path").sha256"
  )
else
  (
    cd "$BACKUP_DIR"
    shasum -a 256 "$(basename "$backup_path")" >"$(basename "$backup_path").sha256"
  )
fi

trap - EXIT HUP INT TERM
printf '%s\n' "$backup_path"
