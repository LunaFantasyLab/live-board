#!/bin/zsh
# 从源码安装（DIY）：双击这个文件，或在终端运行  zsh 安装.command
# Install from source (DIY): double-click this file, or run  zsh 安装.command  in Terminal.
# 做的事：构建网页 → 编译 App → 装进「应用程序」→ 打开（第一次打开会弹出设置向导）。重复运行就是更新。
# What it does: build the web page → compile the app → copy it into Applications → open it (the setup window appears on first launch). Run it again to update.
# 前提 / Needs：Xcode 命令行工具 Command Line Tools（没装会自动弹出安装窗口，装完再双击一次 / an installer pops up if missing; run again afterwards）、Node.js 18+。
# 只想用、不想编译：直接下载做好的 .dmg，打开后把 App 拖进「应用程序」。 / Just want to use it? Download the ready-made .dmg and drag the app into Applications.
set -euo pipefail
cd "${0:A:h}"
[[ "$(uname)" == Darwin ]] || { print "只能在 Mac 上运行 / macOS only"; exit 1; }
bash scripts/build-app.sh
# 文件名和 Info.plist 的 CFBundleDisplayName 一样（实时看板.app），英文系统的访达里才显示 Live Board
DEST=/Applications/实时看板.app
[[ -w /Applications ]] || DEST="$HOME/Applications/实时看板.app"
pkill -x LiveBoard 2>/dev/null || true
rm -rf "${DEST:h}/LiveBoard.app"   # 0.1.x 从源码装的旧文件名 / old file name used by 0.1.x source installs
mkdir -p "${DEST:h}"; rm -rf "$DEST"; ditto dist/LiveBoard.app "$DEST"
print -P "%F{green}▸%f 已安装 / Installed: $DEST"
open "$DEST"
print -P "%F{green}▸%f 完成：菜单栏右上角的小立方体就是实时看板。第一次打开会弹出设置窗口，按提示做三步。"
print -P "%F{green}▸%f Done: the small cube in the menu bar is Live Board. The first launch opens a three-step setup window."
