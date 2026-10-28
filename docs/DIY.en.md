# Build from source (DIY)

[简体中文](DIY.md) | **English**

## Mac app

Requirements:

- macOS 13 or later (Apple silicon or Intel)
- Xcode Command Line Tools: run `xcode-select --install` in Terminal (full Xcode is not needed)
- Node.js 18+ (to build the board web page)

Steps:

1. Download or `git clone` this repository.
2. Double-click `安装.command` ("install"; the first time you may have to allow it in **System Settings → Privacy & Security**), or run in Terminal:
   ```bash
   zsh 安装.command
   ```
   It builds the board web page → compiles the app (universal binary) → installs it into `/Applications` (or `~/Applications` if `/Applications` isn't writable) → opens it.
3. On first launch the setup window appears; follow "First-time setup" in the [README](../README.en.md).

Running `安装.command` again updates the app; your token and settings are kept.

### Build your own .dmg

```bash
scripts/build-app.sh --dmg            # produces dist/LiveBoard.app and dist/LiveBoard-<version>.dmg (volume name "Live Board")
VERSION=0.2.0 BUILD=2 scripts/build-app.sh --dmg
BUNDLE_ID=com.example.liveboard scripts/build-app.sh   # use your own bundle ID
```

The app is ad-hoc signed and not notarized by Apple: the first time someone opens it they have to click **Open Anyway** in **System Settings → Privacy & Security**.
If you want people to open it with a plain double-click, you need an Apple Developer account for Developer ID signing and notarization (`codesign` + `xcrun notarytool`); the scripts in this project don't do that step.

Inside the dmg the app bundle is named `实时看板.app`. That is intentional: macOS shows the localized name (**Live Board** on English systems, **实时看板** on Chinese systems) only when the bundle file name matches the base display name.

### Language

- The app follows the macOS language by default. Right-click the menu bar cube → **Language** to choose *System Default*, *简体中文* or *English*; the setup window has the same choice in its top-right corner.
- The choice is stored in the app's preferences (`defaults read io.github.lunafantasylab.liveboard language`: `system`, `zh-Hans` or `en`).
- Native strings live in `app/LiveBoard/Resources/<lang>.lproj/Localizable.strings`; web strings in `app/LiveBoard/web/i18n.js` (setup) and `board/src/i18n.js` (board). `tests/test_i18n.py` checks that every key exists in both languages.

### What the app stores

| Location | Contents |
|---|---|
| `~/Library/Application Support/LiveBoard/notion_token` | Notion token (mode 600) |
| `~/Library/Application Support/LiveBoard/config.json` | Table ID; optional `timezone` (e.g. `"Asia/Tokyo"`, defaults to the Mac's time zone), `active_ms` / `idle_ms` (how often Notion is read while the board is open / closed; default 3000 / 30000 ms, limited to 1000–60000 and 5000–600000) |

Open at login: on first launch the app registers itself under **System Settings → General → Login Items**; you can turn it off in the right-click menu.

Uninstall: double-click `卸载.command` ("uninstall").

## Writer

Python standard library only, Python 3.8+, macOS or Linux. Put `writer/liveboard.py` on the machine where your members work (or copy the whole repository).

```bash
python3 writer/liveboard.py init --database <table link or ID>
python3 writer/liveboard.py check
python3 writer/liveboard.py sync
```

Creating the table without the app: `python3 writer/liveboard.py setup-notion --parent <page link>` (connect your integration to the page first).

The data folder is `~/.liveboard/` by default; change it with the `LIVEBOARD_HOME` environment variable. The token can also come from the `LIVEBOARD_NOTION_TOKEN` environment variable.

Messages are in English when `LANG` (or `LC_ALL` / `LC_MESSAGES`) is a non-Chinese locale, and in Chinese for Chinese locales or when no locale is set. Set `LIVEBOARD_LANG=en`, or add `--lang en` anywhere in a command, to force English. Event types can be written in English (`claim`, `start`, `output`, `handoff`, `return`, `confirm`, `done`, `error`); they are stored as the Chinese protocol values. `--source` accepts `checkin` or `backfill`.

### Keep sync running

`sync` must keep running: it pushes check-ins to Notion and also applies desk swaps made on the Mac. When it isn't running, the board says the swap hasn't taken effect because the writer (`liveboard.py sync`) doesn't seem to be running. Only one sync runs per machine (file lock).

**macOS (launchd)**: save the following as `~/Library/LaunchAgents/io.github.lunafantasylab.liveboard.sync.plist`, change the path to yours, then run `launchctl load ~/Library/LaunchAgents/io.github.lunafantasylab.liveboard.sync.plist`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.github.lunafantasylab.liveboard.sync</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>/path/to/writer/liveboard.py</string><string>sync</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>LIVEBOARD_LANG</key><string>en</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/liveboard-sync.log</string>
  <key>StandardErrorPath</key><string>/tmp/liveboard-sync.log</string>
</dict></plist>
```

**Linux (systemd user service)**: save as `~/.config/systemd/user/liveboard-sync.service`, then run `systemctl --user enable --now liveboard-sync`.

```ini
[Unit]
Description=Live Board writer sync

[Service]
ExecStart=/usr/bin/python3 /path/to/writer/liveboard.py sync --lang en
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

## Work on the board page only

```bash
python3 writer/liveboard.py serve          # local preview data (reads the roster and events in ~/.liveboard, no Notion)
cd board && npm ci && npm run dev          # open the address printed in the terminal; add ?lang=en for English
```

When you're done, run `安装.command` (or `scripts/build-app.sh`) to package again.

## Change the 3D stage model (optional)

The repository already includes the built `board/public/studio6.glb`. To change the stage: install Blender 4.2+, edit `blender/build_studio.py`, then:

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender blender/export_web.sh
```
