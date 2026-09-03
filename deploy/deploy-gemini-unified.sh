#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:?usage: deploy-gemini-unified.sh IMAGE ENV_FILE}"
ENV_FILE="${2:?usage: deploy-gemini-unified.sh IMAGE ENV_FILE}"
APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
CONTAINER="chatgpt2api"
OLD_CONTAINER="chatgpt2api-previous-gemini-unified-20260829T1933"
rollback_needed=1

rollback() {
  if [[ "${rollback_needed}" -ne 1 ]]; then
    return
  fi
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker rename "${OLD_CONTAINER}" "${CONTAINER}" >/dev/null 2>&1 || true
  docker start "${CONTAINER}" >/dev/null 2>&1 || true
}
trap rollback EXIT

docker inspect "${CONTAINER}" >/dev/null
docker rm -f "${OLD_CONTAINER}" >/dev/null 2>&1 || true
docker stop "${CONTAINER}" >/dev/null
docker rename "${CONTAINER}" "${OLD_CONTAINER}"

docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  --env-file "${ENV_FILE}" \
  --health-cmd='python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:80/version\", timeout=3)"' \
  --health-interval=30s \
  --health-timeout=5s \
  --health-retries=3 \
  --health-start-period=30s \
  -p 127.0.0.1:3000:80 \
  -v "${APP_DIR}/data:/app/data" \
  -v "${APP_DIR}/config.json:/app/config.json:ro" \
  "${IMAGE}" \
  uv run uvicorn main:app --host 0.0.0.0 --port 80 --access-log >/dev/null

for _ in $(seq 1 45); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}starting{{end}}' "${CONTAINER}" 2>/dev/null || true)"
  if [[ "${status}" == "healthy" ]]; then
    rollback_needed=0
    printf 'deployed %s; old container %s retained\n' "${IMAGE}" "${OLD_CONTAINER}"
    exit 0
  fi
  if [[ "${status}" == "unhealthy" || "${status}" == "" ]]; then
    docker logs --tail 80 "${CONTAINER}" >&2 || true
    exit 1
  fi
  sleep 2
done

docker logs --tail 80 "${CONTAINER}" >&2 || true
exit 1
