#!/usr/bin/env python3
"""自测用的本机假 Notion，只实现本项目用到的接口，不接触任何真实数据。

    python3 notion_mock.py <端口>       环境变量：MOCK_TOKEN（必填）、MOCK_DB（预置一张看板表的 ID，可选）、
                                        MOCK_LAG（新行几秒后才查得到，默认 0.5）、MOCK_RATE（每秒最多几次，默认 3）
接口：
- GET  /v1/users/me                         验证密钥
- POST /v1/search                           列出已共享给这个连接的页面（filter object=page）
- POST /v1/pages                            新建页面：parent 是 page_id（建中转页）或 database_id（加一行）
- PATCH /v1/pages/{id}                      改行（properties、archived）
- POST /v1/databases                        在页面下建表
- GET  /v1/databases/{id}                   读表结构
- POST /v1/databases/{id}/query             filter: select equals / does_not_equal、number greater_than、and / or；sorts；分页
- GET  /__stats                             请求数、429 次数（测试用）；/__stats/reset 清零；/__rows/{表ID} 看全部行
照真实 Notion 的限制：每段文字 ≤2000 字、≤100 段；超过 MOCK_RATE 次/秒回 429；新建的行 LAG 秒后才能被查到。
"""
import json, os, re, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]); TOKEN = os.environ["MOCK_TOKEN"]
LAG = float(os.environ.get("MOCK_LAG", "0.5")); RATE = float(os.environ.get("MOCK_RATE", "3"))
rows, dbs, docs = {}, {}, {}          # 表里的行 / 表 / 普通页面
lock, hits = threading.Lock(), []
stats = {"requests": 0, "r429": 0, "max_per_sec": 0, "by_path": {}}
nid = lambda: uuid.uuid4().hex
dash = lambda h: f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
norm = lambda s: str(s or "").replace("-", "").lower()

# 预置：一个已经共享给连接的示例页面；MOCK_DB 给了就再预置一张看板表
SHARED = nid(); docs[SHARED] = {"id": SHARED, "title": "示例工作区首页", "parent": None}
if os.environ.get("MOCK_DB"):
    dbs[norm(os.environ["MOCK_DB"])] = {"title": "看板数据", "parent": SHARED, "properties": {
        "名称": {"type": "title", "title": {}}, "类型": {"type": "select", "select": {"options": []}},
        "序号": {"type": "number", "number": {}}, "数据": {"type": "rich_text", "rich_text": {}}, "状态": {"type": "select", "select": {"options": []}}}}

def fmt_prop(v):
    if "title" in v: return {"type": "title", "title": [dict(x, plain_text=x["text"]["content"]) for x in v["title"]]}
    if "rich_text" in v: return {"type": "rich_text", "rich_text": [dict(x, plain_text=x["text"]["content"]) for x in v["rich_text"]]}
    if "select" in v: return {"type": "select", "select": v["select"]}
    if "number" in v: return {"type": "number", "number": v["number"]}
    return v
def check_text(props):
    for k, v in props.items():
        arr = v.get("title") or v.get("rich_text")
        if arr is None: continue
        if len(arr) > 100: return f"{k}: more than 100 items"
        for x in arr:
            if len(x["text"]["content"]) > 2000: return f"{k}: text over 2000"
    return None
def match(p, f):
    if not f: return True
    if "and" in f: return all(match(p, x) for x in f["and"])
    if "or" in f: return any(match(p, x) for x in f["or"])
    v = p["properties"].get(f["property"], {})
    if "select" in f:
        name = (v.get("select") or {}).get("name")
        if "equals" in f["select"]: return name == f["select"]["equals"]
        if "does_not_equal" in f["select"]: return name != f["select"]["does_not_equal"]
    if "number" in f:
        n = v.get("number")
        if "greater_than" in f["number"]: return n is not None and n > f["number"]["greater_than"]
    raise ValueError("filter not supported")
pub = lambda p: {k: v for k, v in p.items() if not k.startswith("_")}
def db_obj(i):
    d = dbs[i]
    return {"object": "database", "id": dash(i), "title": [{"type": "text", "text": {"content": d["title"]}, "plain_text": d["title"]}],
            "parent": {"type": "page_id", "page_id": dash(d["parent"])}, "properties": {k: dict(v, name=k) for k, v in d["properties"].items()}}
def page_obj(i):
    d = docs[i]
    return {"object": "page", "id": dash(i), "parent": {"type": "page_id", "page_id": dash(d["parent"])} if d["parent"] else {"type": "workspace", "workspace": True},
            "properties": {"title": {"type": "title", "title": [{"type": "text", "text": {"content": d["title"]}, "plain_text": d["title"]}]}},
            "url": "https://www.notion.so/" + i}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj, extra=None):
        b = json.dumps(obj, ensure_ascii=False).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def gate(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send(401, {"object": "error", "status": 401, "code": "unauthorized", "message": "API token is invalid."}); return False
        now = time.time()
        with lock:
            stats["requests"] += 1
            key = self.command + " " + re.sub(r"[0-9a-f]{32}|[0-9a-f-]{36}", "{id}", self.path)
            stats["by_path"][key] = stats["by_path"].get(key, 0) + 1
            hits.append(now)
            while hits and hits[0] < now - 1: hits.pop(0)
            stats["max_per_sec"] = max(stats["max_per_sec"], len(hits))
            if len(hits) > RATE: stats["r429"] += 1; self.send(429, {"code": "rate_limited"}, {"Retry-After": "1"}); return False
        return True
    def body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n) or b"{}")
    def parts(self): return self.path.split("?")[0].strip("/").split("/")
    def nf(self): return self.send(404, {"object": "error", "status": 404, "code": "object_not_found", "message": "Could not find object."})

    def do_GET(self):
        if self.path == "/__stats":
            with lock: return self.send(200, dict(stats, rows=sum(1 for p in rows.values() if not p["archived"]), all=len(rows), dbs=len(dbs)))
        if self.path == "/__stats/reset":
            with lock: stats.update(requests=0, r429=0, max_per_sec=0, by_path={}); hits.clear(); return self.send(200, {"ok": True})
        if self.path.startswith("/__rows/"):   # 测试用：某张表的全部行（含已归档），不计入限流
            d = self.path[len("/__rows/"):].replace("-", "")
            with lock: return self.send(200, [{k: v for k, v in p.items() if not k.startswith("_")} for p in rows.values() if p["_db"] == d])
        if not self.gate(): return
        pt = self.parts()
        if pt == ["v1", "users", "me"]:
            return self.send(200, {"object": "user", "id": dash(nid()), "type": "bot", "name": "示例连接", "bot": {"owner": {"type": "workspace", "workspace": True}, "workspace_name": "示例工作区"}})
        if pt[:2] == ["v1", "databases"] and len(pt) == 3:
            i = norm(pt[2])
            return self.send(200, db_obj(i)) if i in dbs else self.nf()
        self.nf()

    def do_POST(self):
        if not self.gate(): return
        b = self.body(); pt = self.parts()
        if pt == ["v1", "search"]:
            f = (b.get("filter") or {}).get("value")
            res = [page_obj(i) for i, d in docs.items() if not d.get("private")] if f in (None, "page") else []
            if f in (None, "database"): res += [db_obj(i) for i in dbs]
            return self.send(200, {"object": "list", "results": res, "has_more": False, "next_cursor": None})
        if pt == ["v1", "databases"]:
            par = norm((b.get("parent") or {}).get("page_id"))
            if par not in docs or docs[par].get("private"): return self.nf()
            props = b.get("properties") or {}
            if sum(1 for v in props.values() if "title" in v) != 1: return self.send(400, {"code": "validation_error", "message": "need one title property"})
            i = nid()
            with lock:
                dbs[i] = {"title": "".join(x["text"]["content"] for x in b.get("title") or []), "parent": par,
                          "properties": {k: dict(v, type=next(iter(v))) for k, v in props.items()}}
            return self.send(200, db_obj(i))
        if pt[:2] == ["v1", "databases"] and pt[3:] == ["query"]:
            i = norm(pt[2])
            if i not in dbs: return self.nf()
            now = time.time()
            with lock:
                out = [p for p in rows.values() if p["_db"] == i and not p["archived"] and p["_vis"] <= now and match(p, b.get("filter"))]
            for s in reversed(b.get("sorts") or []):
                if s.get("timestamp") == "created_time": key = lambda p: p["_ct"]
                else: key = lambda p, k=s["property"]: (p["properties"].get(k, {}).get("number") or 0)
                out.sort(key=key, reverse=s.get("direction") == "descending")
            start = int(b.get("start_cursor") or 0); size = min(100, b.get("page_size") or 100)
            sl = out[start:start + size]; more = start + size < len(out)
            return self.send(200, {"object": "list", "results": [pub(p) for p in sl], "has_more": more, "next_cursor": str(start + size) if more else None})
        if pt == ["v1", "pages"]:
            par = b.get("parent") or {}
            if "page_id" in par:
                pp = norm(par["page_id"])
                if pp not in docs or docs[pp].get("private"): return self.nf()
                t = "".join(x["text"]["content"] for x in (b.get("properties", {}).get("title", {}).get("title") or []))
                i = nid()
                with lock: docs[i] = {"id": i, "title": t, "parent": pp}
                return self.send(200, page_obj(i))
            d = norm(par.get("database_id"))
            if d not in dbs: return self.nf()
            for k in b.get("properties", {}):
                if k not in dbs[d]["properties"]: return self.send(400, {"code": "validation_error", "message": f"{k} is not a property that exists."})
            err = check_text(b.get("properties", {}))
            if err: return self.send(400, {"code": "validation_error", "message": err})
            pid = str(uuid.uuid4()); now = time.time()
            p = {"object": "page", "id": pid, "created_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + ".%03dZ" % int(now % 1 * 1000), "archived": False, "properties": {k: fmt_prop(v) for k, v in b["properties"].items()}, "_ct": now, "_vis": now + LAG, "_db": d}
            with lock: rows[pid] = p
            return self.send(200, pub(p))
        self.nf()

    def do_PATCH(self):
        if not self.gate(): return
        b = self.body(); pt = self.parts()
        if pt[:2] == ["v1", "pages"] and len(pt) == 3:
            with lock:
                p = rows.get(pt[2])
                if not p: return self.nf()
                err = check_text(b.get("properties", {}))
                if err: return self.send(400, {"code": "validation_error", "message": err})
                for k, v in (b.get("properties") or {}).items(): p["properties"][k] = fmt_prop(v)
                if "archived" in b: p["archived"] = bool(b["archived"])
                return self.send(200, pub(p))
        self.nf()

ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
