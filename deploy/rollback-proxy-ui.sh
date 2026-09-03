#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
BACKUP_DIR="${1:?usage: rollback-proxy-ui.sh BACKUP_DIR}"

[[ -d "${BACKUP_DIR}/web_dist" ]] || {
  echo "web UI backup not found: ${BACKUP_DIR}" >&2
  exit 1
}

docker exec "${CONTAINER_NAME}" sh -lc 'rm -rf /app/web_dist/*'
docker cp "${BACKUP_DIR}/web_dist/." "${CONTAINER_NAME}:/app/web_dist/" >/dev/null
docker restart "${CONTAINER_NAME}" >/dev/null

for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
  [[ "${health}" == "healthy" ]] && break
  sleep 2
done

[[ "$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")" == "healthy" ]]
printf 'rolled back %s\n' "${BACKUP_DIR}"
