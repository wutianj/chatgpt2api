#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
BUNDLE_DIR="${BUNDLE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
STAMP="${STAMP:-$(date +%Y%m%d-%H%M%S)}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups/reg2-import-${STAMP}}"
CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
APP_DIR="$(cd "${APP_DIR}" && pwd)"

require_file() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    echo "missing required path: ${path}" >&2
    exit 2
  fi
}

require_file "${BUNDLE_DIR}/api/accounts.py"
require_file "${BUNDLE_DIR}/web_dist/index.html"
require_file "${BUNDLE_DIR}/docs/runbooks/reg2-account-import.md"
require_file "${BUNDLE_DIR}/CHANGELOG.md"
require_file "${BUNDLE_DIR}/manifest.json"

python3 - "${BUNDLE_DIR}" <<'PY'
import hashlib
import json
import pathlib
import sys

bundle_dir = pathlib.Path(sys.argv[1]).resolve()
manifest_path = bundle_dir / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
if manifest.get("name") != "reg2-import-bundle":
    raise SystemExit("manifest name is invalid")
for item in manifest.get("files") or []:
    relative_path = str(item.get("path") or "").strip()
    expected_hash = str(item.get("sha256") or "").strip().upper()
    if not relative_path or not expected_hash:
        raise SystemExit("manifest contains invalid file entry")
    target = (bundle_dir / relative_path).resolve()
    if not str(target).startswith(str(bundle_dir) + "/") and target != bundle_dir:
        raise SystemExit(f"manifest path escapes bundle: {relative_path}")
    if not target.is_file():
        raise SystemExit(f"manifest file missing: {relative_path}")
    actual_hash = hashlib.sha256(target.read_bytes()).hexdigest().upper()
    if actual_hash != expected_hash:
        raise SystemExit(f"manifest hash mismatch: {relative_path}")
print("manifest ok")
PY

if ! grep -R "导入 reg2" "${BUNDLE_DIR}/web_dist" >/dev/null 2>&1; then
  echo "bundle web_dist does not contain reg2 import UI text" >&2
  exit 2
fi
if ! grep -R "/api/accounts/import/reg2" "${BUNDLE_DIR}/web_dist" >/dev/null 2>&1; then
  echo "bundle web_dist does not contain reg2 import API client" >&2
  exit 2
fi

mkdir -p "${BACKUP_DIR}/api" "${BACKUP_DIR}/web_dist" "${BACKUP_DIR}/docs/runbooks"

if [[ -f "${APP_DIR}/api/accounts.py" ]]; then
  cp -a "${APP_DIR}/api/accounts.py" "${BACKUP_DIR}/api/accounts.py"
fi
if [[ -f "${APP_DIR}/CHANGELOG.md" ]]; then
  cp -a "${APP_DIR}/CHANGELOG.md" "${BACKUP_DIR}/CHANGELOG.md"
fi
if [[ -d "${APP_DIR}/web_dist" ]]; then
  cp -a "${APP_DIR}/web_dist/." "${BACKUP_DIR}/web_dist/"
fi
if [[ -f "${APP_DIR}/docs/runbooks/reg2-account-import.md" ]]; then
  cp -a "${APP_DIR}/docs/runbooks/reg2-account-import.md" "${BACKUP_DIR}/docs/runbooks/reg2-account-import.md"
fi

install -m 644 "${BUNDLE_DIR}/api/accounts.py" "${APP_DIR}/api/accounts.py"
install -m 644 "${BUNDLE_DIR}/CHANGELOG.md" "${APP_DIR}/CHANGELOG.md"
mkdir -p "${APP_DIR}/web_dist" "${APP_DIR}/docs/runbooks"
cp -a "${BUNDLE_DIR}/web_dist/." "${APP_DIR}/web_dist/"
install -m 644 "${BUNDLE_DIR}/docs/runbooks/reg2-account-import.md" "${APP_DIR}/docs/runbooks/reg2-account-import.md"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  mkdir -p "${BACKUP_DIR}/container"
  docker cp "${CONTAINER_NAME}:/app/api/accounts.py" "${BACKUP_DIR}/container/accounts.py" 2>/dev/null || true
  docker cp "${CONTAINER_NAME}:/app/web_dist" "${BACKUP_DIR}/container/web_dist" 2>/dev/null || true
  docker cp "${BUNDLE_DIR}/api/accounts.py" "${CONTAINER_NAME}:/app/api/accounts.py"
  tmp_web_tar="/tmp/reg2-import-web-dist-${STAMP}.tar"
  tar -C "${BUNDLE_DIR}/web_dist" -cf "${tmp_web_tar}" .
  docker exec "${CONTAINER_NAME}" sh -lc "mkdir -p /app/web_dist && rm -rf /app/web_dist/*"
  docker cp "${tmp_web_tar}" "${CONTAINER_NAME}:/tmp/reg2-import-web-dist.tar"
  rm -f "${tmp_web_tar}"
  docker exec "${CONTAINER_NAME}" sh -lc "tar -C /app/web_dist -xf /tmp/reg2-import-web-dist.tar && rm -f /tmp/reg2-import-web-dist.tar"
  docker exec "${CONTAINER_NAME}" python -m py_compile /app/api/accounts.py
  docker restart "${CONTAINER_NAME}" >/dev/null
  for _ in $(seq 1 30); do
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
    if [[ "${health}" == "healthy" || "${health}" == "running" ]]; then
      if curl -fsS http://127.0.0.1:3000/openapi.json | grep -q "/api/accounts/import/reg2"; then
        break
      fi
    fi
    sleep 2
  done
  if ! curl -fsS http://127.0.0.1:3000/openapi.json | grep -q "/api/accounts/import/reg2"; then
    echo "reg2 import route is missing from running service" >&2
    exit 2
  fi
  image_tag="${CONTAINER_NAME}:reg2-import-${STAMP}"
  docker commit "${CONTAINER_NAME}" "${image_tag}" >/dev/null
  echo "reg2 import route ok"
  echo "container image: ${image_tag}"
else
  python -m py_compile "${APP_DIR}/api/accounts.py"
fi

if ! grep -R "导入 reg2" "${APP_DIR}/web_dist" >/dev/null 2>&1; then
  echo "installed web_dist does not contain reg2 import UI text" >&2
  exit 2
fi
if ! grep -R "/api/accounts/import/reg2" "${APP_DIR}/web_dist" >/dev/null 2>&1; then
  echo "installed web_dist does not contain reg2 import API client" >&2
  exit 2
fi

cat > "${BACKUP_DIR}/rollback-reg2-import.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
BACKUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="${CONTAINER_NAME:-chatgpt2api}"
APP_DIR="$(cd "${APP_DIR}" && pwd)"
if [[ -f "${BACKUP_DIR}/api/accounts.py" ]]; then
  install -m 644 "${BACKUP_DIR}/api/accounts.py" "${APP_DIR}/api/accounts.py"
fi
if [[ -f "${BACKUP_DIR}/CHANGELOG.md" ]]; then
  install -m 644 "${BACKUP_DIR}/CHANGELOG.md" "${APP_DIR}/CHANGELOG.md"
else
  rm -f "${APP_DIR}/CHANGELOG.md"
fi
if [[ -d "${BACKUP_DIR}/web_dist" ]]; then
  target_web_dist="${APP_DIR}/web_dist"
  parent_dir="$(dirname "${target_web_dist}")"
  if [[ "$(cd "${parent_dir}" && pwd)" != "${APP_DIR}" ]]; then
    echo "refusing to replace unexpected web_dist path: ${target_web_dist}" >&2
    exit 2
  fi
  rm -rf -- "${target_web_dist}"
  mkdir -p "${target_web_dist}"
  cp -a "${BACKUP_DIR}/web_dist/." "${target_web_dist}/"
fi
if [[ -f "${BACKUP_DIR}/docs/runbooks/reg2-account-import.md" ]]; then
  mkdir -p "${APP_DIR}/docs/runbooks"
  install -m 644 "${BACKUP_DIR}/docs/runbooks/reg2-account-import.md" "${APP_DIR}/docs/runbooks/reg2-account-import.md"
else
  rm -f "${APP_DIR}/docs/runbooks/reg2-account-import.md"
fi
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  if [[ -f "${BACKUP_DIR}/container/accounts.py" ]]; then
    docker cp "${BACKUP_DIR}/container/accounts.py" "${CONTAINER_NAME}:/app/api/accounts.py"
  fi
  if [[ -d "${BACKUP_DIR}/container/web_dist" ]]; then
    tmp_web_tar="/tmp/reg2-import-web-dist-rollback-$(date +%Y%m%d-%H%M%S).tar"
    tar -C "${BACKUP_DIR}/container/web_dist" -cf "${tmp_web_tar}" .
    docker exec "${CONTAINER_NAME}" sh -lc "mkdir -p /app/web_dist && rm -rf /app/web_dist/*"
    docker cp "${tmp_web_tar}" "${CONTAINER_NAME}:/tmp/reg2-import-web-dist-rollback.tar"
    rm -f "${tmp_web_tar}"
    docker exec "${CONTAINER_NAME}" sh -lc "tar -C /app/web_dist -xf /tmp/reg2-import-web-dist-rollback.tar && rm -f /tmp/reg2-import-web-dist-rollback.tar"
  fi
  docker exec "${CONTAINER_NAME}" python -m py_compile /app/api/accounts.py
  docker restart "${CONTAINER_NAME}" >/dev/null
  rollback_image="${CONTAINER_NAME}:rollback-$(date +%Y%m%d-%H%M%S)"
  docker commit "${CONTAINER_NAME}" "${rollback_image}" >/dev/null
  echo "rollback image: ${rollback_image}"
else
  python -m py_compile "${APP_DIR}/api/accounts.py"
fi
echo "rollback completed from ${BACKUP_DIR}"
SH
chmod +x "${BACKUP_DIR}/rollback-reg2-import.sh"

echo "applied reg2 import bundle"
echo "backup: ${BACKUP_DIR}"
echo "rollback: ${BACKUP_DIR}/rollback-reg2-import.sh"
