#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
RETENTION_COUNT="${BACKUP_RETENTION_COUNT:-7}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK_DIR="$(mktemp -d)"
ARCHIVE="${BACKUP_DIR}/chatgpt2api-${STAMP}.tar.gz"

cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

mkdir -p "${BACKUP_DIR}"
mkdir -p "${WORK_DIR}/app-data" "${WORK_DIR}/config" "${WORK_DIR}/runtime"

if [[ -n "${DATABASE_URL:-}" && "${DATABASE_URL}" == postgresql* ]]; then
  command -v pg_dump >/dev/null 2>&1 || { echo "pg_dump is required for PostgreSQL backups" >&2; exit 1; }
  pg_dump --format=custom --no-owner --no-privileges "${DATABASE_URL}" > "${WORK_DIR}/app-data/application-database.pgdump"
else
  DB_PATH="${DATABASE_PATH:-${APP_DIR}/data/chatgpt2api.db}"
  [[ -f "${DB_PATH}" ]] || { echo "SQLite database not found: ${DB_PATH}" >&2; exit 1; }
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "${DB_PATH}" ".backup '${WORK_DIR}/app-data/application-database.sqlite3'"
  else
    cp --reflink=auto "${DB_PATH}" "${WORK_DIR}/app-data/application-database.sqlite3"
  fi
fi

if [[ -d "${APP_DIR}/data" ]]; then
  tar -C "${APP_DIR}" \
    --exclude=data/chatgpt2api.db \
    --exclude=data/application-database.sqlite3 \
    --exclude=data/application-database.pgdump \
    -cf - data | tar -C "${WORK_DIR}/app-data" -xf -
fi
for path in config.json .env; do
  if [[ -f "${APP_DIR}/${path}" ]]; then
    cp -a "${APP_DIR}/${path}" "${WORK_DIR}/config/${path}"
  fi
done
if [[ -f "${CADDYFILE}" ]]; then
  cp -a "${CADDYFILE}" "${WORK_DIR}/config/Caddyfile"
fi
if [[ -f "${APP_DIR}/VERSION" ]]; then
  cp -a "${APP_DIR}/VERSION" "${WORK_DIR}/runtime/VERSION"
fi

tar -C "${WORK_DIR}" -czf "${ARCHIVE}" app-data config runtime
chmod 600 "${ARCHIVE}"
sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"
chmod 600 "${ARCHIVE}.sha256"

if [[ "${RETENTION_COUNT}" =~ ^[1-9][0-9]*$ ]]; then
  mapfile -t stale_archives < <(
    find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'chatgpt2api-*.tar.gz' -printf '%T@ %p\n' |
      sort -nr |
      tail -n +$((RETENTION_COUNT + 1)) |
      cut -d' ' -f2-
  )
  for stale_archive in "${stale_archives[@]}"; do
    rm -f -- "${stale_archive}" "${stale_archive}.sha256"
  done
fi

printf 'created %s\n' "${ARCHIVE}"
