#!/usr/bin/env bash
# 一键拉起:检查 UniBarrage → dmnotifier start(注册监听) → dmnotifier run(无头管道) → overlay。
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
    --room)
      if [[ $# -lt 2 ]]; then
        echo "错误: --room 需要一个参数(格式 platform:rid[:cookie])" >&2
        exit 1
      fi
      ROOM_ARGS+=("$2"); shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if ! ss -tln 2>/dev/null | grep -q ':7777 '; then
  echo "UniBarrage 未监听 127.0.0.1:7777,请先启动它(见 UniBarrage 仓库 readme)。" >&2
  exit 1
fi

for room in "${ROOM_ARGS[@]}"; do
  if ! "$DMNOTIFIER_BIN" start "$room"; then
    echo "警告: 订阅请求可能失败(详见上游日志): $room" >&2
  fi
  echo "已请求订阅 $room"
done

# 无头管道进程:把弹幕经 float 插件推给 overlay(日志走 stderr,stdout 保持干净)。
# 必须在 `dmnotifier start` 之后启动:`start` 把房间写入 config history,
# `run` 再按 history 逐个订阅(start 与 run 为顺序执行,history 已落盘)。
"$DMNOTIFIER_BIN" run &
RUN_PID=$!
trap 'if [[ -n "${RUN_PID:-}" ]]; then kill "$RUN_PID" 2>/dev/null || true; fi' EXIT
sleep 0.3
if ! kill -0 "$RUN_PID" 2>/dev/null; then
  echo "错误: dmnotifier run 启动失败,该二进制可能不含 run 子命令(用 DMNOTIFIER_BIN 指向新构建)。" >&2
  exit 1
fi

# 组装 --room 参数,透传给 overlay(房间分组/标签由 overlay 配置决定)
OVERLAY_ARGS=()
for room in "${ROOM_ARGS[@]}"; do
  OVERLAY_ARGS+=(--room "$room")
done

uv run --project "$ROOT" bilidm-overlay "${OVERLAY_ARGS[@]}" &
OVERLAY_PID=$!
echo "overlay pid: $OVERLAY_PID"
wait "$OVERLAY_PID"
