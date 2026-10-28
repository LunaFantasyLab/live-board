// 实时看板 · 第一次打开时的设置向导（也从菜单「重新设置…」进来）。
// 所有 Notion 请求都经 App 原生层发出（window.webkit.messageHandlers.setup）：密钥交给原生层后，网页就再也读不到它。
// 原生层只放行这几种请求：验证密钥、只列页面、在列出来的页面下建中转页、在中转页下建表、读这次选定的那张表的结构。
// 没有原生层（在浏览器里自测）时，同样的请求发给本机测试服务 POST /__setup。
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const ROOT_TITLE = "实时看板中转", DB_TITLE = "看板数据";
  // 看板数据表的结构（和 writer/liveboard.py 里的 SCHEMA 一致）
  const SCHEMA = {
    "名称": { title: {} },
    "类型": { select: { options: [{ name: "事件", color: "blue" }, { name: "工位", color: "green" }, { name: "名单", color: "purple" }, { name: "换人", color: "orange" }] } },
    "序号": { number: { format: "number" } },
    "数据": { rich_text: {} },
    "状态": { select: { options: [{ name: "待处理", color: "yellow" }, { name: "已处理", color: "green" }, { name: "已拒绝", color: "red" }] } },
  };
  const NEED = { "名称": "title", "类型": "select", "序号": "number", "数据": "rich_text", "状态": "select" };

  async function call(op, args = {}) {
    const h = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.setup;
    if (h) return await h.postMessage({ op, ...args });
    const r = await fetch("/__setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op, ...args }), cache: "no-store" });
    return await r.json();
  }
  // 自己控速：两次请求至少隔 350 毫秒；Notion 说太快（429）或临时出错（5xx）就等一会儿再试，最多 3 次
  let lastReq = 0;
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  async function notion(method, path, body) {
    for (let i = 0; ; i++) {
      const gap = lastReq + 350 - Date.now(); if (gap > 0) await sleep(gap);
      lastReq = Date.now();
      const r = await call("notion", { method, path, body: body ? JSON.stringify(body) : "" });
      let json = {}; try { json = r && r.body ? JSON.parse(r.body) : {}; } catch { /* 非 JSON */ }
      const status = (r && r.status) || 0;
      if ((status === 429 || status >= 500) && i < 3) { await sleep(1000 * (i + 1)); continue; }
      return { status, json };
    }
  }
  function why(r) {
    if (r.status === 401) return "密钥不对：请确认复制的是完整的连接密钥";
    if (r.status === 403) return "这个连接没有权限做这件事（检查连接的权限设置是否允许读取、插入、更新内容）";
    if (r.status === 404) return "找不到：这个页面或表还没加上你的连接";
    if (r.status === 429) return "Notion 说请求太快了，请稍等几秒再试";
    if (r.status === 0) return "连不上 Notion，请检查网络";
    return `Notion 出错了（${r.status}）${r.json && r.json.message ? "：" + r.json.message : ""}`;
  }
  const msg = (id, text, kind = "") => { const m = $(id); m.textContent = text; m.className = "msg" + (kind ? " " + kind : ""); };
  const plain = (arr) => (arr || []).map((x) => x.plain_text ?? (x.text && x.text.content) ?? "").join("");
  const titleOf = (p) => { for (const v of Object.values(p.properties || {})) if (v && v.type === "title") return plain(v.title); return ""; };
  const hex = (s) => String(s || "").replace(/-/g, "").toLowerCase();
  // 从链接或 ID 里取 32 位 ID（Notion 链接末尾那串，可能带 ?v= 视图参数）
  function parseId(s) {
    s = String(s || "").trim();
    const path = s.split("?")[0].split("#")[0];
    const m = path.replace(/-/g, "").match(/[0-9a-f]{32}(?!.*[0-9a-f]{32})/i);
    return m ? m[0].toLowerCase() : "";
  }

  // ---------- 步骤切换 ----------
  let step = 1;
  function go(n) {
    step = n;
    document.querySelectorAll("section[data-step]").forEach((s) => (s.hidden = Number(s.dataset.step) !== n));
    document.querySelectorAll(".dots li").forEach((li) => {
      const s = Number(li.dataset.s);
      li.classList.toggle("done", s < n);
      if (s === n) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    const f = document.querySelector(`section[data-step="${n}"] input, section[data-step="${n}"] button:not(.ghost)`);
    if (f && n !== 3) f.focus();
  }

  // ---------- 第 1 步 ----------
  const TOKEN_RE = /^(ntn_|secret_)[A-Za-z0-9_-]{20,}$/;
  async function verify(useSaved) {
    const btn = $("#verify"); btn.disabled = true;
    try {
      if (!useSaved) {
        const t = $("#token").value.trim();
        if (!t) return msg("#msg1", "请先粘贴连接密钥", "err");
        if (!TOKEN_RE.test(t)) return msg("#msg1", "看起来不像 Notion 连接密钥：应该以 ntn_ 或 secret_ 开头，中间没有空格", "err");
        const r = await call("token", { token: t });
        if (!r || !r.ok) return msg("#msg1", "没存进去，请再试一次", "err");
      } else {
        const r = await call("token", { useSaved: true });
        if (!r || !r.ok) return msg("#msg1", "这台 Mac 上没有已保存的密钥，请粘贴", "err");
      }
      $("#token").value = "";   // 网页里不留密钥
      msg("#msg1", "正在验证…", "busy");
      const r = await notion("GET", "/v1/users/me");
      if (r.status !== 200) return msg("#msg1", why(r), "err");
      const ws = (r.json.bot && r.json.bot.workspace_name) || "";
      msg("#msg1", "");
      $("#who").textContent = `密钥有效${r.json.name ? `：连接「${r.json.name}」` : ""}${ws ? `，工作区「${ws}」` : ""}`;
      go(2); loadPages();
    } finally { btn.disabled = false; }
  }
  $("#verify").onclick = () => verify(false);
  $("#token").addEventListener("keydown", (e) => { if (e.key === "Enter") verify(false); });
  $("#use-saved").onclick = () => verify(true);
  $("#open-integrations").onclick = () => call("open", { url: "https://www.notion.so/profile/integrations" });

  // ---------- 第 2 步 ----------
  let picked = null;
  async function loadPages() {
    msg("#msg2", "正在读取这个连接能看到的页面…", "busy"); $("#pages").innerHTML = ""; picked = null; $("#create").disabled = true;
    const list = [];
    let cursor;
    for (let i = 0; i < 5; i++) {
      const body = { filter: { property: "object", value: "page" }, page_size: 100 };
      if (cursor) body.start_cursor = cursor;
      const r = await notion("POST", "/v1/search", body);
      if (r.status !== 200) return msg("#msg2", why(r), "err");
      list.push(...(r.json.results || []));
      if (!r.json.has_more) break; cursor = r.json.next_cursor;
    }
    // 只列「普通页面」：表里的行（parent 是 database）不适合放中转表
    const pages = list.filter((p) => p.object === "page" && p.parent && p.parent.type !== "database_id" && !p.archived && !p.in_trash);
    if (!pages.length) return msg("#msg2", "还没有页面加上这个连接。按上面 1–3 做完再点「刷新列表」。", "err");
    msg("#msg2", `找到 ${pages.length} 个页面，选一个：`);
    for (const p of pages) {
      const li = document.createElement("li");
      li.setAttribute("role", "radio"); li.setAttribute("aria-checked", "false"); li.tabIndex = 0;
      li.dataset.id = hex(p.id); li.textContent = titleOf(p) || "（无标题页面）";
      li.onclick = li.onkeydown = (e) => {
        if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault?.();
        document.querySelectorAll("#pages li").forEach((x) => x.setAttribute("aria-checked", String(x === li)));
        picked = { id: li.dataset.id, title: li.textContent }; $("#create").disabled = false;
      };
      $("#pages").appendChild(li);
    }
  }
  $("#reload-pages").onclick = loadPages;
  $("#back1").onclick = () => go(1);

  let result = null;
  $("#create").onclick = async () => {
    if (!picked) return;
    const btn = $("#create"); btn.disabled = true;
    try {
      msg("#msg2", `正在「${picked.title}」里新建「${ROOT_TITLE}」页面…`, "busy");
      const p = await notion("POST", "/v1/pages", { parent: { type: "page_id", page_id: picked.id }, properties: { title: { title: [{ type: "text", text: { content: ROOT_TITLE } }] } } });
      if (p.status !== 200) return msg("#msg2", why(p), "err");
      msg("#msg2", `正在新建「${DB_TITLE}」表…`, "busy");
      const d = await notion("POST", "/v1/databases", { parent: { type: "page_id", page_id: hex(p.json.id) }, title: [{ type: "text", text: { content: DB_TITLE } }], is_inline: true, properties: SCHEMA });
      if (d.status !== 200) return msg("#msg2", why(d), "err");
      msg("#msg2", "");
      done(hex(d.json.id), `已在「${picked.title}」里新建「${ROOT_TITLE}」页面和「${DB_TITLE}」表`);
    } finally { btn.disabled = !picked; }
  };

  $("#use-db").onclick = async () => {
    const id = parseId($("#dbid").value);
    if (!id) return msg("#msg2b", "没认出表的 ID：请粘贴表的链接，或 32 位 ID", "err");
    msg("#msg2b", "正在检查这张表…", "busy");
    const c = await call("choose", { database_id: id });   // 告诉原生层：这次只用这一张表
    if (!c || !c.ok) return msg("#msg2b", "没认出表的 ID：请粘贴表的链接，或 32 位 ID", "err");
    const r = await notion("GET", `/v1/databases/${id}`);
    if (r.status !== 200) return msg("#msg2b", why(r), "err");
    const props = r.json.properties || {};
    const bad = Object.entries(NEED).filter(([k, t]) => !props[k] || props[k].type !== t).map(([k, t]) => `${k}（${t}）`);
    if (bad.length) return msg("#msg2b", "这张表缺少或类型不对的列：" + bad.join("、"), "err");
    msg("#msg2b", "");
    done(id, `用已有的表「${plain(r.json.title) || DB_TITLE}」`);
  };

  // ---------- 第 3 步 ----------
  function done(id, what) {
    result = id;
    $("#done-what").textContent = what;
    $("#db-out").textContent = id;
    $("#cmd-out").textContent = `python3 liveboard.py init --database ${id}`;
    go(3);
  }
  $("#copy-cmd").onclick = async () => { await call("copy", { text: $("#cmd-out").textContent }); msg("#msg3", "已复制"); };
  $("#finish").onclick = async () => {
    const r = await call("finish", { database_id: result });
    if (!r || !r.ok) return msg("#msg3", (r && r.error) || "没保存成功，请再试一次", "err");
    msg("#msg3", "已保存");
  };

  // ---------- 开始 ----------
  (async () => {
    try { const s = await call("state"); if (s && s.hasToken) $("#keep").hidden = false; } catch { /* 没有原生层也没有测试服务 */ }
    go(1);
  })();
  window.__setup = { parseId, SCHEMA };
})();
