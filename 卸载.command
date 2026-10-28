#!/bin/zsh
# 卸载实时看板：退出 App、取消登录时自动打开、删掉 App 和这台 Mac 上存的密钥与设置。Notion 里的表不会动。
# Uninstall Live Board: quit the app, turn off Open at Login, and delete the app plus the token and settings stored on this Mac. Your Notion table is left untouched.
APP_BIN=LiveBoard
APPS=(/Applications/实时看板.app "$HOME/Applications/实时看板.app" /Applications/LiveBoard.app "$HOME/Applications/LiveBoard.app")
for d in "${APPS[@]}"; do
  [[ -d "$d" ]] && "$d/Contents/MacOS/$APP_BIN" --unregister-login 2>/dev/null &
done
sleep 1; pkill -x "$APP_BIN" 2>/dev/null
rm -rf "${APPS[@]}" "$HOME/Library/Application Support/LiveBoard"
defaults delete io.github.lunafantasylab.liveboard 2>/dev/null   # 语言等偏好 / preferences such as the language choice
echo "已卸载（如果「系统设置 → 通用 → 登录项」里还留着「实时看板」，点减号删掉即可）"
echo "Uninstalled. If “Live Board” is still listed in System Settings → General → Login Items, remove it with the minus button."
