#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
BUNDLE="${1:?usage: apply-portal-runtime.sh BUNDLE.tar.gz}"
[[ -f "${BUNDLE}" ]] || { echo "runtime bundle not found: ${BUNDLE}" >&2; exit 1; }

RUNTIME_PATHS=(
  api/accounts.py
  api/admin_portal.py
  api/ai.py
  api/billing.py
  api/image_tasks.py
  contracts/admin_portal.py
  contracts/portal.py
  services/config.py
  services/image_task_service.py
  services/image_task_view.py
  services/portal_billing.py
  services/protocol/conversation.py
  services/protocol/openai_v1_chat_complete.py
  services/protocol/openai_v1_response.py
  services/storage/portal_repository.py
)

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIR}"
  rm -rf /tmp/portal-runtime-backup-*
}
trap cleanup EXIT
tar -tzf "${BUNDLE}" >/dev/null
tar -C "${WORK_DIR}" -xzf "${BUNDLE}"
for path in "${RUNTIME_PATHS[@]}"; do
  [[ -f "${WORK_DIR}/${path}" ]] || {
    echo "bundle runtime file is missing: ${path}" >&2
    exit 1
  }
done

for path in "${RUNTIME_PATHS[@]}"; do
  docker cp "${CONTAINER_NAME}:/app/${path}" "/tmp/portal-runtime-backup-${path//\//-}" >/dev/null
done
docker cp "${CONTAINER_NAME}:/app/web_dist" /tmp/portal-runtime-backup-web_dist >/dev/null

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${APP_DIR}/backups/portal-runtime-${STAMP}"
mkdir -p "${BACKUP_DIR}/container" "${BACKUP_DIR}/host"
for path in "${RUNTIME_PATHS[@]}"; do
  mkdir -p "${BACKUP_DIR}/container/$(dirname "${path}")" "${BACKUP_DIR}/host/$(dirname "${path}")"
  cp -a "/tmp/portal-runtime-backup-${path//\//-}" "${BACKUP_DIR}/container/${path}"
  if [[ -f "${APP_DIR}/${path}" ]]; then
    cp -a "${APP_DIR}/${path}" "${BACKUP_DIR}/host/${path}"
  else
    touch "${BACKUP_DIR}/host/${path}.missing"
  fi
done
cp -a /tmp/portal-runtime-backup-web_dist "${BACKUP_DIR}/container/web_dist"
if [[ -d "${APP_DIR}/web_dist" ]]; then
  cp -a "${APP_DIR}/web_dist" "${BACKUP_DIR}/host/web_dist"
fi
docker inspect --format '{{.Name}} {{.Config.Image}} {{.State.Status}} {{.State.Health.Status}}' "${CONTAINER_NAME}" > "${BACKUP_DIR}/container.txt"
printf '%s\n' "${RUNTIME_PATHS[@]}" > "${BACKUP_DIR}/runtime-paths.txt"

for path in "${RUNTIME_PATHS[@]}"; do
  mkdir -p "${APP_DIR}/$(dirname "${path}")"
  cp -a "${WORK_DIR}/${path}" "${APP_DIR}/${path}"
  docker cp "${WORK_DIR}/${path}" "${CONTAINER_NAME}:/app/${path}" >/dev/null
done
rm -rf "${APP_DIR}/web_dist"
mkdir -p "${APP_DIR}/web_dist"
cp -a "${WORK_DIR}/web_dist/." "${APP_DIR}/web_dist/"
docker exec "${CONTAINER_NAME}" sh -lc 'rm -rf /app/web_dist/*'
docker cp "${WORK_DIR}/web_dist/." "${CONTAINER_NAME}:/app/web_dist/" >/dev/null
docker restart "${CONTAINER_NAME}" >/dev/null

for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
  [[ "${health}" == "healthy" ]] && break
  sleep 2
done
health="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
[[ "${health}" == "healthy" ]] || { echo "container did not become healthy: ${health}" >&2; exit 1; }

cat > "${BACKUP_DIR}/rollback-portal-runtime.sh" <<'ROLLBACK'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
BACKUP_DIR="${1:?usage: rollback-portal-runtime.sh BACKUP_DIR}"
[[ -f "${BACKUP_DIR}/runtime-paths.txt" ]] || { echo "runtime backup not found" >&2; exit 1; }
mapfile -t RUNTIME_PATHS < "${BACKUP_DIR}/runtime-paths.txt"
docker stop "${CONTAINER_NAME}" >/dev/null
for path in "${RUNTIME_PATHS[@]}"; do
  mkdir -p "${APP_DIR}/$(dirname "${path}")"
  if [[ -f "${BACKUP_DIR}/host/${path}.missing" ]]; then
    rm -f "${APP_DIR}/${path}"
  else
    cp -a "${BACKUP_DIR}/host/${path}" "${APP_DIR}/${path}"
  fi
  docker cp "${BACKUP_DIR}/container/${path}" "${CONTAINER_NAME}:/app/${path}" >/dev/null
done
if [[ -d "${BACKUP_DIR}/host/web_dist" ]]; then
  rm -rf "${APP_DIR}/web_dist"
  cp -a "${BACKUP_DIR}/host/web_dist" "${APP_DIR}/web_dist"
fi
docker exec "${CONTAINER_NAME}" sh -lc 'rm -rf /app/web_dist/*'
docker cp "${BACKUP_DIR}/container/web_dist/." "${CONTAINER_NAME}:/app/web_dist/" >/dev/null
docker start "${CONTAINER_NAME}" >/dev/null
for _ in $(seq 1 60); do
  health="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
  [[ "${health}" == "healthy" ]] && break
  sleep 2
done
[[ "$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")" == "healthy" ]]
printf 'rolled back %s\n' "${BACKUP_DIR}"
ROLLBACK
chmod 700 "${BACKUP_DIR}/rollback-portal-runtime.sh"
printf 'backup %s\n' "${BACKUP_DIR}"
printf 'rollback %s\n' "${BACKUP_DIR}/rollback-portal-runtime.sh"
