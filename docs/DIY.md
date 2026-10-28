# 从源码安装（DIY）

## Mac App

前提：

- macOS 13 或更新（Apple 芯片和 Intel 都行）
- Xcode 命令行工具：终端里运行 `xcode-select --install`（不需要完整的 Xcode）
- Node.js 18+（构建看板网页用）

步骤：

1. 下载或 `git clone` 这个仓库。
2. 双击 `安装.command`（第一次可能要在「系统设置 → 隐私与安全性」里允许它运行），或在终端运行：
   ```bash
   zsh 安装.command
   ```
   它会：构建看板网页 → 编译 App（通用二进制）→ 装进 `/Applications`（没有写权限时装进 `~/Applications`）→ 打开。
3. 第一次打开会弹出设置窗口，按 README 里「第一次设置」做。

再运行一次 `安装.command` 就是更新；密钥和设置会保留。

### 自己打包 .dmg

```bash
scripts/build-app.sh --dmg            # 产出 dist/LiveBoard.app 和 dist/LiveBoard-<版本>.dmg
VERSION=0.2.0 BUILD=2 scripts/build-app.sh --dmg
BUNDLE_ID=com.example.liveboard scripts/build-app.sh   # 换成你自己的 Bundle ID
```

打出来的 App 是「临时签名」（ad-hoc），没有经过 Apple 公证：别人第一次打开时要在「系统设置 → 隐私与安全性」点「仍要打开」。
想让别人双击就能打开，需要 Apple 开发者账号做 Developer ID 签名和公证（`codesign` + `xcrun notarytool`），本项目的脚本没有内置这一步。

### App 存的东西

| 位置 | 内容 |
|---|---|
| `~/Library/Application Support/LiveBoard/notion_token` | 连接密钥（权限 600） |
| `~/Library/Application Support/LiveBoard/config.json` | 表 ID；可选 `timezone`（如 `"Asia/Tokyo"`，不写按本机时区）、`active_ms` / `idle_ms`（打开 / 收起时多久读一次 Notion，默认 3000 / 30000 毫秒，分别限制在 1000–60000 和 5000–600000） |

登录时自动打开：第一次打开时自动登记到「系统设置 → 通用 → 登录项」；可以在右键菜单里关掉。

卸载：双击 `卸载.command`。

## 写入端

只用 Python 标准库，Python 3.8+，macOS / Linux 都行。把 `writer/liveboard.py` 放到成员干活的机器上即可（也可以整个仓库拷过去）。

```bash
python3 writer/liveboard.py init --database <表链接或ID>
python3 writer/liveboard.py check
python3 writer/liveboard.py sync
```

不用 App 也能建表：`python3 writer/liveboard.py setup-notion --parent <页面链接>`（页面要先加上你的连接）。

数据目录默认是 `~/.liveboard/`，可以用环境变量 `LIVEBOARD_HOME` 换。密钥也可以放在环境变量 `LIVEBOARD_NOTION_TOKEN` 里。

### 让 sync 一直在跑

`sync` 要常驻：它负责把打卡推到 Notion，也负责处理 Mac 上的换人。没在跑时，看板会提示「换人还没生效：写入端（liveboard.py sync）好像没在运行」。同一台机器上只会跑一个 sync（有文件锁）。

**macOS（launchd）**：把下面内容存成 `~/Library/LaunchAgents/io.github.lunafantasylab.liveboard.sync.plist`，路径改成你的，然后运行 `launchctl load ~/Library/LaunchAgents/io.github.lunafantasylab.liveboard.sync.plist`。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.github.lunafantasylab.liveboard.sync</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>/path/to/writer/liveboard.py</string><string>sync</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/liveboard-sync.log</string>
  <key>StandardErrorPath</key><string>/tmp/liveboard-sync.log</string>
</dict></plist>
```

**Linux（systemd 用户服务）**：存成 `~/.config/systemd/user/liveboard-sync.service`，然后 `systemctl --user enable --now liveboard-sync`。

```ini
[Unit]
Description=LiveBoard writer sync

[Service]
ExecStart=/usr/bin/python3 /path/to/writer/liveboard.py sync
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

## 只改看板网页

```bash
python3 writer/liveboard.py serve          # 本机预览数据（读 ~/.liveboard 里的名单和事件，不连 Notion）
cd board && npm ci && npm run dev          # 打开终端里给出的地址
```

改完运行 `安装.command`（或 `scripts/build-app.sh`）重新打包。

## 换 3D 舞台模型（可选）

仓库里已带做好的 `board/public/studio6.glb`。想改舞台：装 Blender 4.2+，改 `blender/build_studio.py`，然后：

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender blender/export_web.sh
```
