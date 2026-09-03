#!/usr/bin/env bash
set -euo pipefail

CONTAINER="chatgpt2api"
OLD_CONTAINER="chatgpt2api-previous-gemini-unified-20260829T1933"

docker inspect "${OLD_CONTAINER}" >/dev/null
docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker rename "${OLD_CONTAINER}" "${CONTAINER}"
docker start "${CONTAINER}" >/dev/null
printf 'rolled back to %s\n' "$(docker inspect -f '{{.Config.Image}}' "${CONTAINER}")"
