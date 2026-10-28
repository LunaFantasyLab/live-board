# 素材来源清单

**简体中文** | [English](ASSETS.en.md)

本仓库不包含任何取自游戏、影视或其他作品的原始素材（贴图、字体、Logo、角色、UI 截图或 1:1 复制的界面元素）。
画面全部由仓库里的代码现场生成；唯一打包进来的第三方素材是免费字体 Anton（SIL OFL 1.1）。

| 资源 | 位置 | 来源 | 许可 |
|---|---|---|---|
| 工位 3D 模型 `studio6.glb` | `board/public/` | 由 `blender/build_studio.py` 用立方体、圆柱、球、圆锥和代码算出的多角星拼成，只用顶点色，无贴图；`blender/export_web.sh` 压缩（meshopt + 量化）。可用 Blender 4.2 重新生成 | 本项目（CC BY-NC 4.0） |
| 生成脚本 | `blender/` | 本项目自写，不加载任何外部图片、字体或模型 | 本项目 |
| 网页图标（favicon） | `board/index.html` 内联 SVG | 一个圆角方块加描边，代码写成 | 本项目 |
| 背景放射线、网点、斜切卡片、星形徽章 | `board/src/style.css` | CSS 渐变和 `clip-path` 多边形，代码写成；无外部图片、无 `url()`、无 `@import` | 本项目 |
| 配色（红 / 黑 / 白 / 米白 / 灰） | `board/src/style.css`、`build_studio.py` | 自选色值 | 本项目 |
| 场景里的 “Z” 字、彩色纸屑、灯光闪烁 | `board/src/scene.js` | 运行时用 canvas 和 Three.js 代码生成 | 本项目 |
| 数字字体 Anton | npm `@fontsource/anton`，构建后进 `dist` | Google Fonts / The Anton Project Authors | SIL OFL 1.1，见 `third_party/licenses/Anton-OFL-1.1.txt` |
| 中文与备用字体（PingFang SC、Noto Sans CJK SC 等） | CSS 字体名 | 只引用用户电脑上已有的系统字体，不随仓库分发 | — |
| 3D 引擎 three.js | npm `three` | three.js authors | MIT，见 `third_party/licenses/three.js-MIT.txt` |
| README 截图和动图 | `docs/images/`（中文界面）、`docs/images/en/`（英文界面） | 用本仓库的看板网页、`tests/` 里的假 Notion 和示例名单在浏览器里录制，没有真实数据 | 本项目（CC BY-NC 4.0） |

重新生成模型 / Regenerate the model:

```bash
BLENDER=/path/to/blender bash blender/export_web.sh
```
