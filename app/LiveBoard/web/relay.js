// 实时看板 · Notion 中转数据层（只在 Mac 菜单栏 App 里加载）
// 看板网页要四个接口：GET /api/roster、GET /api/events、EventSource /api/stream、GET/PUT /__board/slots。
// 这里把它们接到 Notion 上：
// 读：每隔几秒问 Notion「看板数据」表里序号比手上大的行（小窗开着 3 秒一次，收起 30 秒一次，弹出时马上一次）。
// 写：换人只写一行「换人 / 待处理」，写入端（writer/liveboard.py sync）读到后改 state/slots.json，再把新工位行写回来。
// Notion 请求经 App 原生层发出（window.webkit.messageHandlers.notion），密钥只在原生层，网页拿不到。
// 设置（表 ID 等）由原生层在页面加载前注入到 window.__LIVEBOARD_CFG。
// 提示文字在 i18n.js（简体中文 / English，跟着 window.__LIVEBOARD_LANG 或系统语言）。
(() => {
  "use strict";
  const CFG = window.__LIVEBOARD_CFG || {};
  const DB = String(CFG.database_id || "").replace(/-/g, "");
  const ACTIVE_MS = CFG.active_ms || 3000, IDLE_MS = CFG.idle_ms || 30000, PENDING_MS = 1500;
  const LOOKBACK = 50, CHECK_EVERY = 15 * 60e3, PENDING_TTL = CFG.pending_ttl_ms || 60e3, SLOT_N = 6, KEEP_EVENTS = 5000;
  const CACHE = "liveboard.relay.v1." + DB;
  const st = { events: new Map(), roster: null, slots: null, seq: { roster: 0, slots: 0 }, lastSeq: 0, ready: false, broken: false, pending: null, lastFull: 0 };
  const stats = { polls: 0, requests: 0, lastOk: 0, lastError: "", newEvents: 0 };
  const origFetch = window.fetch.bind(window);
  const RealES = window.EventSource;

  // ---------- 本机缓存（只是加快启动；第一次问到 Notion 之前不显示）----------
  try {
    const c = JSON.parse(localStorage.getItem(CACHE) || "null");
    if (c && c.v === 1) {
      for (const e of c.events || []) st.events.set(e.id, e);
      st.roster = c.roster || null; st.slots = c.slots || null; st.seq = c.seqs || st.seq; st.lastSeq = c.lastSeq || 0; st.lastFull = c.lastFull || 0;
    }
  } catch { /* 坏缓存当没有 */ }
  let saveT = 0;
  function saveCache() {
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      // 只缓存最近 KEEP_EVENTS 条，表再大本机缓存也不会无限变大
      const evs = [...st.events.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts)).slice(-KEEP_EVENTS);
      try { localStorage.setItem(CACHE, JSON.stringify({ v: 1, events: evs, roster: st.roster, slots: st.slots, seqs: st.seq, lastSeq: st.lastSeq, lastFull: st.lastFull })); } catch { /* 满了就不缓存 */ }
    }, 500);
  }

  // ---------- 一行提示（没连上时才出现）----------
  let bar = null;
  function notice(text) {
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "relay-notice";
      bar.setAttribute("role", "status");
      bar.style.cssText = "position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:9999;background:#111;color:#f2ecde;font:600 13px/1.4 -apple-system,'PingFang SC',sans-serif;padding:6px 14px;border:2px solid #D14A2E;white-space:nowrap;pointer-events:none";
      (document.body || document.documentElement).appendChild(bar);
    }
    // 还没从 Notion 拿到过数据：整屏只有这一行（不让底下的空工位、默认名单露出来）；已经有数据：顶上一行
    bar.style.cssText = st.ready
      ? "position:fixed;left:50%;top:10px;transform:translateX(-50%);z-index:9999;background:#111;color:#f2ecde;font:600 13px/1.4 -apple-system,'PingFang SC',sans-serif;padding:6px 14px;border:2px solid #D14A2E;white-space:nowrap;pointer-events:none"
      : "position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:#111;color:#f2ecde;font:600 15px/1.5 -apple-system,'PingFang SC',sans-serif;padding:24px;text-align:center";
    bar.textContent = text; bar.hidden = !text; if (!text) bar.style.display = "none";
  }

  // ---------- Notion 请求 ----------
  // 自己控速：两次请求至少隔 350 毫秒；Notion 说太快（429）或临时出错（5xx）就等一会儿再试，最多 3 次
  let lastReq = 0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function notion(method, path, body) {
    for (let i = 0; ; i++) {
      const gap = lastReq + 350 - Date.now(); if (gap > 0) await sleep(gap);
      lastReq = Date.now();
      const r = await notionOnce(method, path, body);
      if ((r.status === 429 || r.status >= 500) && i < 3) { stats.retries = (stats.retries || 0) + 1; await sleep(1000 * (i + 1)); continue; }
      return r;
    }
  }
  async function notionOnce(method, path, body) {
    stats.requests++;
    const h = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.notion;
    if (h) {
      const r = await h.postMessage({ method, path, body: body ? JSON.stringify(body) : "" });
      let j = {}; try { j = r && r.body ? JSON.parse(r.body) : {}; } catch { /* 非 JSON */ }
      return { status: (r && r.status) || 0, json: j };
    }
    // 没有原生层（浏览器里自测）：同样的请求发给本机测试服务 /__notion（它照 App 原生层的规则转给 Notion）
    const r = await origFetch("/__notion" + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
    let j = {}; try { j = await r.json(); } catch { /* 非 JSON */ }
    return { status: r.status, json: j };
  }
  const I = window.__LB_I18N, T = (k, v) => (I ? I.t(k, v) : k);
  const WHY = { 401: () => T("r.401"), 403: () => T("r.403"), 404: () => T("r.404") };
  function whyOf(r) {
    if (r.json && r.json.code === "no_token") return T("r.noToken");
    return WHY[r.status] ? WHY[r.status]() : (r.status === 0 ? T("r.offline") : T("r.error", { status: r.status }));
  }
  const text = (p) => ((p && (p.rich_text || p.title)) || []).map((x) => x.plain_text ?? (x.text && x.text.content) ?? "").join("");

  // ---------- 读 ----------
  let inflight = null, timer = 0, active = !document.hidden, fails = 0;
  const waiters = [];
  function markReady() { if (st.ready) return; st.ready = true; while (waiters.length) waiters.shift()(); }
  function whenReady(ms = 20000) {
    if (st.ready) return Promise.resolve(true);
    return new Promise((res) => { const t = setTimeout(() => res(false), ms); waiters.push(() => { clearTimeout(t); res(true); }); });
  }
  async function queryAll(filter) {
    const rows = []; let cursor;
    for (;;) {
      const body = { filter, sorts: [{ property: "序号", direction: "ascending" }], page_size: 100 };
      if (cursor) body.start_cursor = cursor;
      const r = await notion("POST", `/v1/databases/${DB}/query`, body);
      if (r.status !== 200) throw r;
      rows.push(...(r.json.results || []));
      if (!r.json.has_more) return rows;
      cursor = r.json.next_cursor;
    }
  }
  // 某一类最新的一行（序号最大）
  async function latestOf(kind) {
    const r = await notion("POST", `/v1/databases/${DB}/query`, { filter: { property: "类型", select: { equals: kind } }, sorts: [{ property: "序号", direction: "descending" }], page_size: 1 });
    if (r.status !== 200) throw r;
    return r.json.results || [];
  }
  function poll() {
    if (inflight) return inflight;
    inflight = (async () => {
      stats.polls++;
      // 第一次（没有缓存）：整张表读一遍。之后只读序号更大的行；每 15 分钟再单独核对一次最新的名单行和工位行
      // （事件行写进去就不会再改，所以不用定期重读整张表，表变大了也不会越来越慢）。
      const first = !st.lastSeq, check = !first && Date.now() - st.lastFull > CHECK_EVERY;
      const notSwap = { property: "类型", select: { does_not_equal: "换人" } };
      const filter = first ? notSwap : { and: [notSwap, { property: "序号", number: { greater_than: Math.max(0, st.lastSeq - LOOKBACK) } }] };
      let rows;
      try {
        rows = await queryAll(filter);
        if (check) { rows = rows.concat(await latestOf("名单"), await latestOf("工位")); st.seq.roster = Math.min(st.seq.roster, 0); st.seq.slots = Math.min(st.seq.slots, 0); }
      }
      catch (r) { fails++; stats.lastError = whyOf(r || {}); notice(stats.lastError); broken(); return false; }
      fails = 0; stats.lastOk = Date.now(); curSlots(); notice(pendingNote());
      if (first || check) st.lastFull = Date.now();
      const fresh = []; let rosterCh = false, slotsCh = false;
      for (const row of rows) {
        const p = row.properties || {}, kind = p["类型"]?.select?.name, seq = p["序号"]?.number || 0;
        let data; try { data = JSON.parse(text(p["数据"])); } catch { continue; }
        st.lastSeq = Math.max(st.lastSeq, seq);
        if (kind === "事件") {
          if (data && data.id && !data.test && !st.events.has(data.id)) { st.events.set(data.id, data); fresh.push(data); }
        } else if (kind === "名单" && seq > st.seq.roster) {
          st.seq.roster = seq; if (JSON.stringify(st.roster) !== JSON.stringify(data)) { st.roster = data; rosterCh = true; }
        } else if (kind === "工位" && seq > st.seq.slots) {
          st.seq.slots = seq; const ch = JSON.stringify(st.slots) !== JSON.stringify(data); st.slots = data; if (st.pending || ch) slotsCh = true; st.pending = null; st.stale = false;
        }
      }
      const firstShow = !st.ready;
      markReady();
      if (fresh.length || rosterCh || slotsCh || firstShow) saveCache();
      if (st.broken || firstShow) { st.broken = false; for (const s of streams) s._init(); }
      else for (const e of fresh.sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))) { stats.newEvents++; for (const s of streams) s._emit("ev", e); }
      if (firstShow || rosterCh) window.dispatchEvent(new Event("liveboard:roster"));
      if (firstShow || slotsCh) window.dispatchEvent(new Event("liveboard:slots"));
      return true;
    })().finally(() => { inflight = null; });
    return inflight;
  }
  function broken() { if (st.broken && st.ready) return; st.broken = true; for (const s of streams) s._error(); }
  function delay() {
    if (fails) return Math.min(30e3, 3e3 * 2 ** (fails - 1));
    if (st.pending && Date.now() - st.pending.at < 15e3) return PENDING_MS;
    return active ? ACTIVE_MS : IDLE_MS;
  }
  function loop(ms) { clearTimeout(timer); timer = setTimeout(async () => { await poll(); loop(delay()); }, ms); }
  document.addEventListener("visibilitychange", () => { setActive(!document.hidden); });
  function setActive(on) { const was = active; active = !!on; if (active && !was) refresh(); }
  function refresh() { clearTimeout(timer); return poll().then((ok) => { loop(delay()); return ok; }); }

  // ---------- 工位 ----------
  function curSlots() {
    if (st.pending && Date.now() - st.pending.at < PENDING_TTL) return st.pending.rec;
    // 写了换人行，一分钟内写入端都没回新的工位行：多半是写入端没在运行。不再假装换好了，顶上明说一句
    if (st.pending) { st.pending = null; st.stale = true; notice(pendingNote()); }
    return st.slots;
  }
  function pendingNote() { return st.stale ? T("r.pending") : ""; }
  const BY_TXT = { default: "默认（按最近动态，第一次存下后固定）", local: "沿用这台设备原来的选择", manual: "手动替换" };
  async function putSlots(o) {
    await whenReady();
    const a = o && o.slots, ok = new Set(((st.roster && st.roster.bots) || []).map((b) => b.name));
    if (!Array.isArray(a) || a.length !== SLOT_N || a.some((n) => typeof n !== "string" || !ok.has(n)) || new Set(a).size !== SLOT_N)
      return jres(400, { error: T("r.badSlots", { n: SLOT_N }) });
    const cur = curSlots();
    if (o.ifEmpty && cur) return jres(200, { ...cur, kept: true });
    const rec = { slots: a.slice(), updatedAt: new Date().toISOString(), by: BY_TXT[o.reason] || (o.ifEmpty ? BY_TXT.default : BY_TXT.manual) };
    const body = { parent: { database_id: DB }, properties: {
      "名称": { title: [{ type: "text", text: { content: "换人 " + rec.updatedAt } }] },
      "类型": { select: { name: "换人" } }, "状态": { select: { name: "待处理" } },
      "数据": { rich_text: [{ type: "text", text: { content: JSON.stringify({ slots: a, ifEmpty: !!o.ifEmpty, reason: o.reason || "manual", at: rec.updatedAt }) } }] } } };
    let r; try { r = await notion("POST", "/v1/pages", body); } catch { r = { status: 0, json: {} }; }
    if (r.status !== 200) return jres(502, { error: whyOf(r) });
    st.pending = { rec, at: Date.now() }; st.stale = false;
    loop(PENDING_MS);   // 写入端一般几秒内处理完，这段时间多问几次
    return jres(200, rec);
  }

  // ---------- 接管网页的 fetch / EventSource ----------
  function jres(code, obj) { return new Response(JSON.stringify(obj), { status: code, headers: { "Content-Type": "application/json; charset=utf-8" } }); }
  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    let path; try { path = new URL(url, location.href).pathname; } catch { path = ""; }
    const method = String(init.method || (typeof input === "object" && input.method) || "GET").toUpperCase();
    if (path === "/api/roster") return (await whenReady()) && st.roster ? jres(200, st.roster) : jres(503, { error: "not ready" });
    if (path === "/api/events") return (await whenReady()) ? jres(200, [...st.events.values()]) : jres(503, { error: "not ready" });
    if (path === "/__board/slots") {
      if (method === "PUT") { let o = null; try { o = JSON.parse(init.body); } catch { /* 下面会拒 */ } return putSlots(o); }
      if (!(await whenReady())) return jres(503, { error: "not ready" });
      const c = curSlots(); return jres(200, c ? { slots: c.slots, updatedAt: c.updatedAt, by: c.by } : { slots: null });
    }
    return origFetch(input, init);
  };
  const streams = new Set();
  class RelayStream extends EventTarget {
    constructor(url) { super(); this.url = url; this.readyState = 0; this.onerror = null; this.onmessage = null; this.onopen = null; streams.add(this); if (st.ready && !st.broken) setTimeout(() => this._init(), 0); }
    _emit(type, data) { if (this.readyState === 2) return; this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) })); }
    _init() { if (this.readyState === 2) return; this.readyState = 1; this.onopen?.(new Event("open")); this._emit("init", [...st.events.values()]); }
    _error() { if (this.readyState === 2) return; this.readyState = 0; this.onerror?.(new Event("error")); }
    close() { this.readyState = 2; streams.delete(this); }
  }
  window.EventSource = function (url, opts) { return String(url).startsWith("/api/stream") ? new RelayStream(url) : new RealES(url, opts); };

  window.__relay = { refresh, setActive, stats, state: st };
  if (!DB) { notice(T("r.noDb")); return; }
  refresh();
})();
