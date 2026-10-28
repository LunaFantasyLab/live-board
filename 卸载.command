#!/bin/zsh
# 卸载实时看板：退出 App、取消登录时自动打开、删掉 App 和这台 Mac 上存的密钥与设置。Notion 里的表不会动。
APP_BIN=LiveBoard
for d in /Applications/LiveBoard.app "$HOME/Applications/LiveBoard.app"; do
  [[ -d "$d" ]] && "$d/Contents/MacOS/$APP_BIN" --unregister-login 2>/dev/null &
done
sleep 1; pkill -x "$APP_BIN" 2>/dev/null
rm -rf /Applications/LiveBoard.app "$HOME/Applications/LiveBoard.app" "$HOME/Library/Application Support/LiveBoard"
echo "已卸载（如果「系统设置 → 通用 → 登录项」里还留着「实时看板」，点减号删掉即可）"
