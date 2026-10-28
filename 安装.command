#!/bin/zsh
# 从源码安装（DIY）：双击这个文件，或在终端运行  zsh 安装.command
# 做的事：构建网页 → 编译 App → 装进「应用程序」→ 打开（第一次打开会弹出设置向导）。重复运行就是更新。
# 前提：Xcode 命令行工具（没装会自动弹出安装窗口，装完再双击一次）、Node.js 18+。
# 只想用、不想编译：直接下载做好的 .dmg，打开后把「实时看板」拖进「应用程序」。
set -euo pipefail
cd "${0:A:h}"
[[ "$(uname)" == Darwin ]] || { print "只能在 Mac 上运行"; exit 1; }
bash scripts/build-app.sh
DEST=/Applications/LiveBoard.app
[[ -w /Applications ]] || DEST="$HOME/Applications/LiveBoard.app"
pkill -x LiveBoard 2>/dev/null || true
mkdir -p "${DEST:h}"; rm -rf "$DEST"; ditto dist/LiveBoard.app "$DEST"
print -P "%F{green}▸%f 已安装：$DEST"
open "$DEST"
print -P "%F{green}▸%f 完成：菜单栏右上角的小立方体就是实时看板。第一次打开会弹出设置窗口，按提示做三步。"
