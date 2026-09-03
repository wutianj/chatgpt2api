#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
BACKUP_DIR="${1:?usage: rollback-codex-2k-routing.sh BACKUP_DIR}"

[[ -f "${BACKUP_DIR}/conversation.py" ]] || {
  echo "conversation.py backup not found: ${BACKUP_DIR}" >&2
  exit 1
}

docker cp "${BACKUP_DIR}/conversation.py" "${CONTAINER_NAME}:/app/services/protocol/conversation.py" >/dev/null
docker restart "${CONTAINER_NAME}" >/dev/null

for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
  [[ "${health}" == "healthy" ]] && break
  sleep 2
done

[[ "$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")" == "healthy" ]]
printf 'rolled back %s\n' "${BACKUP_DIR}"
