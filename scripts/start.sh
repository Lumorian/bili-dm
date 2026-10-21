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
# 幂等防护:同一条 run 管道已在跑时不重复拉起(重复拉起会弹幕双份);上次 chain 被
# kill 掉没走到 EXIT trap 时残留的孤单 run 也会被 pgrep 检出,后续 start.sh 直接跳过。
RUN_PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/bilidm-dmnotifier-run.pid"
if command -v pgrep >/dev/null 2>&1; then
  RUN_ALIVE() { pgrep -f "${DMNOTIFIER_BIN} run" >/dev/null 2>&1; }
else
  # pgrep 不可用(非 procps 系统):回退到 PID 文件探测。
  RUN_ALIVE() {
    [[ -f "$RUN_PIDFILE" ]] || return 1
    local pid
    pid="$(cat "$RUN_PIDFILE" 2>/dev/null || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
  }
fi
if RUN_ALIVE; then
  echo "dmnotifier run 已在运行,跳过"
else
  "$DMNOTIFIER_BIN" run &
  RUN_PID=$!
  echo "$RUN_PID" > "$RUN_PIDFILE"
fi
trap 'if [[ -n "${RUN_PID:-}" ]]; then kill "$RUN_PID" 2>/dev/null || true; rm -f "$RUN_PIDFILE"; fi' EXIT
if [[ -n "${RUN_PID:-}" ]]; then
  sleep 0.3
  if ! kill -0 "$RUN_PID" 2>/dev/null; then
    echo "错误: dmnotifier run 启动失败,该二进制可能不含 run 子命令(用 DMNOTIFIER_BIN 指向新构建)。" >&2
    exit 1
  fi
fi

# layer-shell 桥需要与 venv 里那份 Qt 同 ABI 的 layer-shell-qt:系统包跟着系统 Qt 走,
# 而 PyQt6 的 wheel 固定自带一版,两者一大版本一错开,桥就 dlopen 失败——窗口会退化成
# 普通顶层窗(不能拖动、不穿透、不定位)。这里缺就补一次;补不上不阻塞启动,
# overlay 自己会报明原因。
if ! "$ROOT/scripts/fetch-layer-shell-qt.sh" --ensure; then
  echo "警告: 未能取回 ABI 兼容的 layer-shell-qt,悬浮窗可能无法拖动(见 overlay/README 的排错一节)。" >&2
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
