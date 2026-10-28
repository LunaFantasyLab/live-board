#!/usr/bin/env python3
"""整套端到端自测（浏览器 + 假 Notion + 写入端），全部在本机临时目录里跑，不碰任何真实数据。
先运行 scripts/build-app.sh --stage-only 生成 dist/stage/board，再：
    python3 tests/e2e.py
截图和记录写到 tests/out/（已在 .gitignore 里）。
"""
import asyncio, json, os, re, secrets, shutil, signal, socket, stat, subprocess, sys, tempfile, time, urllib.request
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "dist", "stage", "board")
CLI = os.path.join(ROOT, "writer", "liveboard.py")
OUT = os.path.join(ROOT, "tests", "out"); os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="liveboard-e2e-")
APP_HOME, W_HOME = os.path.join(TMP, "app"), os.path.join(TMP, "writer")
TOKEN = "ntn_" + secrets.token_hex(23)
R, procs = [], []
# 界面里不该出现的字样（不给 AI 贴标签）
AI_WORDS = re.compile(r"(?<![A-Za-z])AI(?![A-Za-z])|人工智能|智能体|机器人|GPT|Claude|Grok|Gemini|模型生成|自动生成|由.{0,4}生成", re.I)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


MOCKP, HP = free_port(), free_port()
API, BASE = f"http://127.0.0.1:{MOCKP}", f"http://127.0.0.1:{HP}"


def rec(name, ok, detail=""):
    R.append({"项": name, "结果": "PASS" if ok else "FAIL", "说明": detail}); print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def jget(u):
    with urllib.request.urlopen(u, timeout=5) as r: return json.loads(r.read())


def start(cmd, env, log):
    p = subprocess.Popen(cmd, env={**os.environ, **env}, stdout=open(log, "a"), stderr=subprocess.STDOUT, start_new_session=True); procs.append(p); return p


def stop(p):
    try: os.killpg(p.pid, signal.SIGTERM); p.wait(5)
    except Exception: pass


WENV = {"LIVEBOARD_HOME": W_HOME, "NOTION_API_BASE": API}
def cli(*args, stdin=None):
    return subprocess.run([sys.executable, CLI, *args], input=stdin, capture_output=True, text=True, env={**os.environ, **WENV}, timeout=120)


def slots_file():
    try:
        with open(os.path.join(W_HOME, "state", "slots.json")) as f: return json.load(f)
    except Exception: return None


async def wait_until(fn, timeout=30, every=0.25):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v: return v
        await asyncio.sleep(every)
    return None


async def main():
    assert os.path.isfile(os.path.join(WEB, "index.html")), "先运行 scripts/build-app.sh --stage-only"
    start([sys.executable, os.path.join(ROOT, "tests", "notion_mock.py"), str(MOCKP)], {"MOCK_TOKEN": TOKEN, "MOCK_LAG": "0.5", "MOCK_RATE": "3"}, f"{TMP}/mock.log")
    start([sys.executable, os.path.join(ROOT, "tests", "app_harness.py"), str(HP), WEB], {"HARNESS_API": API, "HARNESS_HOME": APP_HOME, "HARNESS_PENDING_TTL_MS": "5000"}, f"{TMP}/harness.log")
    for _ in range(50):
        try: jget(API + "/__stats"); jget(BASE + "/__calls"); break
        except OSError: time.sleep(0.1)
    texts = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        errs = []
        async def newpage(w=1280, h=720, locale="zh-CN"):   # 默认扮演中文系统；I 段测英文
            ctx = await b.new_context(viewport={"width": w, "height": h}, locale=locale); pg = await ctx.new_page(); pg.set_default_timeout(60000)
            pg.on("pageerror", lambda e: errs.append("pageerror " + str(e)))
            pg.on("console", lambda m: m.type == "error" and errs.append("console " + m.text))
            return ctx, pg

        # ---------- A. 还没设置：看板只显示一行说明 ----------
        ctx, pg = await newpage()
        await pg.goto(BASE + "/index.html")
        await pg.wait_for_selector("#relay-notice")
        t = await pg.inner_text("#relay-notice")
        rec("A1 没设置时看板整屏只有一行说明", "缺少看板中转表的设置" in t, t)
        await pg.screenshot(path=f"{OUT}/A1-未设置.png"); await ctx.close()

        # ---------- B. 设置向导：贴密钥 → 当场验证 → 自动建中转页和表 ----------
        ctx, pg = await newpage(680, 620)
        await pg.goto(BASE + "/setup.html")
        texts["setup-1"] = await pg.inner_text("body")
        rec("B1 向导第一步可见，没有保存的密钥时不显示「沿用」", await pg.is_visible("section[data-step='1']") and not await pg.is_visible("#use-saved"))
        await pg.fill("#token", "abc"); await pg.click("#verify")
        t = await pg.inner_text("#msg1"); rec("B2 格式不对的密钥当场拦下", "不像" in t, t)
        await pg.fill("#token", "ntn_" + "0" * 46); await pg.click("#verify")
        await pg.wait_for_function("document.querySelector('#msg1').classList.contains('err')")
        t = await pg.inner_text("#msg1"); rec("B3 错的密钥：Notion 验证不过，明说", "密钥不对" in t, t)
        await pg.fill("#token", TOKEN); await pg.click("#verify")
        await pg.wait_for_selector("section[data-step='2']:not([hidden])")
        who = await pg.inner_text("#who")
        rec("B4 对的密钥：验证通过进第二步，输入框清空", "密钥有效" in who and await pg.evaluate("document.querySelector('#token').value") == "", who)
        await pg.wait_for_selector("#pages li")
        pages = await pg.eval_on_selector_all("#pages li", "els => els.map(e => e.textContent)")
        rec("B5 列出连接能看到的页面", "示例工作区首页" in pages, "、".join(pages))
        texts["setup-2"] = await pg.inner_text("body")
        await pg.screenshot(path=f"{OUT}/B5-选页面.png")
        # 已有表的路径：输错 / 找不到
        await pg.click("#existing")
        await pg.fill("#dbid", "随便写的"); await pg.click("#use-db")
        t = await pg.inner_text("#msg2b"); rec("B6 已有表：认不出 ID 时明说", "没认出" in t, t)
        await pg.fill("#dbid", "f" * 32); await pg.click("#use-db")
        await pg.wait_for_function("document.querySelector('#msg2b').classList.contains('err')")
        t = await pg.inner_text("#msg2b"); rec("B7 已有表：表不存在时明说", "找不到" in t, t)
        # DS-3：设置通道只放行这次向导用到的页面 / 表（网页直接调原生层也越不过去）
        probe = """async ([m, p, b]) => (await (await fetch('/__setup', {method: 'POST', headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({op: 'notion', method: m, path: p, body: b})})).json()).status"""
        other = "e" * 32
        got = [await pg.evaluate(probe, ["GET", f"/v1/databases/{other}", ""]),
               await pg.evaluate(probe, ["POST", "/v1/search", "{}"]),
               await pg.evaluate(probe, ["POST", "/v1/databases", json.dumps({"parent": {"type": "page_id", "page_id": other}, "properties": {}})]),
               await pg.evaluate(probe, ["POST", "/v1/pages", json.dumps({"parent": {"type": "page_id", "page_id": other}, "properties": {}})])]
        rec("B12 设置通道：没选的表不许读结构、不许不带过滤搜索、不许在没列出的页面下建页面或表", got == [403] * 4, str(got))
        # 新建
        await pg.click("#pages li >> text=示例工作区首页"); await pg.click("#create")
        await pg.wait_for_function("!document.querySelector(\"section[data-step='3']\").hidden || document.querySelector('#msg2').classList.contains('err')")
        if not await pg.is_visible("section[data-step='3']"): raise RuntimeError("新建失败：" + await pg.inner_text("#msg2"))
        db = (await pg.inner_text("#db-out")).strip(); cmd = await pg.inner_text("#cmd-out")
        st = jget(API + "/__stats")
        rec("B8 自动建好「实时看板中转」页和「看板数据」表", bool(re.fullmatch(r"[0-9a-f]{32}", db)) and st["dbs"] == 1 and db in cmd, f"表 ID {db[:4]}…；命令：{cmd.replace(db, '<表ID>')}")
        texts["setup-3"] = await pg.inner_text("body")
        await pg.screenshot(path=f"{OUT}/B8-完成.png")
        await pg.click("#copy-cmd"); await pg.wait_for_function("document.querySelector('#msg3').textContent === '已复制'")
        rec("B9 「复制命令」交给原生层复制", jget(BASE + "/__calls")["copy"] == [cmd])
        bad = await pg.evaluate("""async (id) => (await (await fetch('/__setup', {method: 'POST', headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({op: 'finish', database_id: id})})).json())""", "e" * 32)
        rec("B13 完成时只接受这次向导建的 / 选的那张表", bad.get("ok") is False and not os.path.exists(os.path.join(APP_HOME, "config.json")), str(bad))
        await pg.click("#finish"); await pg.wait_for_function("document.querySelector('#msg3').textContent === '已保存'")
        tf = os.path.join(APP_HOME, "notion_token")
        with open(os.path.join(APP_HOME, "config.json")) as f: c = json.load(f)
        with open(tf) as f: saved = f.read().strip()
        rec("B10 完成：表 ID 存进 config.json，密钥存成只有自己能读的文件", c.get("database_id") == db and saved == TOKEN and stat.S_IMODE(os.stat(tf).st_mode) == 0o600)
        html = await pg.content()
        rec("B11 网页里任何地方都没有密钥", TOKEN not in html and TOKEN not in await pg.evaluate("JSON.stringify(localStorage)"))
        await ctx.close()

        # ---------- C. 写入端接上同一张表 ----------
        r = cli("init", "--database", db, "--token-stdin", stdin=TOKEN + "\n")
        rec("C1 写入端 init（自动放好示例名单）", r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "")
        for bot, typ, msg in [("调度", "交接", "新任务"), ("研究员", "接单", "收到"), ("研究员", "产出", "选题清单"), ("写手", "开始", "开始写"), ("审核员", "待确认", "请看初稿")]:
            extra = ["--to", "研究员"] if typ == "交接" else []
            r = cli("ev", typ, "--bot", bot, "--project", "示例任务", "--msg", msg, *extra); assert r.returncode == 0, r.stderr
        r = cli("check"); rec("C2 check 通过", r.returncode == 0, " / ".join(r.stdout.strip().splitlines()))
        sync = start([sys.executable, CLI, "sync"], WENV, f"{TMP}/sync.log")

        # ---------- D. 看板实况 ----------
        ctx, pg = await newpage()
        LABELS = "() => [...document.querySelectorAll('.labels .lab:not([hidden])')].map(e => e.dataset.bot)"
        t0 = time.time(); await pg.goto(BASE + "/index.html")
        try:
            await pg.wait_for_function("document.querySelector('#conn span')?.textContent.startsWith('实况')", timeout=60000)
            await pg.wait_for_function("document.querySelectorAll('.labels .lab:not([hidden])').length === 6", timeout=60000)
        except Exception:
            dump = await pg.evaluate("() => ({conn: document.querySelector('#conn')?.innerText, labs: document.querySelectorAll('.labels .lab').length, shown: document.querySelectorAll('.labels .lab:not([hidden])').length, notice: document.querySelector('#relay-notice')?.textContent, stats: window.__relay?.stats})")
            await pg.screenshot(path=f"{OUT}/D-失败.png")
            raise RuntimeError(f"看板没就绪：{json.dumps(dump, ensure_ascii=False)}；{errs[:3]}")
        labs = await pg.evaluate(LABELS)
        rec("D1 打开就是实况、六个工位", len(labs) == 6, f"{time.time()-t0:.1f} 秒；{'、'.join(labs)}")
        h1 = await pg.inner_text(".top h1"); rec("D2 标题来自名单", "示例团队" in h1.replace("\n", ""), h1.replace("\n", ""))
        await pg.wait_for_function("Number(document.querySelector('#logn').textContent) === 5", timeout=30000)
        rec("D3 事件条数和写入端一致", True, "5 条")
        sf = await wait_until(slots_file, 30)
        rec("D4 第一次打开：默认六位经 Notion 存进写入端 state/slots.json", bool(sf) and sorted(sf["slots"]) == sorted(labs), "、".join((sf or {}).get("slots") or []))
        await pg.screenshot(path=f"{OUT}/D1-实况.png")
        # 新事件
        t1 = time.time(); cli("ev", "产出", "--bot", "画师", "--project", "示例任务", "--msg", "封面三版")
        await pg.wait_for_function("[...document.querySelectorAll('#log li')].some(li => li.textContent.includes('封面三版'))", timeout=30000)
        rec("D5 新打卡自动出现在看板上", True, f"{time.time()-t1:.1f} 秒")
        # 空闲动画：没人操作时场景也一直在画；小窗收起（页面不可见）再弹出后要接着动
        FR = "window.__boardStats ? window.__boardStats.frames : -1"
        f0 = await pg.evaluate(FR); await asyncio.sleep(1.0); f1 = await pg.evaluate(FR)
        await pg.evaluate("""h => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => h}); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => h ? 'hidden' : 'visible'}); document.dispatchEvent(new Event('visibilitychange')); }""", True)
        await asyncio.sleep(0.5); f2 = await pg.evaluate(FR); await asyncio.sleep(0.5); f3 = await pg.evaluate(FR)
        await pg.evaluate("""h => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => h}); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => h ? 'hidden' : 'visible'}); document.dispatchEvent(new Event('visibilitychange')); }""", False)
        await asyncio.sleep(1.0); f4 = await pg.evaluate(FR)
        rec("D8 空闲时场景持续在画；收起时停画，再弹出后恢复", f1 - f0 > 5 and f3 - f2 <= 1 and f4 - f3 > 5, f"空闲 1 秒 {f1-f0} 帧；收起 0.5 秒 {f3-f2} 帧；弹出后 1 秒 {f4-f3} 帧")
        # 背景呼吸：红色放射条纹极慢地转 ±1.5°、微缩放、明暗起伏（16 秒一周期，缓入缓出）；「减少动态效果」打开时不动
        RS = "(() => { const e = document.querySelector('.rays'), c = getComputedStyle(e), a = getComputedStyle(e, '::after'); return {tf: c.transform, op: a.opacity, name: c.animationName, dur: parseFloat(c.animationDuration), ease: c.animationTimingFunction, it: c.animationIterationCount}; })()"
        r0 = await pg.evaluate(RS); await asyncio.sleep(1.0); r1 = await pg.evaluate(RS)
        rec("D9 背景放射条纹在慢慢呼吸（transform / 明暗 1 秒内有变化，周期 12–20 秒，缓入缓出）", r0["tf"] != r1["tf"] and r0["op"] != r1["op"] and 12 <= r0["dur"] <= 20 and r0["ease"] == "ease-in-out" and r0["it"] == "infinite", f"{r0['name']} {r0['dur']}s {r0['ease']}；transform {r0['tf']} → {r1['tf']}；暗罩 {r0['op']} → {r1['op']}")
        # 换人
        new = [n for n in labs[:5]] + ["数据员"]
        t2 = time.time()
        code = await pg.evaluate("s => fetch('/__board/slots', {method:'PUT', headers:{'Content-Type':'application/json','X-Live-Board':'1'}, body: JSON.stringify({slots: s, reason: 'manual'})}).then(r => r.status)", new)
        await pg.wait_for_function("labs => { const a = [...document.querySelectorAll('.labels .lab:not([hidden])')].map(e => e.dataset.bot); return labs.every(n => a.includes(n)); }", arg=new, timeout=30000)
        sf = await wait_until(lambda: (slots_file() or {}).get("slots") == new and slots_file(), 30)
        rec("D6 换人：写入端处理后，看板和 slots.json 都换好", code == 200 and bool(sf), f"{time.time()-t2:.1f} 秒；{'、'.join(new)}")
        texts["board"] = await pg.inner_text("body")
        # 写入端没在跑时换人：不假装换好，顶上明说
        stop(sync)
        back = labs[:6]
        await pg.evaluate("s => fetch('/__board/slots', {method:'PUT', headers:{'Content-Type':'application/json','X-Live-Board':'1'}, body: JSON.stringify({slots: s, reason: 'manual'})})", back)
        await pg.wait_for_function("document.querySelector('#relay-notice') && !document.querySelector('#relay-notice').hidden && document.querySelector('#relay-notice').textContent.includes('换人还没生效')", timeout=40000)
        labs2 = await pg.evaluate(LABELS)
        rec("D7 写入端没运行：换人超时后明说，并退回写入端记录的工位", sorted(labs2) == sorted(new), (await pg.inner_text("#relay-notice")))
        await pg.screenshot(path=f"{OUT}/D7-换人没生效.png")
        rctx, rm = await newpage(); await rm.emulate_media(reduced_motion="reduce"); await rm.goto(BASE + "/index.html")
        await rm.wait_for_selector(".rays", state="attached", timeout=30000)
        q = await rm.evaluate("(() => { const e = document.querySelector('.rays'); return [getComputedStyle(e).animationName, getComputedStyle(e, '::after').animationName]; })()")
        rec("D10 打开「减少动态效果」时背景不动", q == ["none", "none"], str(q)); await rctx.close()
        await ctx.close()
        sync = start([sys.executable, CLI, "sync"], WENV, f"{TMP}/sync.log")

        # ---------- E. 重新设置：沿用密钥 + 已有表 ----------
        ctx, pg = await newpage(680, 620)
        await pg.goto(BASE + "/setup.html")
        await pg.wait_for_selector("#use-saved", state="visible")
        await pg.click("#use-saved"); await pg.wait_for_selector("section[data-step='2']:not([hidden])")
        await pg.click("#existing")
        await pg.fill("#dbid", f"https://www.notion.so/example/{db}?v=0123456789abcdef0123456789abcdef")
        await pg.click("#use-db"); await pg.wait_for_selector("section[data-step='3']:not([hidden])")
        got = (await pg.inner_text("#db-out")).strip()
        rec("E1 沿用已保存的密钥 + 粘贴已有表的链接（带视图参数）", got == db, await pg.inner_text("#done-what"))
        bad = await pg.evaluate("""async (id) => (await (await fetch('/__setup', {method: 'POST', headers: {'Content-Type': 'application/json'},
                   body: JSON.stringify({op: 'finish', database_id: id})})).json())""", "e" * 32)
        with open(os.path.join(APP_HOME, "config.json")) as f: kept = json.load(f).get("database_id")
        st403 = (await (await ctx.request.post(BASE + "/__setup", data=json.dumps({"op": "notion", "method": "GET", "path": "/v1/databases/" + "e" * 32, "body": ""}))).json())["status"]
        rec("E3 粘贴了已有表：只许读、只许保存这一张，别的表读不了也存不进去", bad.get("ok") is False and kept == db and st403 == 403, f"{bad} / 读别的表 → {st403}")
        await pg.click("#finish"); await pg.wait_for_function("document.querySelector('#msg3').textContent === '已保存'")
        rec("E2 只核对现有表，没有再建新表", jget(API + "/__stats")["dbs"] == 1)
        await ctx.close()

        # ---------- F. 密钥没了 ----------
        os.remove(os.path.join(APP_HOME, "notion_token"))
        ctx, pg = await newpage()
        await pg.goto(BASE + "/index.html")
        await pg.wait_for_function("document.querySelector('#relay-notice')?.textContent.includes('还没填连接密钥')", timeout=30000)
        rec("F1 密钥没了：看板明说", True, await pg.inner_text("#relay-notice"))
        await ctx.close()

        # ---------- G. 白名单 ----------
        def post(path, obj):
            req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(), method="POST", headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as r: return r.status
            except urllib.error.HTTPError as e: return e.code
        g = [post("/__notion/v1/search", {}), post(f"/__notion/v1/databases/{'f'*32}/query", {}),
             post("/__notion/v1/pages", {"parent": {"database_id": db}, "properties": {"类型": {"select": {"name": "事件"}}}})]
        rec("G1 看板通道只放行「查这张表」「加换人行」", g == [403, 403, 403], str(g))


        # ---------- I. 界面语言：跟随系统 / 简体中文 / English ----------
        with open(os.path.join(APP_HOME, "notion_token"), "w") as f: f.write(TOKEN + "\n")   # F 删掉了密钥，放回去
        os.chmod(os.path.join(APP_HOME, "notion_token"), 0o600)
        CJK = re.compile(r"[\u4e00-\u9fff]")
        ctx, pg = await newpage(680, 620, locale="en-US")
        await pg.goto(BASE + "/setup.html")
        await pg.wait_for_selector("section[data-step='1']:not([hidden])")
        body = await pg.inner_text("body"); texts["setup-en"] = body
        rec("I1 英文系统、语言跟随系统：设置向导是英文", "Set up Live Board" in body and "Connect" in body and not CJK.search(body.replace("简体中文", "")), body[:120].replace("\n", " / "))
        await pg.fill("#token", "abc"); await pg.click("#verify")
        t = await pg.inner_text("#msg1"); rec("I2 英文向导的提示也是英文", "doesn't look like" in t and not CJK.search(t), t)
        rec("I3 英文向导的 <html lang> 是 en", await pg.evaluate("document.documentElement.lang") == "en")
        await ctx.close()

        ctx, pg = await newpage(locale="en-US")
        await pg.goto(BASE + "/index.html")
        await pg.wait_for_function("document.querySelector('#conn span')?.textContent.startsWith('Live')", timeout=60000)
        await pg.wait_for_function("document.querySelectorAll('.labels .lab:not([hidden])').length === 6", timeout=60000)
        ui = await pg.evaluate("""() => ({online: document.querySelector('.online').innerText, conn: document.querySelector('#conn').innerText,
            bench: document.querySelector('#bench-tab span').textContent, more: document.querySelector('#more > summary').textContent,
            members: document.querySelector('#members > summary').textContent, log: document.querySelector('#logbox > summary').textContent,
            tag: getComputedStyle(document.querySelector('.flow'), '::before').content, flow: document.querySelector('#flow-now').innerText,
            modes: [...document.querySelectorAll('.modes button')].map(b => b.textContent).join('|'), lang: document.documentElement.lang,
            ty: [...document.querySelectorAll('#log .ty')].map(e => e.textContent).join('|'), em: [...document.querySelectorAll('#log em')].map(e => e.textContent).join('|')})""")
        texts["board-en"] = json.dumps(ui, ensure_ascii=False)
        chrome = " ".join(str(ui[k]) for k in ("online", "conn", "bench", "more", "members", "log", "tag", "modes", "em"))   # ty 里带成员名（数据），I5 单独查
        rec("I4 英文系统：看板界面文字是英文（成员名、任务名等数据不翻译）", "Working" in ui["online"] and "Idle" in ui["online"] and ui["bench"] == "Bench" and "More" in ui["more"] and "Live" in ui["modes"] and ui["lang"] == "en" and not CJK.search(chrome), chrome[:200])
        rec("I5 英文看板：事件类型、来源标签用英文显示", "output" in ui["ty"] and "check-in" in ui["em"], ui["ty"][:80] + " / " + ui["em"][:40])
        rec("I6 英文看板：流程「Step N of M」", bool(re.search(r"Step\s+\d+\s+of \d+", ui["flow"])), ui["flow"][:80].replace("\n", " "))
        await pg.screenshot(path=f"{OUT}/I-英文看板.png"); await ctx.close()

        # 中文系统里在向导上手动选 English：马上换成英文、记下来，看板也跟着（App 的设置优先于系统语言）
        ctx, pg = await newpage(680, 620)
        await pg.goto(BASE + "/setup.html")
        await pg.wait_for_selector("#lang")
        before = await pg.inner_text("h1")
        await pg.select_option("#lang", "en")
        await pg.wait_for_function("document.querySelector('h1').textContent.includes('Live Board')")
        after = await pg.inner_text("h1"); saved = jget(BASE + "/__calls").get("lang")
        rec("I7 中文系统里在向导选 English：当场换成英文，设置存进 App", "实时看板" in before and "Live Board" in after and saved == "en", f"{before} → {after}；存下 {saved}")
        pg2 = await ctx.new_page(); await pg2.goto(BASE + "/index.html")
        await pg2.wait_for_function("document.querySelector('#conn span')?.textContent.startsWith('Live')", timeout=60000)
        rec("I8 App 里选了 English：中文系统的看板也显示英文", await pg2.evaluate("document.documentElement.lang") == "en")
        await pg.select_option("#lang", "system")
        await pg.wait_for_function("document.querySelector('h1').textContent.includes('实时看板')")
        await pg2.reload(); await pg2.wait_for_function("document.querySelector('#conn span')?.textContent.startsWith('实况')", timeout=60000)
        rec("I9 改回「跟随系统」：中文系统又显示中文", jget(BASE + "/__calls").get("lang") == "system")
        await ctx.close()
        ctx, pg = await newpage(680, 620, locale="en-US")
        await pg.goto(BASE + "/setup.html"); await pg.wait_for_selector("#lang")
        await pg.select_option("#lang", "zh-Hans")
        await pg.wait_for_function("document.querySelector('h1').textContent.includes('实时看板')")
        rec("I10 英文系统里选简体中文：向导换成中文", jget(BASE + "/__calls").get("lang") == "zh-Hans")
        await pg.select_option("#lang", "system"); await ctx.close()

        # ---------- H. 界面字样 ----------
        hits = {k: sorted(set(m.group(0) for m in AI_WORDS.finditer(v))) for k, v in texts.items()}
        bad = {k: v for k, v in hits.items() if v}
        rec("H1 看板和向导界面里没有「AI / 智能体 / 机器人」一类标签", not bad, json.dumps(bad, ensure_ascii=False) if bad else f"检查了 {len(texts)} 个界面")
        # 浏览器把 4xx/5xx 响应都记成一条 console 错误：429（被限流后已自动重试）和 599（F1 故意删了密钥）是预期内的，单独数出来
        net = [e for e in errs if "Failed to load resource" in e]; real = [e for e in errs if e not in net]
        rec("H2 页面没有脚本报错", not real, "；".join(real[:5]) or f"另有 {len(net)} 条预期内的网络响应记录（429 自动重试 / 599 无密钥）")
        await b.close()
    stop(sync)


try:
    asyncio.run(main())
except Exception as e:
    rec("运行中断", False, f"{type(e).__name__}: {str(e)[:300]}")
finally:
    for p in procs: stop(p)
    with open(os.path.join(OUT, "记录.json"), "w") as f: json.dump(R, f, ensure_ascii=False, indent=1)
    ok = all(x["结果"] == "PASS" for x in R)
    print(f"\n共 {len(R)} 项，{sum(x['结果'] == 'PASS' for x in R)} 项通过" + ("" if ok else "，有失败项"))
    if ok: shutil.rmtree(TMP, ignore_errors=True)
    else: print("临时目录（日志）：", TMP)
    sys.exit(0 if ok else 1)
