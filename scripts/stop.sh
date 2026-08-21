#!/usr/bin/env bash
set -euo pipefail
ROOMS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --room) ROOMS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
for room in "${ROOMS[@]}"; do
  dmnotifier stop "$room" || true
done
pkill -f "bilidm-overlay" || true
