#!/usr/bin/env bash
# 一键拉起:检查 UniBarrage → dmnotifier start → overlay。
# 用法: scripts/start.sh [--room bilibili:689422[:cookie]]...
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
ROOM_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --room) ROOM_ARGS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if ! ss -tln 2>/dev/null | grep -q ':7777 '; then
  echo "UniBarrage 未监听 127.0.0.1:7777,请先启动它(见 UniBarrage 仓库 readme)。" >&2
  exit 1
fi

for room in "${ROOM_ARGS[@]}"; do
  "$DMNOTIFIER_BIN" start "$room" || true   # 已订阅时跳过
  echo "已请求订阅 $room"
done

# 组装 --room 参数,透传给 overlay(房间分组/标签由 overlay 配置决定)
OVERLAY_ARGS=()
for room in "${ROOM_ARGS[@]}"; do
  OVERLAY_ARGS+=(--room "$room")
done

uv run --project "$ROOT" bilidm-overlay "${OVERLAY_ARGS[@]}" &
OVERLAY_PID=$!
echo "overlay pid: $OVERLAY_PID"
wait "$OVERLAY_PID"
