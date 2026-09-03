#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/chatgpt2api}"
THRESHOLD_PERCENT="${DISK_ALERT_THRESHOLD_PERCENT:-80}"

used_percent="$(df --output=pcent "${APP_DIR}" | tail -n 1 | tr -dc '0-9')"
if [[ -z "${used_percent}" ]]; then
  logger -p daemon.err -t chatgpt2api-disk-alert "无法读取 ${APP_DIR} 的磁盘占用"
  exit 0
fi

if (( used_percent >= THRESHOLD_PERCENT )); then
  logger -p daemon.warning -t chatgpt2api-disk-alert \
    "磁盘占用 ${used_percent}%，已达到阈值 ${THRESHOLD_PERCENT}%，请检查 ${APP_DIR}"
else
  logger -p daemon.info -t chatgpt2api-disk-alert \
    "磁盘占用 ${used_percent}%，阈值 ${THRESHOLD_PERCENT}%"
fi
