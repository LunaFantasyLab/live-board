#!/usr/bin/env python3
"""liveboard — 实时看板的写入端（只用 Python 标准库，Python 3.8+，macOS / Linux）。

成员打卡写进本机的 events.jsonl（只追加）；sync 常驻进程把事件、名单、工位同步到你 Notion 里的「看板数据」表，
Mac 菜单栏 App 从那张表读。Mac 上换人会在表里加一行「换人」，也由 sync 处理。

用法
  liveboard.py init [--database <表链接或ID>]    第一次：保存连接密钥（提示粘贴，不回显）和表 ID，并当场验证
  liveboard.py setup-notion --parent <页面链接或ID> 不用 App 也能建表：在这个页面里建「实时看板中转」页和「看板数据」表
  liveboard.py check                              检查密钥、表、名单是否都正常
  liveboard.py ev <类型> --bot <成员> --msg "一句话" [--project <任务名>] [--to <成员>] [--task <ID>]
                 [--gate <标记>] [--file <文件>]... [--test] [--source 打卡|补记] [--ts <时间>]
  liveboard.py log [条数]                         看最近的事件（默认 10 条）
  liveboard.py roster                             列出名单里的成员和可用的事件类型
  liveboard.py sync [--once]                      同步到 Notion（常驻；--once 同步完就退出）
  liveboard.py serve [--port 4380]                本机预览服务（给 board/ 的 npm run dev 用，不连 Notion）

事件类型：接单 开始 产出 交接 退回 待确认 完成 报错
  （也可以写英文：claim start output handoff return confirm done error）
交接、退回要写 --to。--file 只记文件名，不记完整路径。--ts 只有补记才能用，不写时区按本机时区。

文件都在 $LIVEBOARD_HOME（默认 ~/.liveboard/）：
  config.json（表 ID）  notion_token（连接密钥，600 权限）  roster.json（名单）  events.jsonl（事件）  state/（同步记账）
连接密钥也可以放在环境变量 LIVEBOARD_NOTION_TOKEN 里。
"""
import argparse, fcntl, getpass, hashlib, json, os, re, secrets, shutil, sys, threading, time
import urllib.error, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.abspath(os.path.expanduser(os.environ.get("LIVEBOARD_HOME", "~/.liveboard")))
API = os.environ.get("NOTION_API_BASE", "https://api.notion.com").rstrip("/")
NOTION_VERSION = "2022-06-28"
CONFIG = os.path.join(HOME, "config.json")
TOKEN_FILE = os.path.join(HOME, "notion_token")
ROSTER = os.path.join(HOME, "roster.json")
EVENTS = os.path.join(HOME, "events.jsonl")
STATE = os.path.join(HOME, "state")
SLOTS = os.path.join(STATE, "slots.json")
SYNC = os.path.join(STATE, "sync.json")
STATUS = os.path.join(STATE, "status.json")
LOCK = os.path.join(STATE, "sync.lock")
HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_ROSTER = os.path.join(HERE, "..", "examples", "roster.example.json")

SLOT_N = 6
MIN_GAP = float(os.environ.get("LIVEBOARD_MIN_GAP", "0.45"))   # 两次请求至少隔 0.45 秒（≤2.2 次/秒，低于 Notion 约 3 次/秒）
SWAP_EVERY = 2.0
CHUNK = 1000          # Notion 每段文字上限 2000 字，取 1000 留余量
BY_TXT = {"default": "默认（按最近动态，第一次存下后固定）", "local": "沿用这台设备原来的选择", "manual": "手动替换"}
TYPES = ["接单", "开始", "产出", "交接", "退回", "待确认", "完成", "报错"]
TYPE_ALIAS = {"claim": "接单", "start": "开始", "output": "产出", "handoff": "交接", "return": "退回",
              "confirm": "待确认", "done": "完成", "error": "报错"}
SOURCES = {"打卡": "cli", "补记": "backfill", "cli": "cli", "backfill": "backfill"}
# 只拦「真像密钥」的内容：常见密钥前缀、私钥头、「password=…」这类赋值写法、长随机串。
# 「密码」「密钥」「token」这些普通词本身不拦。
SECRET = re.compile(r"(ntn_[A-Za-z0-9]{10,}|secret_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{8,}"
                    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY"
                    r"|(password|passwd|pwd|api[_-]?key|app[_-]?secret|secret|token|cookie|密码|密钥)\s*[:=：]\s*\S{3,})", re.I)
LONG_RANDOM = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
def looks_secret(text):
    """像密钥就返回 True。长随机串要同时有大写、小写和数字（提交哈希、UUID 这类全小写的不算）。"""
    if SECRET.search(text): return True
    return any(re.search(r"[A-Z]", m) and re.search(r"[a-z]", m) and re.search(r"[0-9]", m) for m in LONG_RANDOM.findall(text))
GATE = re.compile(r"^[A-Za-z0-9_.-]{1,16}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?$")
BACK_DAYS, AHEAD_MIN, MSG_MAX = 30, 5, 80
B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
# 看板数据表的结构（和 App 设置向导 setup.js 里的 SCHEMA 一致）
SCHEMA = {
    "名称": {"title": {}},
    "类型": {"select": {"options": [{"name": "事件", "color": "blue"}, {"name": "工位", "color": "green"},
                                   {"name": "名单", "color": "purple"}, {"name": "换人", "color": "orange"}]}},
    "序号": {"number": {"format": "number"}},
    "数据": {"rich_text": {}},
    "状态": {"select": {"options": [{"name": "待处理", "color": "yellow"}, {"name": "已处理", "color": "green"},
                                   {"name": "已拒绝", "color": "red"}]}},
}
NEED = {"名称": "title", "类型": "select", "序号": "number", "数据": "rich_text", "状态": "select"}


# ---------- 小工具 ----------
def die(msg, code=2):
    print(f"liveboard：{msg}", file=sys.stderr)
    sys.exit(code)


def now_local():
    return datetime.now().astimezone()


def log(msg):
    print(f"{now_local().isoformat(timespec='seconds')} {msg}", flush=True)


def write_json(path, obj, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def norm_id(s):
    """从 Notion 链接或 ID 里取 32 位 ID（取路径里最后一串，忽略 ?v= 视图参数）"""
    path = str(s or "").strip().split("?")[0].split("#")[0].replace("-", "")
    m = re.findall(r"[0-9a-fA-F]{32}", path)
    return m[-1].lower() if m else ""


def read_token():
    t = os.environ.get("LIVEBOARD_NOTION_TOKEN", "").strip()
    if t:
        return t
    try:
        if os.stat(TOKEN_FILE).st_mode & 0o077:
            os.chmod(TOKEN_FILE, 0o600)
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_token(t):
    os.makedirs(HOME, exist_ok=True)
    os.chmod(HOME, 0o700)
    fd = os.open(TOKEN_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(t.strip() + "\n")
    os.replace(TOKEN_FILE + ".tmp", TOKEN_FILE)


def database_id():
    return norm_id((read_json(CONFIG, {}) or {}).get("database_id", ""))


def load_roster(strict=True):
    r = read_json(ROSTER)
    if not isinstance(r, dict) or not isinstance(r.get("bots"), list):
        if strict:
            die(f"名单读不了：{ROSTER}。先运行 init，或照 examples/roster.example.json 写一份")
        return {"bots": []}
    return r


def roster_problems(r):
    """名单格式检查，返回问题列表（空 = 没问题）"""
    out = []
    bots = r.get("bots")
    if not isinstance(bots, list) or not bots:
        return ["bots 要是一个非空列表"]
    names = [b.get("name") for b in bots if isinstance(b, dict)]
    if len(names) != len(bots) or not all(isinstance(n, str) and n.strip() for n in names):
        out.append("每个成员都要有 name（字符串）")
    if len(set(names)) != len(names):
        out.append("name 有重复")
    if len(bots) < SLOT_N:
        out.append(f"成员少于 {SLOT_N} 个：工位会空着（能用，只是提醒）")
    stages = r.get("stages", [])
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        out.append("stages 要是字符串列表")
        stages = []
    for b in bots:
        if isinstance(b, dict) and "stage" in b and not (isinstance(b["stage"], int) and 0 <= b["stage"] < len(stages)):
            out.append(f"{b.get('name')}：stage 要是 stages 的下标（0 到 {len(stages) - 1}）")
    return out


# ---------- Notion ----------
class NotionError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {body[:200]}")
        self.code, self.body = code, body


WHY = {401: "连接密钥不对（401）", 403: "这个连接没有权限（403）", 404: "看板表还没加上这个连接，或 ID 不对（404）"}


class Notion:
    def __init__(self, token, retries=6):
        self.token, self.last, self.count, self.retries = token, 0.0, 0, retries

    def call(self, method, path, body=None):
        for attempt in range(self.retries):
            gap = self.last + MIN_GAP - time.monotonic()
            if gap > 0:
                time.sleep(gap)
            self.last = time.monotonic()
            self.count += 1
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(API + path, data=data, method=method, headers={
                "Authorization": "Bearer " + self.token, "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf8", "replace")
                if e.code == 429 or e.code >= 500:
                    wait = float(e.headers.get("Retry-After") or 0) or min(30, 1.5 * 2 ** attempt)
                    time.sleep(wait)
                    continue
                raise NotionError(e.code, txt)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(min(30, 1.5 * 2 ** attempt))
                continue
        raise NotionError(0, "连不上 Notion")

    def query(self, db, body):
        out, cursor = [], None
        while True:
            b = dict(body, page_size=100)
            if cursor:
                b["start_cursor"] = cursor
            r = self.call("POST", f"/v1/databases/{db}/query", b)
            out += r.get("results", [])
            if not r.get("has_more"):
                return out
            cursor = r.get("next_cursor")


def schema_problems(db_obj):
    props = db_obj.get("properties") or {}
    return [f"{k}（{t}）" for k, t in NEED.items() if (props.get(k) or {}).get("type") != t]


def rich(text):
    return [{"type": "text", "text": {"content": text[i:i + CHUNK]}} for i in range(0, len(text), CHUNK)] or []


def plain(prop):
    if not prop:
        return ""
    arr = prop.get("rich_text") or prop.get("title") or []
    return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in arr)


def props(name, kind, seq, data, state=None):
    p = {"名称": {"title": [{"type": "text", "text": {"content": name[:200]}}]},
         "类型": {"select": {"name": kind}}, "序号": {"number": seq}, "数据": {"rich_text": rich(data)}}
    if state:
        p["状态"] = {"select": {"name": state}}
    return p


# ---------- 同步 ----------
def read_slots():
    o = read_json(SLOTS)
    if isinstance(o, dict) and isinstance(o.get("slots"), list) and len(o["slots"]) == SLOT_N:
        return o
    return None


def valid_slots(a, names):
    return isinstance(a, list) and len(a) == SLOT_N and all(isinstance(x, str) and x in names for x in a) and len(set(a)) == SLOT_N


def save_slots(a, reason, if_empty):
    rec = {"slots": a, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
           "by": BY_TXT.get(reason) or (BY_TXT["default"] if if_empty else BY_TXT["manual"])}
    write_json(SLOTS, rec, 0o644)
    return rec


def status(**kw):
    kw["at"] = now_local().isoformat(timespec="seconds")
    try:
        write_json(STATUS, kw, 0o644)
    except OSError:
        pass


class Sync:
    def __init__(self, n, db):
        self.n, self.db = n, db
        self.st = self.load_state()
        self.offset = 0
        self.partial = ""
        self.last_swap = 0.0

    def load_state(self):
        st = read_json(SYNC)
        if isinstance(st, dict) and st.get("database_id") == self.db:
            st["ids"] = set(st.get("ids", []))
            return st
        return self.bootstrap()

    def bootstrap(self):
        """记账文件没了（或换了表）：从 Notion 表里把已有的行读一遍，避免重复写。"""
        st = {"database_id": self.db, "seq": 0, "ids": set(), "roster_page": None, "slots_page": None,
              "roster_hash": None, "slots_hash": None}
        rows = self.n.query(self.db, {"filter": {"property": "类型", "select": {"does_not_equal": "换人"}},
                                      "sorts": [{"property": "序号", "direction": "ascending"},
                                                {"timestamp": "created_time", "direction": "ascending"}]})
        # 本地再排一次，顺序固定：序号小的在前，同序号按创建时间、再按 ID；后面的行就是更新的那行
        rows.sort(key=lambda r: ((r["properties"].get("序号", {}).get("number") or 0), r.get("created_time") or "", r.get("id") or ""))
        for r in rows:
            p = r["properties"]
            kind = (p.get("类型", {}).get("select") or {}).get("name")
            seq = p.get("序号", {}).get("number") or 0
            st["seq"] = max(st["seq"], int(seq))
            name = plain(p.get("名称"))
            if kind == "事件":
                st["ids"].add(name)
            elif kind in ("名单", "工位"):
                key = "roster" if kind == "名单" else "slots"
                if st[key + "_page"] and st.get(key + "_seq", 0) > seq:
                    self.n.call("PATCH", f"/v1/pages/{r['id']}", {"archived": True})   # 多出来的旧行
                    continue
                # 序号相同时，排在后面的（更晚创建的）留下，前面那行归档
                if st[key + "_page"]:
                    self.n.call("PATCH", f"/v1/pages/{st[key + '_page']}", {"archived": True})
                st[key + "_page"], st[key + "_seq"] = r["id"], seq
                st[key + "_hash"] = hashlib.sha256(plain(p.get("数据")).encode()).hexdigest()
        log(f"从 Notion 读回已有 {len(st['ids'])} 条事件，序号到 {st['seq']}")
        self.save(st)
        return st

    def save(self, st=None):
        st = st or self.st
        write_json(SYNC, dict(st, ids=sorted(st["ids"])))

    def next_seq(self):
        self.st["seq"] += 1
        return self.st["seq"]

    def new_events(self):
        try:
            size = os.path.getsize(EVENTS)
        except OSError:
            return []
        if size < self.offset:
            self.offset, self.partial = 0, ""
        if size == self.offset:
            return []
        with open(EVENTS, "rb") as f:
            f.seek(self.offset)
            buf = f.read(size - self.offset)
        self.offset = size
        text = self.partial + buf.decode("utf8", "replace")
        lines = text.split("\n")
        self.partial = lines.pop()
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("ts") and e.get("bot") and e.get("type") and e.get("id") and not e.get("test"):
                out.append(e)
        return out

    def push_events(self):
        n = 0
        for e in self.new_events():
            if e["id"] in self.st["ids"]:
                continue
            seq = self.next_seq()
            self.n.call("POST", "/v1/pages", {"parent": {"database_id": self.db},
                                              "properties": props(e["id"], "事件", seq, json.dumps(e, ensure_ascii=False))})
            self.st["ids"].add(e["id"])
            self.save()
            n += 1
        return n

    def upsert(self, key, kind, text):
        h = hashlib.sha256(text.encode()).hexdigest()
        if h == self.st.get(key + "_hash"):
            return False
        seq = self.next_seq()
        page = self.st.get(key + "_page")
        if page:
            try:
                self.n.call("PATCH", f"/v1/pages/{page}", {"properties": props(kind, kind, seq, text)})
            except NotionError as e:
                if e.code not in (400, 404):
                    raise
                page = None   # 那一行被删了，重建
        if not page:
            r = self.n.call("POST", "/v1/pages", {"parent": {"database_id": self.db}, "properties": props(kind, kind, seq, text)})
            self.st[key + "_page"] = r["id"]
        self.st[key + "_hash"], self.st[key + "_seq"] = h, seq
        self.save()
        return True

    def push_roster(self):
        r = load_roster(strict=False)
        if not r.get("bots"):
            return False
        return self.upsert("roster", "名单", json.dumps(r, ensure_ascii=False, separators=(",", ":")))

    def push_slots(self):
        o = read_slots()
        if not o:
            return False
        return self.upsert("slots", "工位", json.dumps({"slots": o["slots"], "updatedAt": o.get("updatedAt"), "by": o.get("by")}, ensure_ascii=False))

    def handle_swaps(self):
        if time.monotonic() - self.last_swap < SWAP_EVERY:
            return 0
        self.last_swap = time.monotonic()
        rows = self.n.query(self.db, {"filter": {"and": [{"property": "类型", "select": {"equals": "换人"}},
                                                          {"property": "状态", "select": {"equals": "待处理"}}]},
                                       "sorts": [{"timestamp": "created_time", "direction": "ascending"}]})
        done = 0
        names = {b.get("name") for b in load_roster(strict=False).get("bots", []) if isinstance(b, dict)}
        for r in rows:
            verdict = "已拒绝"
            try:
                o = json.loads(plain(r["properties"].get("数据")))
                a = o.get("slots")
                if valid_slots(a, names):
                    if o.get("ifEmpty") and read_slots():
                        verdict = "已处理"   # 默认阵容只存第一次
                    else:
                        rec = save_slots(a, o.get("reason"), o.get("ifEmpty"))
                        log(f"换人已存（{rec['by']}）：{'、'.join(a)}")
                        verdict = "已处理"
                else:
                    log("换人请求被拒：名字不在名单里、有重复或数量不对")
            except Exception as e:
                log(f"换人请求读不懂：{type(e).__name__}")
            self.n.call("PATCH", f"/v1/pages/{r['id']}", {"properties": {"状态": {"select": {"name": verdict}}}, "archived": True})
            done += 1
        return done

    def step(self):
        a = self.handle_swaps()
        b = self.push_slots()
        c = self.push_roster()
        d = self.push_events()
        return a or b or c or d


def cmd_sync(args):
    os.makedirs(STATE, exist_ok=True)
    lockf = open(LOCK, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("已经有一个同步在跑", flush=True)
        return 0
    told = None
    while True:
        token, db = read_token(), database_id()
        if not token or not db:
            why = "缺少 Notion 连接密钥" if not token else "缺少表 ID（config.json）"
            if told != why:
                log(f"等待：{why}。先运行 liveboard.py init")
                told = why
            status(ok=False, why=why)
            if args.once:
                return 2
            time.sleep(30)
            continue
        try:
            n = Notion(token)
            s = Sync(n, db)
            log("已连上 Notion，开始同步")
            told, last_ok = None, 0
            while True:
                changed = s.step()
                if changed or time.monotonic() - last_ok > 30:
                    status(ok=True, events=len(s.st["ids"]), seq=s.st["seq"], requests=n.count)
                    last_ok = time.monotonic()
                if args.once:
                    s.last_swap = 0
                    while s.step():
                        s.last_swap = 0
                    status(ok=True, events=len(s.st["ids"]), seq=s.st["seq"], requests=n.count)
                    log(f"同步完成：共 {len(s.st['ids'])} 条事件，序号 {s.st['seq']}，请求 {n.count} 次")
                    return 0
                if read_token() != token or database_id() != db:
                    break   # 密钥或表换了，重连
                time.sleep(0.5)
        except NotionError as e:
            why = WHY.get(e.code, f"Notion 出错 {e.code}")
            if told != why:
                log(f"出错：{why}")
                told = why
            status(ok=False, why=why)
            if args.once:
                return 1
            time.sleep(30)
        except Exception as e:
            log(f"出错：{type(e).__name__}: {str(e)[:200]}")
            status(ok=False, why=type(e).__name__)
            if args.once:
                return 1
            time.sleep(10)


# ---------- init / setup-notion / check ----------
def ask_token(args):
    t = os.environ.get("LIVEBOARD_NOTION_TOKEN", "").strip()
    if args.token_stdin:
        t = sys.stdin.readline().strip()
    if not t and read_token() and not args.new_token:
        return read_token(), False
    if not t:
        if not sys.stdin.isatty():
            die("要粘贴连接密钥：请在终端里运行，或用 --token-stdin 从标准输入读")
        t = getpass.getpass("粘贴 Notion 连接密钥（不会显示）：").strip()
    if not re.match(r"^(ntn_|secret_)[A-Za-z0-9_-]{20,}$", t):
        die("看起来不像 Notion 连接密钥：应该以 ntn_ 或 secret_ 开头")
    return t, True


def verify_token(n):
    try:
        me = n.call("GET", "/v1/users/me")
    except NotionError as e:
        die(WHY.get(e.code, f"Notion 出错 {e.code}"), 1)
    ws = (me.get("bot") or {}).get("workspace_name") or ""
    print(f"密钥有效：连接「{me.get('name') or '未命名'}」" + (f"，工作区「{ws}」" if ws else ""))


def ensure_home():
    os.makedirs(STATE, exist_ok=True)
    os.chmod(HOME, 0o700)
    if not os.path.exists(ROSTER) and os.path.exists(EXAMPLE_ROSTER):
        shutil.copyfile(EXAMPLE_ROSTER, ROSTER)
        print(f"已放一份示例名单：{ROSTER}（改成你自己的成员）")


def save_db(db):
    c = read_json(CONFIG, {}) or {}
    c["database_id"] = db
    write_json(CONFIG, c, 0o644)


def cmd_init(args):
    ensure_home()
    token, fresh = ask_token(args)
    n = Notion(token, retries=3)
    verify_token(n)
    if fresh and not os.environ.get("LIVEBOARD_NOTION_TOKEN"):
        save_token(token)
        print(f"密钥已保存：{TOKEN_FILE}（600 权限）")
    if args.database:
        db = norm_id(args.database)
        if not db:
            die("没认出表的 ID：请粘贴表的链接或 32 位 ID")
        try:
            bad = schema_problems(n.call("GET", f"/v1/databases/{db}"))
        except NotionError as e:
            die(WHY.get(e.code, f"Notion 出错 {e.code}"), 1)
        if bad:
            die("这张表缺少或类型不对的列：" + "、".join(bad), 1)
        save_db(db)
        print(f"表 ID 已保存：{CONFIG}")
    elif not database_id():
        print("还没有表 ID：在 Mac App 的设置向导里建好表后，运行  liveboard.py init --database <表ID>")
        print("或者不用 App：liveboard.py setup-notion --parent <一个已加上连接的页面链接>")
    print("下一步：liveboard.py check，然后 liveboard.py sync")
    return 0


def cmd_setup_notion(args):
    ensure_home()
    token = read_token()
    if not token:
        die("还没有连接密钥：先运行 liveboard.py init")
    parent = norm_id(args.parent)
    if not parent:
        die("没认出页面 ID：请粘贴页面的链接或 32 位 ID")
    n = Notion(token, retries=3)
    try:
        p = n.call("POST", "/v1/pages", {"parent": {"type": "page_id", "page_id": parent},
                                         "properties": {"title": {"title": [{"type": "text", "text": {"content": "实时看板中转"}}]}}})
        d = n.call("POST", "/v1/databases", {"parent": {"type": "page_id", "page_id": norm_id(p["id"])},
                                             "title": [{"type": "text", "text": {"content": "看板数据"}}], "is_inline": True, "properties": SCHEMA})
    except NotionError as e:
        die(WHY.get(e.code, f"Notion 出错 {e.code}") + "（页面要先在 Notion 里 ⋯ → 连接 → 加上你的连接）", 1)
    db = norm_id(d["id"])
    save_db(db)
    print(f"已建好「看板数据」表，表 ID：{db}")
    print("在 Mac App 的设置向导里选「已经有看板数据表了？」，粘贴这个 ID 即可")
    return 0


def cmd_check(args):
    ok = True
    r = load_roster(strict=False)
    probs = roster_problems(r) if r.get("bots") else ["名单是空的或读不了：" + ROSTER]
    for p in probs:
        print(("提醒：" if "提醒" in p else "名单有问题：") + p)
        ok = ok and "提醒" in p
    if r.get("bots"):
        print(f"名单：{len(r['bots'])} 个成员，{len(r.get('stages') or [])} 个流程步骤")
    token, db = read_token(), database_id()
    if not token:
        print("缺少连接密钥：运行 liveboard.py init"); return 1
    if not db:
        print("缺少表 ID：运行 liveboard.py init --database <表ID>"); return 1
    n = Notion(token, retries=3)
    try:
        n.call("GET", "/v1/users/me")
        bad = schema_problems(n.call("GET", f"/v1/databases/{db}"))
    except NotionError as e:
        print("Notion：" + WHY.get(e.code, f"出错 {e.code}")); return 1
    if bad:
        print("表结构不对，缺少：" + "、".join(bad)); return 1
    print("Notion：密钥有效，表结构正确")
    st = read_json(STATUS)
    if st:
        print(f"上次同步状态（{st.get('at')}）：" + ("正常" if st.get("ok") else f"出错：{st.get('why')}"))
    return 0 if ok else 1


# ---------- 打卡 ----------
def ulid():
    ms = int(time.time() * 1000)
    t = "".join(B32[(ms >> (5 * i)) & 31] for i in reversed(range(10)))
    r = secrets.randbits(80)
    return t + "".join(B32[(r >> (5 * i)) & 31] for i in reversed(range(16)))


def resolve(name, names, field):
    n = name.strip()
    if n in names:
        return n
    hits = [x for x in names if (len(n) >= 2 and n in x)]
    if len(hits) == 1:
        return hits[0]
    die(f"{field} 不认识：{name}。可用：{'、'.join(names)}")


def parse_ts(raw):
    t = raw.strip()
    if not TS_RE.match(t):
        die(f"--ts 格式不对：{raw}。要写成 2026-01-31T08:30 或 2026-01-31T08:30:00+00:00")
    try:
        d = datetime.fromisoformat(t.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        die(f"--ts 不是有效的日期时间：{raw}")
    now = now_local()
    if d.tzinfo is None:
        d = d.replace(tzinfo=now.tzinfo)
    if d > now + timedelta(minutes=AHEAD_MIN):
        die(f"--ts 在未来：{raw}。补记只能补已经发生的事")
    if d < now - timedelta(days=BACK_DAYS):
        die(f"--ts 太早：{raw}。只能补 {BACK_DAYS} 天以内的事")
    return d.isoformat(timespec="seconds")


def append_event(ev):
    os.makedirs(HOME, exist_ok=True)
    line = json.dumps(ev, ensure_ascii=False) + "\n"
    with open(EVENTS, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)


def cmd_ev(args):
    names = [b["name"] for b in load_roster()["bots"] if isinstance(b, dict) and b.get("name")]
    typ = TYPE_ALIAS.get(args.type.lower(), args.type)
    if typ not in TYPES:
        die(f"类型只能是：{' '.join(TYPES)}（收到：{args.type}）")
    source = SOURCES.get(args.source)
    if not source:
        die(f"--source 只能是 打卡 或 补记（收到：{args.source}）")
    if args.ts and source != "backfill":
        die("--ts 只有补记才能用：… --source 补记 --ts <时间>")
    if source == "backfill" and not args.ts:
        die("补记要写 --ts <时间>，例如 --ts 2026-01-31T08:30")
    ts = parse_ts(args.ts) if args.ts else now_local().isoformat(timespec="seconds")
    bot = resolve(args.bot, names, "--bot")
    to = resolve(args.to, names, "--to") if args.to else None
    if typ in ("交接", "退回") and not to:
        die("交接和退回要写 --to <对方>")
    msg = " ".join(args.msg.split())
    if not msg:
        die("--msg 不能为空")
    if len(msg) > MSG_MAX:
        die(f"--msg 最多 {MSG_MAX} 个字（现在 {len(msg)} 个），写一句话就好")
    project = (args.project or "").strip().strip("/").split("/")[-1] or None
    texts = [msg, project or "", args.task or ""] + args.file
    if any(looks_secret(x) for x in texts):
        die("内容里像有密钥或密码，不能写进日志")
    gate = args.gate.strip() if args.gate else None
    if gate and not GATE.match(gate):
        die("--gate 只能是 1–16 个字母、数字或 _ . -")
    files = []
    for f in args.file:
        if not os.path.exists(os.path.expanduser(f)):
            die(f"--file 不存在：{f}")
        files.append(os.path.basename(os.path.normpath(f)))   # 只记文件名：完整路径可能带用户名、目录结构
    ev = {"v": 1, "id": ulid(), "ts": ts, "bot": bot, "type": typ, "project": project, "task_id": args.task or None,
          "to": to, "gate": gate, "message": msg, "files": files, "source": source}
    if args.test:
        ev["test"] = True
    append_event(ev)
    print(f"已记：{ev['ts'][11:16]} {bot} {typ}{(' → ' + to) if to else ''}：{msg}")
    return 0


def cmd_log(args):
    if not os.path.exists(EVENTS):
        print("（还没有事件）")
        return 0
    with open(EVENTS, encoding="utf-8") as f:
        lines = f.read().splitlines()[-args.n:]
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        tag = "测试" if e.get("test") else {"cli": "打卡", "backfill": "补记"}.get(e.get("source"), "推断")
        to = f" → {e['to']}" if e.get("to") else ""
        print(f"{e['ts'][11:16]}  {e['bot']}  {e['type']}{to}  {e['message']}  [{tag}]")
    return 0


def cmd_roster(args):
    r = load_roster()
    print("成员：" + "、".join(b.get("name", "?") for b in r["bots"]))
    if r.get("stages"):
        print("流程：" + " → ".join(r["stages"]))
    print("类型：" + " ".join(TYPES))
    return 0


# ---------- 本机预览服务 ----------
def read_events():
    out = []
    try:
        with open(EVENTS, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("id") and not e.get("test"):
                    out.append(e)
    except OSError:
        pass
    return out


class Preview(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/roster":
            return self.send(200, load_roster(strict=False))
        if path == "/api/events":
            return self.send(200, read_events())
        if path == "/__board/slots":
            o = read_slots()
            return self.send(200, o if o else {"slots": None})
        if path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = set()
            try:
                evs = read_events()
                seen.update(e["id"] for e in evs)
                self.wfile.write(f"event: init\ndata: {json.dumps(evs, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                while True:
                    time.sleep(1)
                    for e in read_events():
                        if e["id"] not in seen:
                            seen.add(e["id"])
                            self.wfile.write(f"event: ev\ndata: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        self.send(404, {"error": "not found"})

    def do_PUT(self):
        if self.path.split("?")[0] != "/__board/slots" or self.headers.get("X-Live-Board") != "1":
            return self.send(404, {"error": "not found"})
        try:
            o = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        names = {b.get("name") for b in load_roster(strict=False).get("bots", []) if isinstance(b, dict)}
        if not valid_slots(o.get("slots"), names):
            return self.send(400, {"error": f"slots 要是 {SLOT_N} 个不重复、名单里有的名字"})
        cur = read_slots()
        if o.get("ifEmpty") and cur:
            return self.send(200, dict(cur, kept=True))
        return self.send(200, save_slots(o["slots"], o.get("reason"), o.get("ifEmpty")))


def cmd_serve(args):
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Preview)
    srv.daemon_threads = True
    log(f"本机预览服务：http://127.0.0.1:{args.port}（只给 board/ 的 npm run dev 用；按 Ctrl+C 停止）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="liveboard.py", description="实时看板写入端", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("init", help="保存连接密钥和表 ID")
    s.add_argument("--database")
    s.add_argument("--token-stdin", action="store_true", help="从标准输入读一行密钥（脚本里用）")
    s.add_argument("--new-token", action="store_true", help="已经存过密钥也重新输入")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("setup-notion", help="在一个页面里建中转页和看板表")
    s.add_argument("--parent", required=True)
    s.set_defaults(fn=cmd_setup_notion)
    sub.add_parser("check", help="检查设置").set_defaults(fn=cmd_check)
    s = sub.add_parser("ev", help="打卡")
    s.add_argument("type")
    s.add_argument("--bot", required=True)
    s.add_argument("--project")
    s.add_argument("--msg", "--message", dest="msg", required=True)
    s.add_argument("--to")
    s.add_argument("--task")
    s.add_argument("--gate")
    s.add_argument("--file", action="append", default=[])
    s.add_argument("--test", action="store_true")
    s.add_argument("--source", default="打卡")
    s.add_argument("--ts")
    s.set_defaults(fn=cmd_ev)
    s = sub.add_parser("log", help="最近的事件")
    s.add_argument("n", nargs="?", type=int, default=10)
    s.set_defaults(fn=cmd_log)
    sub.add_parser("roster", help="名单").set_defaults(fn=cmd_roster)
    s = sub.add_parser("sync", help="同步到 Notion")
    s.add_argument("--once", action="store_true")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("serve", help="本机预览服务")
    s.add_argument("--port", type=int, default=4380)
    s.set_defaults(fn=cmd_serve)
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 0
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
