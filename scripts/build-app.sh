#!/usr/bin/env bash
# 打包 Mac 菜单栏 App。
#   scripts/build-app.sh              在 Mac 上：编译通用二进制（Apple 芯片 + Intel），组装 dist/LiveBoard.app
#   scripts/build-app.sh --dmg        另外做一个 dist/LiveBoard-<版本>.dmg（卷名 Live Board；打开后把图标拖进 Applications / 应用程序 即可安装）
#   scripts/build-app.sh --stage-only 任何系统都能跑：只组装 App 里的网页资源（dist/stage/board），不编译，用来自测
# 环境变量：BUNDLE_ID（默认 io.github.lunafantasylab.liveboard）、VERSION（默认 0.2.0）、BUILD（默认 1）、SKIP_WEB=1（不重新构建网页）
# 前提（Mac）：Xcode 命令行工具（xcode-select --install），Node.js 18+（构建网页用；SKIP_WEB=1 且已有 board/dist 时不需要）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUNDLE_ID="${BUNDLE_ID:-io.github.lunafantasylab.liveboard}"; VERSION="${VERSION:-0.2.0}"; BUILD="${BUILD:-1}"
MODE="${1:-}"
OUT="$ROOT/dist"; STAGE="$OUT/stage"
say() { printf '\033[32m▸\033[0m %s\n' "$*"; }
die() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# 1) 网页
if [[ "${SKIP_WEB:-}" != 1 || ! -f "$ROOT/board/dist/index.html" ]]; then
  command -v npm >/dev/null || die "需要 Node.js（npm）来构建看板网页"
  say "构建看板网页"
  (cd "$ROOT/board" && { [[ -d node_modules ]] || npm ci --no-audit --no-fund; } && npx vite build >/dev/null)
fi
[[ -f "$ROOT/board/dist/index.html" ]] || die "board/dist 不存在"

# 2) 组装网页资源：看板 + relay.js（Notion 中转）+ 设置向导
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$ROOT/board/dist" "$STAGE/board"
cp "$ROOT/app/LiveBoard/web/i18n.js" "$ROOT/app/LiveBoard/web/relay.js" "$ROOT/app/LiveBoard/web/setup.html" "$ROOT/app/LiveBoard/web/setup.js" "$ROOT/app/LiveBoard/web/setup.css" "$STAGE/board/"
python3 - "$STAGE/board/index.html" <<'PY'
import sys; p = sys.argv[1]; s = open(p, encoding="utf-8").read()
tag = '<script src="/i18n.js"></script>\n<script src="/relay.js"></script>\n'   # i18n.js：relay.js 的提示文字（中 / 英）
if 'relay.js' not in s: s = s.replace('<script type="module"', tag + '<script type="module"', 1)
open(p, "w", encoding="utf-8").write(s)
PY
grep -q 'src="/relay.js"' "$STAGE/board/index.html" && grep -q 'src="/i18n.js"' "$STAGE/board/index.html" || die "relay.js / i18n.js 没插进 index.html"
say "网页资源：$STAGE/board"
[[ "$MODE" == "--stage-only" ]] && exit 0

# 3) 编译（只能在 Mac 上）
[[ "$(uname)" == Darwin ]] || die "编译 App 只能在 Mac 上做（这台不是 Mac）；可以用 --stage-only 只组装网页资源"
xcrun --find swiftc >/dev/null 2>&1 || { xcode-select --install 2>/dev/null || true; die "没找到 Xcode 命令行工具：装好后再运行一次"; }
SDK=$(xcrun --sdk macosx --show-sdk-path)
APP="$OUT/LiveBoard.app"; rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
BIN=()
for arch in arm64 x86_64; do
  xcrun swiftc -O -swift-version 5 -sdk "$SDK" -target "$arch-apple-macos13.0" \
    -framework AppKit -framework WebKit -framework ServiceManagement \
    "$ROOT/app/LiveBoard/Policy.swift" "$ROOT/app/LiveBoard/Store.swift" "$ROOT/app/LiveBoard/Lang.swift" "$ROOT/app/LiveBoard/main.swift" -o "$OUT/LiveBoard-$arch"
  BIN+=("$OUT/LiveBoard-$arch")
done
lipo -create "${BIN[@]}" -output "$APP/Contents/MacOS/LiveBoard"; rm -f "${BIN[@]}"
sed -e "s/__BUNDLE_ID__/$BUNDLE_ID/" -e "s/__VERSION__/$VERSION/" -e "s/__BUILD__/$BUILD/" "$ROOT/app/LiveBoard/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist" >/dev/null
ditto "$STAGE/board" "$APP/Contents/Resources/board"
ditto "$ROOT/app/LiveBoard/Resources" "$APP/Contents/Resources"   # en.lproj / zh-Hans.lproj：界面文字和 App 名
for l in en zh-Hans; do plutil -lint "$APP/Contents/Resources/$l.lproj/Localizable.strings" "$APP/Contents/Resources/$l.lproj/InfoPlist.strings" >/dev/null; done
mkdir -p "$APP/Contents/Resources/licenses"   # 许可文件随 App 分发
cp "$ROOT/LICENSE" "$ROOT/NOTICE" "$APP/Contents/Resources/licenses/"
cp "$ROOT"/third_party/licenses/* "$APP/Contents/Resources/licenses/"
codesign --force --deep --sign - "$APP" >/dev/null   # 本机临时签名（没有开发者证书）
say "已生成 ${APP}（$(lipo -archs "$APP/Contents/MacOS/LiveBoard")）"

# 4) DMG
if [[ "$MODE" == "--dmg" ]]; then
  D="$OUT/dmg"; rm -rf "$D"; mkdir -p "$D"; ditto "$APP" "$D/实时看板.app"; ln -s /Applications "$D/Applications"   # 文件名要和 Info.plist 的 CFBundleDisplayName 一样，英文系统才显示 Live Board
  cp "$ROOT/LICENSE" "$D/LICENSE.txt"; cp "$ROOT/NOTICE" "$D/NOTICE.txt"
  rm -f "$OUT/LiveBoard-$VERSION.dmg"
  hdiutil create -quiet -volname "Live Board" -srcfolder "$D" -fs HFS+ -format UDZO "$OUT/LiveBoard-$VERSION.dmg"
  rm -rf "$D"; say "已生成 $OUT/LiveBoard-$VERSION.dmg"
fi
