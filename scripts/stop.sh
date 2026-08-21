#!/usr/bin/env bash
# 停止:UniBarrage 监听 + 杀掉 overlay(与 start.sh 同源解析 dmnotifier 二进制)。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 优先用仓库内构建的 dmnotifier 二进制;否则找 PATH 里的
DMNOTIFIER_BIN="${DMNOTIFIER_BIN:-}"
if [[ -z "$DMNOTIFIER_BIN" ]]; then
  if [[ -x "$ROOT/../dmnotifier/dmnotifier" ]]; then
    DMNOTIFIER_BIN="$ROOT/../dmnotifier/dmnotifier"
  else
    DMNOTIFIER_BIN="$(command -v dmnotifier || echo dmnotifier)"
  fi
fi
ROOMS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --room)
      if [[ $# -lt 2 ]]; then
        echo "错误: --room 需要一个参数(格式 platform:rid[:cookie])" >&2
        exit 1
      fi
      ROOMS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
for room in "${ROOMS[@]}"; do
  "$DMNOTIFIER_BIN" stop "$room" || true
done
pkill -f "bilidm-overlay" || true
