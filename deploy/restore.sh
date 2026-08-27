#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
COMPOSE_FILE="${COMPOSE_FILE:-${APP_DIR}/docker-compose.prod.yml}"
ARCHIVE="${1:?usage: restore.sh BACKUP.tar.gz [--apply]}"
APPLY="${2:-}"
DATABASE_URL="${DATABASE_URL:-}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
[[ -f "${ARCHIVE}" ]] || { echo "backup archive not found: ${ARCHIVE}" >&2; exit 1; }

if [[ -f "${ARCHIVE}.sha256" ]]; then
  sha256sum --check "${ARCHIVE}.sha256"
fi

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT
tar -tzf "${ARCHIVE}" >/dev/null
tar -C "${WORK_DIR}" -xzf "${ARCHIVE}"
[[ -f "${WORK_DIR}/app-data/application-database.sqlite3" || -f "${WORK_DIR}/app-data/application-database.pgdump" ]] || {
  echo "backup does not contain an application database" >&2
  exit 1
}

if [[ "${APPLY}" != "--apply" ]]; then
  printf 'validated %s; rerun with --apply to restore\n' "${ARCHIVE}"
  exit 0
fi

command -v docker >/dev/null 2>&1 && docker compose -f "${COMPOSE_FILE}" stop app >/dev/null 2>&1 || true
mkdir -p "${APP_DIR}/data"
if [[ -f "${WORK_DIR}/app-data/application-database.pgdump" ]]; then
  [[ -n "${DATABASE_URL}" ]] || { echo "DATABASE_URL is required to restore PostgreSQL" >&2; exit 1; }
  command -v pg_restore >/dev/null 2>&1 || { echo "pg_restore is required for PostgreSQL restores" >&2; exit 1; }
  pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "${DATABASE_URL}" "${WORK_DIR}/app-data/application-database.pgdump"
fi
if [[ -d "${WORK_DIR}/app-data/data" ]]; then
  mkdir -p "${APP_DIR}/data.restoring"
  cp -a "${WORK_DIR}/app-data/data/." "${APP_DIR}/data.restoring/"
  rm -rf "${APP_DIR}/data.before-restore"
  if [[ -d "${APP_DIR}/data" ]]; then
    mv "${APP_DIR}/data" "${APP_DIR}/data.before-restore"
  fi
  mv "${APP_DIR}/data.restoring" "${APP_DIR}/data"
fi
if [[ -f "${WORK_DIR}/app-data/application-database.sqlite3" ]]; then
  install -m 600 "${WORK_DIR}/app-data/application-database.sqlite3" "${APP_DIR}/data/chatgpt2api.db"
fi
for path in config.json .env; do
  if [[ -f "${WORK_DIR}/config/${path}" ]]; then
    install -m 600 "${WORK_DIR}/config/${path}" "${APP_DIR}/${path}"
  fi
done
if [[ -f "${WORK_DIR}/config/Caddyfile" ]]; then
  mkdir -p "$(dirname "${CADDYFILE}")"
  install -m 600 "${WORK_DIR}/config/Caddyfile" "${CADDYFILE}"
fi
printf 'restored %s; start the application and verify /, /admin, and /v1/models\n' "${ARCHIVE}"
