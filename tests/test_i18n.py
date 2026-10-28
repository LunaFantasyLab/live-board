#!/usr/bin/env python3
"""界面双语（简体中文 / English）的静态检查：两套文字条目一一对应、代码里用到的条目都有、英文里没有中文、
App 名和安装包在英文系统下的名字、两份 README 互相能切换。只读文件，不联网。
    python3 tests/test_i18n.py -v
"""
import json, os, plistlib, re, subprocess, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "app", "LiveBoard", "Resources")
CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
STR = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;\s*$')


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f: return f.read()


def strings(lang, table="Localizable"):
    out = {}
    with open(os.path.join(RES, f"{lang}.lproj", f"{table}.strings"), encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.strip().startswith(("/*", "//", "*")): continue
            m = STR.match(line)
            assert m, f"{lang}/{table}.strings 这一行不是 \"key\" = \"value\"; 格式：{line!r}"
            assert m.group(1) not in out, f"{lang}/{table}.strings 重复的 key：{m.group(1)}"
            out[m.group(1)] = m.group(2)
    return out


def node_dicts(src, expr):
    """在 node 里跑一段网页脚本，取出它的双语词表"""
    code = src + "\nconsole.log(JSON.stringify(" + expr + "));"
    r = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


class TestNative(unittest.TestCase):
    def test_tables_match(self):
        zh, en = strings("zh-Hans"), strings("en")
        self.assertEqual(set(zh), set(en))
        self.assertGreaterEqual(len(zh), 20)
        for k, v in en.items():
            self.assertFalse(CJK.search(v), f"英文条目里有中文：{k} = {v}")
        for k in zh:   # 带参数的条目，两边参数个数一样
            self.assertEqual(len(re.findall(r"%(?:\d\$)?@", zh[k])), len(re.findall(r"%(?:\d\$)?@", en[k])), k)

    def test_code_keys_exist(self):
        zh = strings("zh-Hans")
        used = set()
        for f in ("main.swift", "Store.swift", "Lang.swift"):
            used |= set(re.findall(r'\bL\("([^"]+)"', read(f"app/LiveBoard/{f}")))
        self.assertGreater(len(used), 15)
        self.assertEqual(sorted(used - set(zh)), [], "代码里用到、词表里没有的条目")
        self.assertEqual(sorted(set(zh) - used), [], "词表里有、代码里没用到的条目")

    def test_no_hardcoded_chinese_in_ui_code(self):
        # 原生层的界面文字都要走 L("…")：去掉注释后，main.swift / Store.swift 里不该再有中文字符串
        for f in ("main.swift", "Store.swift"):
            src = read(f"app/LiveBoard/{f}")
            src = re.sub(r"//[^\n]*", "", src)
            lits = [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', src) if CJK.search(s)]
            allowed = {"类型", "换人", "简体中文"}   # Notion 表的协议字段；语言名用它自己的文字写
            self.assertEqual([s for s in lits if s not in allowed], [], f)

    def test_app_name(self):
        info = plistlib.loads(read("app/LiveBoard/Info.plist").encode())
        self.assertTrue(info.get("LSHasLocalizedDisplayName"))
        self.assertEqual(info.get("CFBundleDevelopmentRegion"), "en")
        self.assertEqual(sorted(info.get("CFBundleLocalizations") or []), ["en", "zh-Hans"])
        en, zh = strings("en", "InfoPlist"), strings("zh-Hans", "InfoPlist")
        self.assertEqual(en.get("CFBundleDisplayName"), "Live Board")
        self.assertEqual(zh.get("CFBundleDisplayName"), "实时看板")
        # Finder 只有在文件名和 Info.plist 里的 CFBundleDisplayName 一样时才显示本地化的名字
        build = read("scripts/build-app.sh")
        self.assertIn(f'"$D/{info["CFBundleDisplayName"]}.app"', build)
        self.assertIn(f'/Applications/{info["CFBundleDisplayName"]}.app', read("安装.command"))

    def test_dmg_names(self):
        build = read("scripts/build-app.sh")
        self.assertIn('-volname "Live Board"', build)
        self.assertIn('"$D/Applications"', build)
        self.assertIn("app/LiveBoard/Resources", build)   # 两套 .lproj 打进 App
        for f in ("scripts/build-app.sh", ".github/workflows/build.yml"):
            self.assertIn("Lang.swift", read(f), f)


class TestWeb(unittest.TestCase):
    def test_board_dict(self):
        d = node_dicts(read("board/src/i18n.js"), "{zh: Object.keys(STRINGS.zh), en: Object.keys(STRINGS.en), enV: Object.values(STRINGS.en), "
                       "r: [pickLang('en', []), pickLang('zh', ['en-US']), pickLang('', ['en-US']), pickLang(undefined, ['zh-CN']), pickLang('', ['ja', 'zh-TW']), pickLang('', ['fr'])]}")
        self.assertEqual(set(d["zh"]), set(d["en"]))
        for v in d["enV"]: self.assertFalse(CJK.search(v), v)
        self.assertEqual(d["r"], ["en", "zh", "en", "zh", "zh", "en"])

    def test_board_keys_used(self):
        d = node_dicts(read("board/src/i18n.js"), "Object.keys(STRINGS.zh)")
        pat = r'\bt\("([^"]+)"\s*[,)]'   # t("key") / t("key", {...})；拼出来的 key（t("st." + k)）不算
        used = set(re.findall(pat, read("board/src/main.js"))) | set(re.findall(r'\btr\("([^"]+)"\s*[,)]', read("board/src/scene.js")))
        self.assertEqual(sorted(used - set(d)), [])

    def test_board_no_hardcoded_chinese(self):
        src = re.sub(r"//[^\n]*|/\*.*?\*/", "", read("board/src/main.js"), flags=re.S)
        lits = [s for s in re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', src) for s in s if s and CJK.search(s)]
        protocol = {"交接", "退回", "待确认", "完成", "报错"}   # 事件类型是协议值（数据），显示时再翻译
        self.assertEqual([s for s in lits if s not in protocol], [])

    def test_setup_and_relay_dict(self):
        src = read("app/LiveBoard/web/i18n.js")
        d = node_dicts("globalThis.window = globalThis; Object.defineProperty(globalThis, 'navigator', {value: {languages: ['en-US']}, configurable: true});\n" + src,
                       "{zh: Object.keys(window.__LB_I18N.STRINGS.zh), en: Object.keys(window.__LB_I18N.STRINGS.en), enV: Object.values(window.__LB_I18N.STRINGS.en), lang: window.__LB_I18N.lang}")
        self.assertEqual(set(d["zh"]), set(d["en"]))
        for v in d["enV"]: self.assertFalse(CJK.search(v), v)
        self.assertEqual(d["lang"], "en")
        used = set()
        for f in ("app/LiveBoard/web/setup.js", "app/LiveBoard/web/relay.js"):
            used |= set(re.findall(r'\b(?:T|tx)\("([^"]+)"', read(f)))
        used |= set(re.findall(r'data-i18n(?:-[a-z]+)?="([^"]+)"', read("app/LiveBoard/web/setup.html")))
        self.assertGreater(len(used), 20)
        self.assertEqual(sorted(used - set(d["zh"])), [])
        self.assertEqual(sorted(set(d["zh"]) - used), [])
        for f in ("app/LiveBoard/web/setup.js", "app/LiveBoard/web/relay.js"):
            src = re.sub(r"//[^\n]*|/\*.*?\*/", "", read(f), flags=re.S)
            lits = [s for s in re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', src) for s in s if s and CJK.search(s)]
            protocol = {"名称", "类型", "序号", "数据", "状态", "事件", "工位", "名单", "换人", "待处理", "已处理", "已拒绝", "换人 ",
                        # 工位记录里的 by 字段：写进数据、和写入端一致，界面不显示
                        "默认（按最近动态，第一次存下后固定）", "沿用这台设备原来的选择", "手动替换"}
            self.assertEqual([s for s in lits if s not in protocol and not s.startswith("换人 ")], [], f)


class TestSceneMeter(unittest.TestCase):
    def test_debug_meter_localized(self):
        """DS-1：调试读数也跟着语言走，不写死英文或中文"""
        sc = read("board/src/scene.js")
        line = next(l for l in sc.splitlines() if "meter.textContent" in l)
        self.assertIn('tr("meter"', line)
        self.assertIn('import { t as tr } from "./i18n.js"', sc)
        self.assertNotIn("ms/frame", line); self.assertNotIn("draws", line)


class TestDocs(unittest.TestCase):
    def test_readmes(self):
        zh, en = read("README.md"), read("README.en.md")
        self.assertIn("[English](README.en.md)", zh.split("\n\n")[0] + zh[:400])
        self.assertIn("[简体中文](README.md)", en[:400])
        for w in ("CC BY-NC 4.0", "Luna Fantasy Lab", "releases/latest", "Notion", "liveboard.py"):
            self.assertIn(w, en, w)
        self.assertIn("docs/images/en/", en)
        self.assertFalse(re.search(r"\bopen[- ]source\b", en, re.I), "英文 README 不用 open source 形容许可证")
        self.assertIn("source-available", en)
        self.assertIn("releases/latest", zh)

    def test_docs_en(self):
        for f in ("docs/DIY.en.md", "docs/PROTOCOL.en.md", "docs/ASSETS.en.md"):
            s = read(f)
            self.assertGreater(len(s), 500, f)
            self.assertFalse(re.search(r"\bopen[- ]source\b", s, re.I), f)
        self.assertIn("English", read("NOTICE"))
        for f in ("board.gif", "working.png", "idle.png", "detail.png"):
            self.assertTrue(os.path.getsize(os.path.join(ROOT, "docs", "images", "en", f)) > 10000, f)


if __name__ == "__main__":
    unittest.main()
