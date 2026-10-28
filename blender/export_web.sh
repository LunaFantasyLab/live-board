#!/usr/bin/env bash
# 重建网页模型：Blender 导出 → gltf-transform 量化 + meshopt 压缩（约 1 MB → 约 120 KB）
# 用法：BLENDER=/path/to/blender blender/export_web.sh
#   macOS 上一般是 BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
set -euo pipefail
cd "$(dirname "$0")/.."
B="${BLENDER:-blender}"
command -v "$B" >/dev/null 2>&1 || { echo "找不到 Blender：请用 BLENDER=… 指定可执行文件" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
"$B" -b -P blender/build_studio.py -- --slots 6 --export "$TMP/studio6-raw.glb"
npx -y @gltf-transform/cli@4 optimize "$TMP/studio6-raw.glb" board/public/studio6.glb \
  --compress meshopt --texture-compress false --simplify false --instance false --join false --flatten false
ls -la board/public/studio6.glb
