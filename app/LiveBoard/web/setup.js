// 实时看板 · 第一次打开时的设置向导（也从菜单「重新设置…」进来）。
// 所有 Notion 请求都经 App 原生层发出（window.webkit.messageHandlers.setup）：密钥交给原生层后，网页就再也读不到它。
// 原生层只放行这几种请求：验证密钥、只列页面、在列出来的页面下建中转页、在中转页下建表、读这次选定的那张表的结构。
// 没有原生层（在浏览器里自测）时，同样的请求发给本机测试服务 POST /__setup。
// 界面文字在 i18n.js（简体中文 / English）；右上角可以换语言，当场换文字，已填的内容不丢。
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const I = window.__LB_I18N, T = (k, v) => I.t(k, v);
  // 新建的 Notion 页面和表用当前语言起名（只是名字，改了也不影响使用）
  const rootTitle = () => T("notion.root"), dbTitle = () => T("notion.db");
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
  // 提示文字都存成「怎么生成」（函数），换语言时重新生成一遍
  const why = (r) => () => {
    if (r.status === 401) return T("why.401");
    if (r.status === 403) return T("why.403");
    if (r.status === 404) return T("why.404");
    if (r.status === 429) return T("why.429");
    if (r.status === 0) return T("why.0");
    return T("why.other", { status: r.status, detail: r.json && r.json.message ? T("why.detail", { message: r.json.message }) : "" });
  };
  const tx = (k, v) => () => T(k, v);
  const live = {};
  const put = (id, f) => { live[id] = f; $(id).textContent = typeof f === "function" ? f() : f; };
  const msg = (id, text, kind = "") => { put(id, text); $(id).className = "msg" + (kind ? " " + kind : ""); };
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
        if (!t) return msg("#msg1", tx("m.pasteFirst"), "err");
        if (!TOKEN_RE.test(t)) return msg("#msg1", tx("m.notToken"), "err");
        const r = await call("token", { token: t });
        if (!r || !r.ok) return msg("#msg1", tx("m.notSaved"), "err");
      } else {
        const r = await call("token", { useSaved: true });
        if (!r || !r.ok) return msg("#msg1", tx("m.noSaved"), "err");
      }
      $("#token").value = "";   // 网页里不留密钥
      msg("#msg1", tx("m.verifying"), "busy");
      const r = await notion("GET", "/v1/users/me");
      if (r.status !== 200) return msg("#msg1", why(r), "err");
      const ws = (r.json.bot && r.json.bot.workspace_name) || "", name = r.json.name || "";
      msg("#msg1", "");
      put("#who", () => T("m.valid") + (name ? T("m.validName", { name }) : "") + (ws ? T("m.validWs", { ws }) : ""));
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
    msg("#msg2", tx("m.loadingPages"), "busy"); $("#pages").innerHTML = ""; picked = null; $("#create").disabled = true;
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
    if (!pages.length) return msg("#msg2", tx("m.noPages"), "err");
    msg("#msg2", tx("m.foundPages", { n: pages.length }));
    for (const p of pages) {
      const li = document.createElement("li");
      li.setAttribute("role", "radio"); li.setAttribute("aria-checked", "false"); li.tabIndex = 0;
      li.dataset.id = hex(p.id); li.dataset.title = titleOf(p); li.textContent = li.dataset.title || T("m.untitled");
      li.onclick = li.onkeydown = (e) => {
        if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault?.();
        document.querySelectorAll("#pages li").forEach((x) => x.setAttribute("aria-checked", String(x === li)));
        picked = { id: li.dataset.id, li }; $("#create").disabled = false;
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
      const li = picked.li, page = () => li.dataset.title || T("m.untitled");
      const root = rootTitle(), db = dbTitle();   // 用点按钮那一刻的语言起名
      msg("#msg2", () => T("m.creatingRoot", { page: page(), root }), "busy");
      const p = await notion("POST", "/v1/pages", { parent: { type: "page_id", page_id: picked.id }, properties: { title: { title: [{ type: "text", text: { content: root } }] } } });
      if (p.status !== 200) return msg("#msg2", why(p), "err");
      msg("#msg2", tx("m.creatingDb", { db }), "busy");
      const d = await notion("POST", "/v1/databases", { parent: { type: "page_id", page_id: hex(p.json.id) }, title: [{ type: "text", text: { content: db } }], is_inline: true, properties: SCHEMA });
      if (d.status !== 200) return msg("#msg2", why(d), "err");
      msg("#msg2", "");
      done(hex(d.json.id), () => T("m.created", { page: page(), root, db }));
    } finally { btn.disabled = !picked; }
  };

  $("#use-db").onclick = async () => {
    const id = parseId($("#dbid").value);
    if (!id) return msg("#msg2b", tx("m.badId"), "err");
    msg("#msg2b", tx("m.checking"), "busy");
    const c = await call("choose", { database_id: id });   // 告诉原生层：这次只用这一张表
    if (!c || !c.ok) return msg("#msg2b", tx("m.badId"), "err");
    const r = await notion("GET", `/v1/databases/${id}`);
    if (r.status !== 200) return msg("#msg2b", why(r), "err");
    const props = r.json.properties || {};
    const bad = Object.entries(NEED).filter(([k, t]) => !props[k] || props[k].type !== t);
    if (bad.length) return msg("#msg2b", () => T("m.badCols", { cols: bad.map(([name, type]) => T("m.col", { name, type })).join(T("m.colSep")) }), "err");
    msg("#msg2b", "");
    const title = plain(r.json.title);
    done(id, () => T("m.usingDb", { title: title || dbTitle() }));
  };

  // ---------- 第 3 步 ----------
  function done(id, what) {
    result = id;
    put("#done-what", what);
    $("#db-out").textContent = id;
    $("#cmd-out").textContent = `python3 liveboard.py init --database ${id}`;
    go(3);
  }
  $("#copy-cmd").onclick = async () => { await call("copy", { text: $("#cmd-out").textContent }); msg("#msg3", tx("m.copied")); };
  $("#finish").onclick = async () => {
    const r = await call("finish", { database_id: result });
    if (!r || !r.ok) return msg("#msg3", (r && r.error) || tx("m.saveFailed"), "err");   // 原生层的错误提示已经按当前语言
    msg("#msg3", tx("m.saved"));
  };

  // ---------- 语言 ----------
  function render() {
    document.documentElement.lang = I.lang === "en" ? "en" : "zh-CN";
    document.querySelectorAll("[data-i18n]").forEach((e) => { e.textContent = T(e.dataset.i18n); });
    document.querySelectorAll("[data-i18n-html]").forEach((e) => { e.innerHTML = T(e.dataset.i18nHtml); });   // 只有词表里固定的 <b> / <code>
    document.querySelectorAll("[data-i18n-placeholder]").forEach((e) => { e.placeholder = T(e.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-label]").forEach((e) => { e.setAttribute("aria-label", T(e.dataset.i18nLabel)); });
    document.querySelectorAll("#pages li").forEach((li) => { li.textContent = li.dataset.title || T("m.untitled"); });
    for (const [id, f] of Object.entries(live)) $(id).textContent = typeof f === "function" ? f() : f;
  }
  function setLang(lang) { I.lang = lang === "en" || lang === "zh" ? lang : I.detect(); render(); }
  window.__lbSetLang = setLang;   // App 菜单里换语言时原生层调用
  $("#lang").onchange = async () => {
    const value = $("#lang").value;
    let r = null;
    try { r = await call("lang", { value }); } catch { /* 没有原生层 */ }
    window.__LIVEBOARD_LANG = (r && r.lang) || undefined;
    setLang(window.__LIVEBOARD_LANG || (value === "en" ? "en" : value === "zh-Hans" ? "zh" : ""));
  };

  // ---------- 开始 ----------
  render();
  (async () => {
    try {
      const s = await call("state");
      if (s && s.hasToken) $("#keep").hidden = false;
      if (s && s.language) $("#lang").value = s.language;
    } catch { /* 没有原生层也没有测试服务 */ }
    go(1);
  })();
  window.__setup = { parseId, SCHEMA };
})();
