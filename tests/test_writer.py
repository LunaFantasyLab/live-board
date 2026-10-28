#!/usr/bin/env python3
"""写入端 writer/liveboard.py 的测试。全部用本机假 Notion（tests/notion_mock.py），临时目录，不碰任何真实数据。
    python3 tests/test_writer.py -v
"""
import json, os, secrets, shutil, socket, stat, subprocess, sys, tempfile, time, unittest, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "writer", "liveboard.py")
MOCK = os.path.join(ROOT, "tests", "notion_mock.py")
TOKEN = "ntn_" + secrets.token_hex(23)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def jget(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def jreq(url, method, obj=None, headers=None):
    for _ in range(10):   # 测试自己直接调假 Notion 时也守限流：429 就等一下再试
        code, o = _jreq(url, method, obj, headers)
        if code != 429: return code, o
        time.sleep(1)
    return code, o


def _jreq(url, method, obj=None, headers=None):
    data = json.dumps(obj).encode() if obj is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Base(unittest.TestCase):
    rate = "3"

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.api = f"http://127.0.0.1:{cls.port}"
        cls.mock = subprocess.Popen([sys.executable, MOCK, str(cls.port)], env={**os.environ, "MOCK_TOKEN": TOKEN, "MOCK_LAG": "0", "MOCK_RATE": cls.rate})
        for _ in range(50):
            try:
                jget(cls.api + "/__stats"); break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.mock.terminate(); cls.mock.wait(5)

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="liveboard-test-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_cli(self, *args, stdin=None, env=None):
        e = {**os.environ, "LIVEBOARD_HOME": self.home, "NOTION_API_BASE": self.api, "LIVEBOARD_MIN_GAP": "0.36"}
        e.pop("LIVEBOARD_NOTION_TOKEN", None)
        e.update(env or {})
        return subprocess.run([sys.executable, CLI, *args], input=stdin, capture_output=True, text=True, env=e, timeout=120)

    def events(self):
        p = os.path.join(self.home, "events.jsonl")
        if not os.path.exists(p): return []
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f]

    def setup_db(self):
        """init 存密钥 → setup-notion 在示例页面里建表"""
        r = self.run_cli("init", "--token-stdin", stdin=TOKEN + "\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        page = [x for x in jreq(self.api + "/v1/search", "POST", {}, {"Authorization": "Bearer " + TOKEN})[1]["results"] if x["object"] == "page"][0]
        r = self.run_cli("setup-notion", "--parent", "https://www.notion.so/" + page["id"].replace("-", ""))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.home, "config.json")) as f:
            return json.load(f)["database_id"]


class TestEv(Base):
    def setUp(self):
        super().setUp()
        shutil.copy(os.path.join(ROOT, "examples", "roster.example.json"), os.path.join(self.home, "roster.json"))

    def test_basic_event(self):
        r = self.run_cli("ev", "开始", "--bot", "写手", "--project", "示例任务", "--msg", "开始写初稿")
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.events()[-1]
        self.assertEqual((e["bot"], e["type"], e["project"], e["source"]), ("写手", "开始", "示例任务", "cli"))
        self.assertRegex(e["ts"], r"[+-]\d{2}:\d{2}$")   # 带本机时区

    def test_english_alias_and_handoff_needs_to(self):
        r = self.run_cli("ev", "handoff", "--bot", "写手", "--msg", "交给画师")
        self.assertEqual(r.returncode, 2); self.assertIn("--to", r.stderr)
        r = self.run_cli("ev", "handoff", "--bot", "写手", "--to", "画师", "--msg", "交给画师")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.events()[-1]["type"], "交接")

    def test_files_store_basename_only(self):
        f = os.path.join(self.home, "子目录", "初稿.md"); os.makedirs(os.path.dirname(f))
        with open(f, "w") as fh: fh.write("x")
        r = self.run_cli("ev", "产出", "--bot", "写手", "--msg", "初稿", "--file", f)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.events()[-1]["files"], ["初稿.md"])
        self.assertNotIn(self.home, json.dumps(self.events()[-1], ensure_ascii=False))

    def test_rejects_secrets(self):
        for msg in ["密钥是 ntn_" + "a" * 30, "secret_" + "b" * 30, "password=hunter2", "token: abc",
                    "sk-" + "Ab1" * 6, "这串 " + "aZ3kQ9xV2mL7pR4tW8yB5nC1" + "dF6gH0jK", "-----BEGIN PRIVATE KEY-----"]:
            r = self.run_cli("ev", "产出", "--bot", "写手", "--msg", msg)
            self.assertEqual(r.returncode, 2, msg); self.assertIn("密钥", r.stderr)
        self.assertEqual(self.events(), [])

    def test_secret_filter_lets_plain_words_through(self):
        # DS-8：只拦像密钥的格式，「密码」「密钥」这类普通词照常写
        for msg in ["请把密码改成新密码", "密钥已更新到新文档", "password 规则说明", "commit 3f2a9c1e0b7d4a6f8e5c2b1a0d9f8e7c6b5a4f3e"]:
            r = self.run_cli("ev", "产出", "--bot", "写手", "--msg", msg)
            self.assertEqual(r.returncode, 0, msg + " / " + r.stderr)
        self.assertEqual(len(self.events()), 4)

    def test_validation(self):
        cases = [
            (["ev", "吃饭", "--bot", "写手", "--msg", "x"], "类型"),
            (["ev", "开始", "--bot", "不存在的人", "--msg", "x"], "不认识"),
            (["ev", "开始", "--bot", "写手", "--msg", "长" * 81], "最多"),
            (["ev", "开始", "--bot", "写手", "--msg", "x", "--ts", "2026-01-01T08:00"], "补记"),
            (["ev", "开始", "--bot", "写手", "--msg", "x", "--source", "补记"], "--ts"),
            (["ev", "开始", "--bot", "写手", "--msg", "x", "--gate", "有 空格"], "--gate"),
            (["ev", "开始", "--bot", "写手", "--msg", "x", "--file", "/不存在/的文件"], "不存在"),
        ]
        for args, word in cases:
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, args); self.assertIn(word, r.stderr, args)
        self.assertEqual(self.events(), [])

    def test_backfill_with_ts(self):
        ts = time.strftime("%Y-%m-%dT%H:%M", time.localtime(time.time() - 3600))
        r = self.run_cli("ev", "完成", "--bot", "审核员", "--msg", "审完了", "--source", "补记", "--ts", ts)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.events()[-1]["source"], "backfill")

    def test_log_and_roster(self):
        self.run_cli("ev", "开始", "--bot", "写手", "--msg", "开写")
        self.assertIn("写手  开始  开写", self.run_cli("log").stdout)
        out = self.run_cli("roster").stdout
        self.assertIn("调度", out); self.assertIn("选题 → 写稿", out)


class TestNotion(Base):
    def test_init_rejects_bad_token(self):
        r = self.run_cli("init", "--token-stdin", stdin="not-a-token\n")
        self.assertEqual(r.returncode, 2); self.assertIn("不像", r.stderr)
        r = self.run_cli("init", "--token-stdin", stdin="ntn_" + "0" * 46 + "\n")
        self.assertEqual(r.returncode, 1); self.assertIn("401", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, "notion_token")))

    def test_init_setup_check(self):
        db = self.setup_db()
        tf = os.path.join(self.home, "notion_token")
        self.assertEqual(stat.S_IMODE(os.stat(tf).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.home).st_mode), 0o700)
        self.assertTrue(os.path.exists(os.path.join(self.home, "roster.json")))   # 示例名单自动放好
        r = self.run_cli("check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("表结构正确", r.stdout)
        # 已有表：init --database 当场核对表结构
        r = self.run_cli("init", "--database", db)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("init", "--database", "f" * 32)
        self.assertEqual(r.returncode, 1); self.assertIn("404", r.stderr)

    def test_token_never_in_outputs(self):
        self.setup_db()
        self.run_cli("ev", "开始", "--bot", "写手", "--msg", "开写")
        self.run_cli("sync", "--once")
        for dp, _, fs in os.walk(self.home):
            for f in fs:
                if f == "notion_token": continue
                with open(os.path.join(dp, f), encoding="utf-8", errors="replace") as fh:
                    self.assertNotIn(TOKEN, fh.read(), f)

    def test_sync_dedupe_and_swaps(self):
        db = self.setup_db()
        for i in range(3):
            self.run_cli("ev", "产出", "--bot", "写手", "--msg", f"第 {i} 稿")
        self.run_cli("ev", "开始", "--bot", "写手", "--msg", "测试事件", "--test")
        r = self.run_cli("sync", "--once")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = lambda: [x for x in self.query(db) if not x["archived"]]
        kinds = sorted(self.kind(x) for x in rows())
        self.assertEqual(kinds, ["事件"] * 3 + ["名单"], "测试事件不写；名单写一行")
        seqs = [x["properties"]["序号"]["number"] for x in rows()]
        self.assertEqual(len(set(seqs)), len(seqs), "序号不重复")
        # 记账文件丢了：从 Notion 读回，不重复写
        os.remove(os.path.join(self.home, "state", "sync.json"))
        self.run_cli("ev", "完成", "--bot", "写手", "--msg", "写完了")
        self.assertEqual(self.run_cli("sync", "--once").returncode, 0)
        self.assertEqual(sorted(self.kind(x) for x in rows()).count("事件"), 4)
        # Mac 发来的换人：合法的写进 slots.json，名单外的名字拒绝
        names = ["调度", "研究员", "写手", "画师", "剪辑师", "审核员"]
        self.add_swap(db, {"slots": names, "reason": "manual"})
        self.assertEqual(self.run_cli("sync", "--once").returncode, 0)
        sl = self.slots()
        self.assertEqual((sl["slots"], sl["by"]), (names, "手动替换"))
        self.assertIn("工位", [self.kind(x) for x in rows()])
        self.add_swap(db, {"slots": names[:5] + ["外人"], "reason": "manual"})
        self.assertEqual(self.run_cli("sync", "--once").returncode, 0)
        self.assertEqual(self.slots()["slots"], names)
        swaps = [x for x in self.query(db) if self.kind(x) == "换人"]
        self.assertEqual(sorted(x["properties"]["状态"]["select"]["name"] for x in swaps), ["已处理", "已拒绝"])
        self.assertTrue(all(x["archived"] for x in swaps))
        # ifEmpty：已经有工位时不覆盖
        self.add_swap(db, {"slots": names[::-1], "ifEmpty": True, "reason": "default"})
        self.run_cli("sync", "--once")
        self.assertEqual(self.slots()["slots"], names)

    def test_bootstrap_keeps_newest_row(self):
        # DS-5：记账文件丢了重读 Notion 时，同一种行有好几行（序号一样）也要留最新那行
        db = self.setup_db()
        auth = {"Authorization": "Bearer " + TOKEN}
        def add(kind, text, seq):
            code, o = jreq(self.api + "/v1/pages", "POST", {"parent": {"database_id": db}, "properties": {
                "名称": {"title": [{"type": "text", "text": {"content": kind}}]}, "类型": {"select": {"name": kind}},
                "序号": {"number": seq}, "数据": {"rich_text": [{"type": "text", "text": {"content": text}}]}}}, auth)
            self.assertEqual(code, 200); time.sleep(0.05); return o["id"]
        old, new = add("工位", "旧", 5), add("工位", "新", 5)
        lower, top = add("名单", "高序号", 9), add("名单", "低序号", 3)
        sf = os.path.join(self.home, "state", "sync.json")
        if os.path.exists(sf): os.remove(sf)
        r = self.run_cli("sync", "--once")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        arch = {x["id"]: x["archived"] for x in self.query(db)}
        self.assertEqual((arch[old], arch[new]), (True, False), "序号一样时留后建的那行")
        self.assertEqual((arch[lower], arch[top]), (False, True), "留序号大的那行")

    def test_rate_limit(self):
        self.setup_db()
        for i in range(12):
            self.run_cli("ev", "产出", "--bot", "写手", "--msg", f"稿 {i}")
        time.sleep(1.1); jget(self.api + "/__stats/reset")
        self.assertEqual(self.run_cli("sync", "--once").returncode, 0)
        s = jget(self.api + "/__stats")
        self.assertGreaterEqual(s["requests"], 12)
        self.assertEqual(s["r429"], 0, "没有被限流")
        self.assertLessEqual(s["max_per_sec"], 3)

    # 直接读假 Notion（含已归档的行，不计入限流）
    def query(self, db):
        return jget(f"{self.api}/__rows/{db}")

    def slots(self):
        with open(os.path.join(self.home, "state", "slots.json")) as f:
            return json.load(f)

    def kind(self, row):
        return row["properties"]["类型"]["select"]["name"]

    def add_swap(self, db, data):
        code, _ = jreq(self.api + "/v1/pages", "POST", {"parent": {"database_id": db}, "properties": {
            "名称": {"title": [{"type": "text", "text": {"content": "换人"}}]}, "类型": {"select": {"name": "换人"}},
            "状态": {"select": {"name": "待处理"}}, "数据": {"rich_text": [{"type": "text", "text": {"content": json.dumps(data, ensure_ascii=False)}}]}}},
            {"Authorization": "Bearer " + TOKEN})
        self.assertEqual(code, 200)


class TestServe(Base):
    def test_preview_server(self):
        shutil.copy(os.path.join(ROOT, "examples", "roster.example.json"), os.path.join(self.home, "roster.json"))
        self.run_cli("ev", "开始", "--bot", "写手", "--msg", "开写")
        port = free_port()
        p = subprocess.Popen([sys.executable, CLI, "serve", "--port", str(port)], env={**os.environ, "LIVEBOARD_HOME": self.home}, stdout=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                try: jget(base + "/api/roster"); break
                except OSError: time.sleep(0.1)
            self.assertEqual(jget(base + "/api/roster")["title"], "示例团队")
            self.assertEqual(len(jget(base + "/api/events")), 1)
            self.assertEqual(jget(base + "/__board/slots"), {"slots": None})
            names = ["调度", "研究员", "写手", "画师", "剪辑师", "审核员"]
            self.assertEqual(jreq(base + "/__board/slots", "PUT", {"slots": names})[0], 404, "没有 X-Live-Board 头不收")
            self.assertEqual(jreq(base + "/__board/slots", "PUT", {"slots": names[:5]}, {"X-Live-Board": "1"})[0], 400)
            code, o = jreq(base + "/__board/slots", "PUT", {"slots": names, "reason": "manual"}, {"X-Live-Board": "1"})
            self.assertEqual((code, o["slots"]), (200, names))
            code, o = jreq(base + "/__board/slots", "PUT", {"slots": names[::-1], "ifEmpty": True}, {"X-Live-Board": "1"})
            self.assertEqual((code, o["slots"], o.get("kept")), (200, names, True))
        finally:
            p.terminate(); p.wait(5)


if __name__ == "__main__":
    unittest.main()
