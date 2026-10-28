#!/usr/bin/env python3
"""自测用：在浏览器里扮演 Mac App 的原生层（规则照 app/LiveBoard/Policy.swift 和 main.swift）。
- 提供组装好的网页资源（scripts/build-app.sh --stage-only 生成的 dist/stage/board，和 App 里的一模一样）
- index.html 加载前注入 window.__LIVEBOARD_CFG（App 里由 WKUserScript 注入）
- 界面语言（照 Lang.swift）：选了简体中文 / English 时，index.html 和 setup.html 加载前注入 window.__LIVEBOARD_LANG；跟随系统时不注入，网页按浏览器语言
- /__notion/*：看板通道，只放行「查这张表」「在这张表里加换人行」，密钥由这里加，网页拿不到
- /__setup：设置向导通道（op: state / token / notion / choose / open / copy / lang / finish），notion 只放行这次向导用到的页面 / 表，finish 后把密钥和表 ID 存进 HARNESS_HOME
用法：python3 app_harness.py <端口> <网页目录>
环境变量：HARNESS_API（Notion 地址）、HARNESS_HOME（模拟 ~/Library/Application Support/LiveBoard）、HARNESS_PENDING_TTL_MS（可选）
"""
import json, os, re, sys, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, ROOT = int(sys.argv[1]), os.path.abspath(sys.argv[2])
API = os.environ["HARNESS_API"].rstrip("/"); HOME = os.environ["HARNESS_HOME"]
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".glb": "model/gltf-binary",
         ".woff2": "font/woff2", ".woff": "font/woff", ".json": "application/json"}
os.makedirs(HOME, exist_ok=True)
pending = {"token": None}
calls = {"open": [], "copy": [], "lang": "system"}
WEB_LANG = {"zh-Hans": "zh", "en": "en"}
ERR = {"表 ID 不对": "Invalid table ID", "这张表不是这次设置里选的": "This table wasn't chosen in this setup", "还没有密钥": "No token yet",
       "设置没存进去": "Couldn't save the settings", "密钥没存进去": "Couldn't save the token"}
def err(zh): return ERR[zh] if calls["lang"] == "en" else zh
HEX32 = re.compile(r"^[0-9a-f]{32}$")
def norm(s):
    h = str(s or "").replace("-", "").lower()
    return h if HEX32.match(h) else None
def token():
    try: return open(os.path.join(HOME, "notion_token")).read().strip() or None
    except OSError: return None
def cfg():
    try: return json.load(open(os.path.join(HOME, "config.json")))
    except Exception: return {}
def db(): return norm(cfg().get("database_id")) or ""
def board_allowed(m, p, body):
    d = db()
    if not d: return False
    if m == "POST" and p == f"/v1/databases/{d}/query": return True
    if m == "POST" and p == "/v1/pages":
        try:
            o = json.loads(body)
            return norm(o["parent"]["database_id"]) == d and o["properties"]["类型"]["select"]["name"] == "换人"
        except Exception: return False
    return False
# 设置向导这一次打开期间的放行范围（照 Policy.swift 的 SetupScope）；打开 setup.html 时清空
scope = {"pages": set(), "relay": None, "table": None}
def scope_reset(): scope.update(pages=set(), relay=None, table=None)
def jobj(s):
    try:
        o = json.loads(s); return o if isinstance(o, dict) else None
    except Exception: return None
def setup_allowed(m, p, body):
    if m == "GET" and p == "/v1/users/me": return True
    if m == "POST" and p == "/v1/search":
        f = (jobj(body) or {}).get("filter")
        return isinstance(f, dict) and f.get("property") == "object" and f.get("value") == "page"
    if m == "GET" and p.startswith("/v1/databases/"):
        return scope["table"] is not None and norm(p[len("/v1/databases/"):]) == scope["table"]
    if m == "POST" and p in ("/v1/pages", "/v1/databases"):
        o = jobj(body)
        if not o or "children" in o or not isinstance(o.get("parent"), dict): return False
        pid = norm(o["parent"].get("page_id"))
        if not pid: return False
        return pid in scope["pages"] if p == "/v1/pages" else pid == scope["relay"]
    return False
def scope_record(m, p, code, txt):
    o = jobj(txt) if code == 200 else None
    if not o: return
    if m == "POST" and p == "/v1/search":
        for r in o.get("results") or []:
            if isinstance(r, dict) and r.get("object") == "page" and norm(r.get("id")): scope["pages"].add(norm(r.get("id")))
    elif m == "POST" and p == "/v1/pages" and o.get("object") == "page": scope["relay"] = norm(o.get("id"))
    elif m == "POST" and p == "/v1/databases" and o.get("object") == "database": scope["table"] = norm(o.get("id"))
def write_secret(path, text):
    """先写同目录临时文件（600），再原子替换（照 Store.swift 的 writeSecretFile）"""
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.{os.urandom(6).hex()}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f: f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path); return True
    except OSError:
        try: os.unlink(tmp)
        except OSError: pass
        return False
def notion(m, p, body, tok):
    req = urllib.request.Request(API + p, data=body.encode() if body and m != "GET" else None, method=m,
                                 headers={"Authorization": "Bearer " + tok, "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()
    except Exception: return 0, '{"code":"network"}'

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, data, ctype="application/json"):
        if isinstance(data, (dict, list)): data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache"); self.end_headers(); self.wfile.write(data)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return self.rfile.read(n).decode() if n else ""
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/__calls": return self.send(200, calls)
        if p in ("", "/"): p = "/index.html"
        if p == "/setup.html": scope_reset()   # 和 App 一样：每次打开向导都从零开始
        f = os.path.abspath(os.path.join(ROOT, p.lstrip("/")))
        if not f.startswith(ROOT + "/") or not os.path.isfile(f): return self.send(404, b"not found", "text/plain")
        data = open(f, "rb").read()
        if p == "/index.html":   # 和 App 的 WKUserScript 一样：页面脚本运行前注入设置
            c = {"database_id": db(), "active_ms": 3000, "idle_ms": 30000}
            if os.environ.get("HARNESS_PENDING_TTL_MS"): c["pending_ttl_ms"] = int(os.environ["HARNESS_PENDING_TTL_MS"])
            inj = f"<script>window.__LIVEBOARD_CFG = {json.dumps(c)};</script>\n".encode()
            data = data.replace(b"<head>", b"<head>\n" + inj, 1)
        if p in ("/index.html", "/setup.html") and calls["lang"] in WEB_LANG:
            data = data.replace(b"<head>", b"<head>\n" + f"<script>window.__LIVEBOARD_LANG = {json.dumps(WEB_LANG[calls['lang']])};</script>\n".encode(), 1)
        self.send(200, data, TYPES.get(os.path.splitext(f)[1], "application/octet-stream"))
    def board(self, m):
        body = self.body(); p = self.path[len("/__notion"):]
        if not board_allowed(m, p, body): return self.send(403, b'{"code":"not_allowed"}')
        tok = token()
        if not tok: return self.send(599, b'{"code":"no_token"}')
        code, txt = notion(m, p, body, tok); self.send(code or 502, txt.encode())
    def setup_op(self):
        try: o = json.loads(self.body())
        except ValueError: return self.send(400, {"ok": False})
        op = o.get("op")
        if op == "state": return self.send(200, {"ok": True, "hasToken": token() is not None, "configured": bool(db() and token()), "language": calls["lang"]})
        if op == "lang":   # 照 L10n.preference：不认识的值当跟随系统；回传网页该用的语言（跟随系统时由网页自己看浏览器语言）
            v = o.get("value"); calls["lang"] = v if v in WEB_LANG else "system"
            return self.send(200, {"ok": True, "language": calls["lang"], "lang": WEB_LANG.get(calls["lang"])})
        if op == "token":
            if o.get("useSaved"): pending["token"] = None; return self.send(200, {"ok": token() is not None})
            t = str(o.get("token") or "").strip(); ok = bool(t) and len(t) < 300 and not re.search(r"\s", t)
            if ok: pending["token"] = t
            return self.send(200, {"ok": ok})
        if op == "notion":
            m, p, body = o.get("method", ""), o.get("path", ""), o.get("body", "")
            if not setup_allowed(m, p, body): return self.send(200, {"status": 403, "body": '{"code":"not_allowed"}'})
            tok = pending["token"] or token()
            if not tok: return self.send(200, {"status": 0, "body": '{"code":"no_token"}'})
            code, txt = notion(m, p, body, tok); scope_record(m, p, code, txt)
            return self.send(200, {"status": code, "body": txt})
        if op == "choose":
            d = norm(o.get("database_id"))
            if d: scope["table"] = d
            return self.send(200, {"ok": bool(d)})
        if op == "open": calls["open"].append(o.get("url")); return self.send(200, {"ok": True})
        if op == "copy": calls["copy"].append(o.get("text")); return self.send(200, {"ok": True})
        if op == "finish":   # 照 Store.commitSetup：先写设置，再提交密钥，密钥存不进去就退回设置
            d = norm(o.get("database_id"))
            if not d: return self.send(200, {"ok": False, "error": err("表 ID 不对")})
            if d != scope["table"]: return self.send(200, {"ok": False, "error": err("这张表不是这次设置里选的")})
            if not (pending["token"] or token()): return self.send(200, {"ok": False, "error": err("还没有密钥")})
            cf = os.path.join(HOME, "config.json")
            try: before = open(cf, "rb").read()
            except OSError: before = None
            c = cfg(); c["database_id"] = d
            if not write_secret(cf, json.dumps(c)): return self.send(200, {"ok": False, "error": err("设置没存进去")})
            if pending["token"] and not write_secret(os.path.join(HOME, "notion_token"), pending["token"] + "\n"):
                if before is None: os.unlink(cf)
                else: write_secret(cf, before.decode())
                return self.send(200, {"ok": False, "error": err("密钥没存进去")})
            pending["token"] = None
            return self.send(200, {"ok": True})
        self.send(200, {"ok": False})
    def do_POST(self):
        if self.path.startswith("/__notion/"): return self.board("POST")
        if self.path == "/__setup": return self.setup_op()
        self.send(405, b"")
    def do_PATCH(self):
        if self.path.startswith("/__notion/"): return self.board("PATCH")
        self.send(405, b"")

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
