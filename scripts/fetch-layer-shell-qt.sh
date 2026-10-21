#!/usr/bin/env bash
# 取回与本 venv 的 Qt 同 ABI 的 layer-shell-qt,存进缓存目录供 overlay 预载。
#
# 为什么要这一步:系统 layer-shell-qt 自 6.8.0 起用 Qt 6.12 编译,而 PyQt6 的 wheel
# 自带 Qt 6.11 —— libkoto-layer.so dlopen 时命中的是系统那份,直接报
# "version `Qt_6.12' not found"。overlay 于是失去 layer-shell 能力,窗口退化成
# 合成器排布的普通顶层窗:不能拖动、不能穿透、不能定位。
#
# 用法:
#   scripts/fetch-layer-shell-qt.sh              # 自动选与 venv Qt 同 ABI 的版本
#   scripts/fetch-layer-shell-qt.sh 6.7.5-1      # 指定版本
#   scripts/fetch-layer-shell-qt.sh --print-pkg  # 只打印需要的包版本
#   scripts/fetch-layer-shell-qt.sh --ensure     # 已经有了就什么都不做(start.sh 用)
#
# 取回的库落在 ${XDG_CACHE_HOME:-~/.cache}/bilidm-overlay/layer-shell-qt/,
# overlay 启动时自己预载,不安装到系统、不需要 root。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# HOME 可能没导出(定时任务、systemd --user 单元):从 passwd 兜底,别让 set -u 直接炸。
HOME_DIR="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME_DIR/.cache}/bilidm-overlay/layer-shell-qt"
ARCHIVE_URL="https://archive.archlinux.org/packages/l/layer-shell-qt"
PKG_REPO="https://archlinux.org/packages/extra/x86_64/layer-shell-qt/json/"

log() { printf '%s\n' "$*" >&2; }

venv_qt_minor() {
  "$ROOT/.venv/bin/python" - <<'PY'
from PyQt6.QtCore import QT_VERSION_STR
print(".".join(QT_VERSION_STR.split(".")[:2]))
PY
}

# 兼容库的包版本:归档里最接近、但 ABI 不高于 venv Qt 的那一版。
# 这里用一个显式对照表,而不是去解析归档目录:需要的只是"哪一版用哪个 Qt 编的",
# 那是一次性的历史事实,查表比每次抓 HTML 更稳,也不会因为归档改版而静默选错。
pkg_for_qt() {
  case "$1" in
    6.11) echo "6.7.5-1" ;;   # 6.7.5-1: Qt 6.11;6.7.5-3 起改用 Qt 6.12
    6.12) echo "6.8.0-1" ;;
    *)    echo "" ;;
  esac
}

QT_MINOR="$(venv_qt_minor)"
log "venv Qt: $QT_MINOR"

if [[ "${1:-}" == "--print-pkg" ]]; then
  pkg_for_qt "$QT_MINOR"
  exit 0
fi

ENSURE=0
if [[ "${1:-}" == "--ensure" ]]; then
  ENSURE=1
  shift
fi

PKG_VERSION="${1:-$(pkg_for_qt "$QT_MINOR")}"
if [[ -z "$PKG_VERSION" ]]; then
  log "没有为 Qt $QT_MINOR 登记的兼容 layer-shell-qt 版本。"
  log "可用的对照:6.11 -> 6.7.5-1、6.12 -> 6.8.0-1;其它情况请手动指定版本参数。"
  exit 1
fi
log "目标包: layer-shell-qt $PKG_VERSION"

# 已缓存就不再下载:判据是"目录里有任意一份带 ABI 后缀的库",而不是拿包版本号去
# 拼文件名——包的 6.7.5-1 是打包版本,库的 6.7.5 是 soname 版本,两者永远拼不上。
if [[ "$ENSURE" == "1" ]]; then
  # `|| true`:目录还不存在时 find 非零退出,配合 pipefail + set -e 会直接终止脚本。
  existing="$(find "$CACHE_DIR" -maxdepth 1 -name 'libLayerShellQtInterface.so.6.*' -type f 2>/dev/null | head -n 1 || true)"
  if [[ -n "$existing" ]]; then
    log "已缓存 $existing,跳过"
    exit 0
  fi
fi

mkdir -p "$CACHE_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PKG_FILE="$TMP_DIR/layer-shell-qt.pkg.tar.zst"
log "下载 $ARCHIVE_URL/layer-shell-qt-$PKG_VERSION-x86_64.pkg.tar.zst"
curl -fsSL -o "$PKG_FILE" "$ARCHIVE_URL/layer-shell-qt-$PKG_VERSION-x86_64.pkg.tar.zst"

# 只取 .so,且只取真实文件:不落软链接——软链接在别的目录里指不到目标。
log "解出库文件到 $CACHE_DIR"
tar -I zstd -xf "$PKG_FILE" -C "$TMP_DIR" --wildcards 'usr/lib/libLayerShellQtInterface.so.6.*'
cp -f "$TMP_DIR"/usr/lib/libLayerShellQtInterface.so.6.* "$CACHE_DIR"/
chmod 644 "$CACHE_DIR"/libLayerShellQtInterface.so.6.*

ls -l "$CACHE_DIR" >&2
log "完成。overlay 下次启动会自动预载它(可用 BILIDM_LAYER_SHELL_QT 指向别的目录)。"
