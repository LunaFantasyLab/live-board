import "@fontsource/anton/latin-400.css";
import "./style.css";
import { DEFAULT_TITLE, SLOT_N } from "./data.js";
import { createScene, LAMP } from "./scene.js";
import { LANG, t, tyOf } from "./i18n.js";

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TZ = window.__LIVEBOARD_TZ || undefined;   // 不设就用本机时区
const fmtHM = new Intl.DateTimeFormat(LANG === "en" ? "en-GB" : "zh-CN", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDate = new Intl.DateTimeFormat(LANG === "en" ? "en-US" : "zh-CN", { timeZone: "UTC", month: LANG === "en" ? "short" : "numeric", day: "numeric" });
document.documentElement.lang = LANG === "en" ? "en" : "zh-CN";
const fmtDay = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const dayOf = (ms) => fmtDay.format(ms);
const H = 3600e3;
const params = new URLSearchParams(location.search);
let mode = params.get("mode") === "replay" ? "replay" : "live";   // 打开就是实况；回放从「更多」进
// 名单、标题、流程步骤都来自 /api/roster（写入端 roster.json 的原样内容）
// 名单没写标题时用界面语言的默认标题；写了就原样显示（用户自己的数据，不翻译）
const BASE_TITLE = LANG === "en" ? t("title") : DEFAULT_TITLE;
let ROSTER = [], BY = {}, STAGES = [], STAGE_OF = {}, TITLE = BASE_TITLE;
const shortOf = (b) => b.short || b.name;
const short = (n) => (BY[n] ? shortOf(BY[n]) : n || t("unsigned"));
function useRoster(r) {
  ROSTER = r.bots.filter((b) => b && typeof b.name === "string" && b.name).map((b) => ({ ...b, short: shortOf(b) }));
  BY = Object.fromEntries(ROSTER.map((b) => [b.name, b]));
  STAGES = Array.isArray(r.stages) ? r.stages.map(String) : [];
  STAGE_OF = Object.fromEntries(ROSTER.filter((b) => Number.isInteger(b.stage) && b.stage >= 0 && b.stage < STAGES.length).map((b) => [b.name, b.stage]));
  setTitle(typeof r.title === "string" && r.title.trim() ? r.title.trim() : BASE_TITLE);
  const nb = $("#banner"); if (nb) { nb.hidden = !r.notice; nb.textContent = r.notice || ""; }
}
async function loadRoster() {
  try { const r = await (await fetch("/api/roster", { cache: "no-store" })).json(); if (Array.isArray(r?.bots) && r.bots.length) useRoster(r); } catch { /* 还没拿到名单：沿用上一次 */ }
  const n = $("#members .cnt"); if (n) n.textContent = ROSTER.length;
  if (!ROSTER.length) return;
  // 名单到了：按本机记住的那份（没有就按当前的）重新排一次，名牌文字也跟着名单更新
  slots = fixSlots(savedSlots || slots, all); scene?.assign(slots);
}
function setTitle(title) {
  const t = title;
  TITLE = t; document.title = t;
  const h = $(".top h1"); if (!h) return;
  h.setAttribute("aria-label", t);
  // 一个字一块拼贴字；空格留一道空隙（英文标题「Live Board」要看得出是两个词）
  h.innerHTML = [...t].slice(0, 16).map((c) => (/\s/.test(c) ? '<span class="sp" aria-hidden="true"></span>' : `<span${/[\x21-\x7e]/.test(c) ? ' class="l"' : ""} aria-hidden="true">${esc(c)}</span>`)).join("");
}

// ---------- 状态 ----------
// st：work 进行中 / wait 待接手 / back 被退回 / confirm 待你确认 / error 报错 / done 刚交完 / idle 空闲 / none 未激活
// group：on 工作中 / idle 空闲 / off 未激活
const WORD = Object.fromEntries(["work", "wait", "back", "confirm", "error", "done", "idle", "none"].map((k) => [k, t("st." + k)]));
function deriveStates(evs, now) {
  const last = {}, lastIn = {}, seen = new Set();
  for (const e of evs) {
    last[e.bot] = e; seen.add(e.bot);
    if (e.to) { seen.add(e.to); if (e.type === "交接" || e.type === "退回") lastIn[e.to] = e; }
  }
  const out = {};
  for (const b of ROSTER) {
    const l = last[b.name], i = lastIn[b.name];
    let st = seen.has(b.name) ? "idle" : "none", ref = l, incoming = false;
    if (i && (!l || i._t >= l._t) && now - i._t < 24 * H) { st = i.type === "退回" ? "back" : "wait"; ref = i; incoming = true; }
    else if (l) {
      const age = now - l._t;
      if (l.type === "报错") st = "error";
      else if (l.type === "待确认") st = "confirm";
      else if (["交接", "完成", "退回"].includes(l.type)) st = age < 8 * H ? "done" : "idle";
      else st = age < 2 * H ? "work" : "idle";
    }
    const group = st === "none" ? "off" : ["work", "wait", "back", "confirm", "error"].includes(st) ? "on" : "idle";
    out[b.name] = { st, group, ref, incoming };
  }
  return out;
}

// ---------- 流程 ----------
// 名单里给成员写了 stage（stages 的下标）才有步骤条；被退回时算回到接收方那一步
function stageOf(e) {
  if (e.type === "退回" && e.to && STAGE_OF[e.to] !== undefined) return STAGE_OF[e.to];
  return STAGE_OF[e.bot] ?? -1;
}
function pipeline(evs) {
  const per = STAGES.map(() => null); let maxS = -1, latest = null;
  for (const e of evs) { const s = stageOf(e); if (s < 0) continue; per[s] = e; if (s > maxS) maxS = s; if (!latest || e._t >= latest.e._t) latest = { s, e }; }
  const steps = STAGES.map((name, s) => {
    let st = "todo";
    if (latest && s === latest.s) st = (latest.e.type === "完成" || latest.e.type === "交接") && s !== maxS ? "done" : "active";
    else if (per[s]) st = "done"; else if (s < maxS) st = "skip";
    return { name, st, e: per[s] };
  });
  return { steps, cur: latest ? latest.s : -1, latest: latest?.e };
}

// ---------- 骨架 ----------
// 替补席大标题：一个字（英文一个字母）一块拼贴字
const benchLetters = () => [...t("bench")].map((c) => `<span${/[\x21-\x7e]/.test(c) ? ' class="l"' : ""}>${esc(c)}</span>`).join("");
document.body.dataset.mode = mode;
document.body.classList.add("fx");   // 常驻待机动画（纯装饰，不代表任何工作状态）
$("#app").innerHTML = `
<div class="shell"><div class="rays" aria-hidden="true"></div>
  <header class="top">
    <h1></h1>
    <p id="conn" class="conn" role="status"><i></i><span>${t("conn.wait")}</span></p>
  </header>
  <p id="banner" class="banner" hidden></p>
  <main class="stage" id="stage" aria-label="${t("stage.label", { n: SLOT_N })}">
    <p class="loading" id="loading">${t("loading")}</p>
    
    <button class="bench-tab" id="bench-tab" aria-haspopup="dialog"><span>${t("bench")}</span><b id="bench-n">0</b><i id="bench-new" hidden></i></button>
    <div class="pop" id="pop" hidden role="dialog" aria-label="${t("pop.label")}"></div>
    <p class="swap-toast" id="swap-toast" role="status" hidden></p>
    <section class="bench" id="bench" hidden role="dialog" aria-label="${t("bench")}">
      <header class="bench-h">
        <h2 aria-label="${t("bench")}">${benchLetters()}<b id="bench-n2">0</b></h2>
        <p id="bench-hint"></p>
        <button class="bench-x" id="bench-x" aria-label="${t("bench.closeLabel")}">${t("bench.close")}</button>
      </header>
      <div class="bench-slots" id="bench-slots" hidden></div>
      <ul class="bench-grid" id="bench-grid"></ul>
    </section>
  </main>
  <aside class="side">
    <section class="online" aria-label="${t("online.label")}">
      <div class="big"><b id="n-on">0</b><span>${t("on")}</span></div>
      <div class="big"><b id="n-idle">0</b><span>${t("idle")}</span></div>
      <div class="big conf" id="conf-cell" hidden><b id="d-conf">0</b><span>${t("confirm")}</span></div>
    </section>
    <section class="flow" aria-label="${t("flow.label")}" data-tag="${t("flow.tag")}">
      <div class="flow-h">
        <label class="sr" for="proj">${t("task")}</label>
        <select id="proj"></select>
      </div>
      <p class="flow-now" id="flow-now">${t("noTask")}</p>
      <ol class="steps" id="steps"></ol>
    </section>
    <details id="more"><summary>${t("more")}</summary>
      <details id="members"><summary>${t("members")}<span class="cnt">0</span></summary><ul id="mlist" class="mlist"></ul></details>
      <details id="logbox"><summary>${t("log")}<span class="cnt" id="logn">0</span></summary><ol id="log" class="log"></ol></details>
      <footer class="foot">
        <nav class="modes" aria-label="${t("views")}">
          <button data-m="live">${t("live")}</button><button data-m="replay">${t("replay")}</button>
        </nav>
        <div class="rp" id="rp">
          <select id="day" aria-label="${t("day")}"></select>
          <button id="play" class="play" aria-label="${t("pause")}">${t("pause")}</button>
          <input id="scrub" type="range" min="0" max="1000" value="0" aria-label="${t("scrub")}">
        </div>
      </footer>
    </details>
  </aside>
  <div class="wipe" aria-hidden="true"></div>
</div>`;

// ---------- 数据 ----------
let all = [], shown = [], vnow = Date.now(), project = null, pinned = false, focus = null;
const prep = (e) => ({ ...e, _t: Date.parse(e.ts) });
const sortT = (a, b) => a._t - b._t;
const tagOf = (e) => t(e.test ? "tag.test" : e.source === "watcher" ? "tag.watcher" : e.source === "backfill" ? "tag.backfill" : "tag.checkin");
setTitle(BASE_TITLE);

// ---------- 6 个工位 ----------
// 工位上坐谁以写入端的 state/slots.json 为准（经 /__board/slots 读写；App 里由 relay.js 经 Notion 转过去），
// 所有设备共用同一份；localStorage 只当缓存。
const SLOT_KEY = "liveboard.slots.v1", SEEN_KEY = "liveboard.benchSeen.v1";
const USE_SLOTS = true;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* 无痕模式等 */ } } };
let savedSlots = null;
try { const a = JSON.parse(store.get(SLOT_KEY) || "null"); if (Array.isArray(a) && a.length === SLOT_N) savedSlots = a; } catch { /* 坏数据当没存 */ }
let benchSeen = Number(store.get(SEEN_KEY)) || 0;
if (USE_SLOTS && !benchSeen) { benchSeen = Date.now(); store.set(SEEN_KEY, String(benchSeen)); }   // 第一次打开：以前的动态不算「新」
// 默认 6 位：最近有动态的优先，再按名单顺序补齐
function lastActOf(evs) { const m = {}; for (const e of evs) { if (e.test) continue; m[e.bot] = Math.max(m[e.bot] || 0, e._t); if (e.to) m[e.to] = Math.max(m[e.to] || 0, e._t); } return m; }
function defaultOrder(evs) {
  const ok = new Set(ROSTER.map((b) => b.name)), la = lastActOf(evs);
  const act = Object.keys(la).filter((n) => ok.has(n)).sort((a, b) => la[b] - la[a]);
  return [...new Set([...act, ...ROSTER.map((b) => b.name)])].filter((n) => ok.has(n));
}
function fixSlots(a, evs = []) {   // 去掉名单外 / 重复的名字，空位按默认顺序补上；保持各工位原来的位置
  const ok = new Set(ROSTER.map((b) => b.name)), out = [];
  for (let i = 0; i < SLOT_N; i++) { const n = a?.[i]; out.push(n && ok.has(n) && !out.includes(n) ? n : null); }
  const pool = defaultOrder(evs).filter((n) => !out.includes(n));
  return out.map((n) => n || pool.shift() || null);
}
let slots = fixSlots(savedSlots || []), defaultsDone = !!savedSlots;
const hadLocal = !!savedSlots;
// 服务器端：srv = "ok" 能用 / "off" 用不了（只用本机缓存）；serverHad = 服务器上已经存过
const SLOT_API = "/__board/slots";
let srv = "unknown", serverHad = false;
async function fetchSlots() {
  try {
    const r = await fetch(SLOT_API, { cache: "no-store", credentials: "same-origin" });
    if (!r.ok || !(r.headers.get("content-type") || "").includes("application/json")) { srv = "off"; return null; }
    const o = await r.json(); srv = "ok";
    return Array.isArray(o?.slots) && o.slots.length === SLOT_N ? o.slots : null;
  } catch { srv = "off"; return null; }
}
async function pushSlots(a, reason, ifEmpty = false) {
  if (srv !== "ok") return null;
  try {
    const r = await fetch(SLOT_API, { method: "PUT", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Live-Board": "1" }, body: JSON.stringify({ slots: a, ifEmpty, reason }) });
    if (!r.ok) return null;
    const o = await r.json(); return Array.isArray(o?.slots) && o.slots.length === SLOT_N ? o.slots : null;
  } catch { return null; }
}
function adopt(a) {   // 用服务器上的那一份；本机缓存跟着更新
  if (!ROSTER.length) return;   // 名单还没到，先不动
  const fx = fixSlots(a, all);
  savedSlots = fx.slice(); defaultsDone = true; serverHad = true; store.set(SLOT_KEY, JSON.stringify(fx));
  if (fx.join("|") === slots.join("|")) return;
  slots = fx; scene?.assign(slots);
  if (popFor && !slots.includes(popFor)) hidePop();
  if (scene) render();
}
async function syncSlots() { if (!USE_SLOTS) return; const a = await fetchSlots(); if (a) adopt(a); }
function saveSlots() {
  savedSlots = slots.slice(); defaultsDone = true; store.set(SLOT_KEY, JSON.stringify(slots));
  const mine = slots.slice();
  pushSlots(mine, "manual").then((r) => { if (r) serverHad = true; else if (srv === "ok") toast(t("toast.notSaved")); });
}
async function applyDefaults() {   // 服务器上存过就用服务器的；没存过才按最近动态排一次，然后存上去固定下来
  if (!USE_SLOTS) return;
  if (serverHad) return;
  const next = defaultsDone ? fixSlots(slots, all) : fixSlots([], all);
  defaultsDone = true;
  if (next.join("|") !== slots.join("|")) { slots = next; scene?.assign(slots); }
  if (srv === "ok") {
    const r = await pushSlots(slots.slice(), hadLocal ? "local" : "default", true);
    if (r) adopt(r);
    else if (srv === "ok" && (applyDefaults.tries = (applyDefaults.tries || 0) + 1) < 5) setTimeout(() => { syncSlots().then(applyDefaults); }, 10e3);   // 没存上（比如 Notion 一时限流）：过一会儿再试
  }
}
if (USE_SLOTS) {   // 切回来、或开着的时候每 30 秒跟服务器对一次（另一台设备换了人，这边也会跟上）
  document.addEventListener("visibilitychange", () => { if (!document.hidden) syncSlots(); });
  setInterval(() => { if (!document.hidden && srv === "ok") syncSlots(); }, 30e3);
}

// App 里的 relay.js 读到工位 / 名单变了会发这两个事件，马上跟上
window.addEventListener("liveboard:slots", () => syncSlots());
window.addEventListener("liveboard:roster", () => loadRoster().then(() => { if (scene) render(); }));

let scene = null;
createScene($("#stage"), ROSTER, { onPick: (n, o) => showPop(n, o), slots: slots.slice(), labelOf: (n) => short(n) })
  .then((s) => { scene = s; $("#loading").remove(); if (USE_SLOTS) scene.assign(slots); render(); })
  .catch((err) => { $("#loading").textContent = t("loadFail", { msg: err.message }); });

function render() {
  const states = deriveStates(shown, vnow);
  scene?.setStates(states);
  const c = { on: 0, idle: 0, off: 0 };
  for (const s of Object.values(states)) c[s.group]++;
  $("#n-on").textContent = c.on; $("#n-idle").textContent = c.idle;
  renderMembers(states);
  renderFlow();
  renderToday(states);
  renderLog();
  if (USE_SLOTS) renderBench(states);
}

// ---------- 替换：点人物 → 「替换」按钮 → 替补席里选人 ----------
let popFor = null, benchFor = -1, benchPick = null, lastStates = {}, toastT = 0;
const isFresh = (n, la) => mode === "live" && !slots.includes(n) && (la[n] || 0) > benchSeen;
function showPop(n, o = {}) {
  const pop = $("#pop"); if (!pop) return;
  if (!n || !slots.includes(n)) { hidePop(); return; }
  if (popFor === n && !pop.hidden && !o.label) { hidePop(); return; }
  popFor = n; const s = lastStates[n] || { st: "none" }, i = slots.indexOf(n);
  pop.innerHTML = `<p class="pop-h"><i>${t("pop.slot", { n: i + 1 })}</i><b>${esc(short(n))}</b><em>${WORD[s.st] || ""}</em></p>
    <div class="pop-b"><button class="pop-swap" id="pop-swap">${t("pop.swap")}</button><button class="pop-info" id="pop-info">${t("pop.info")}</button></div>`;
  pop.hidden = false;
  const p = scene?.screenOf(n), st = $("#stage").getBoundingClientRect();
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  const x = p ? Math.min(st.width - pw - 6, Math.max(6, p.x - pw / 2)) : 12, y = p ? Math.min(st.height - ph - 6, Math.max(40, p.y + 8)) : 48;
  pop.style.left = x + "px"; pop.style.top = y + "px";
  pop.classList.remove("go"); void pop.offsetWidth; pop.classList.add("go");
  $("#pop-swap").onclick = () => { const k = slots.indexOf(n); hidePop(); openBench(k); };
  $("#pop-info").onclick = () => { hidePop(); openMember(n); };
  $("#pop-swap").focus({ preventScroll: true });
}
function hidePop() { const pop = $("#pop"); if (pop) pop.hidden = true; popFor = null; }
function openBench(k = -1) {
  benchFor = k; benchPick = null; $("#bench").hidden = false; $("#bench").classList.remove("go"); void $("#bench").offsetWidth; $("#bench").classList.add("go");
  $("#bench-tab").setAttribute("aria-expanded", "true"); renderBench(lastStates); $("#bench-x").focus({ preventScroll: true });
}
function closeBench() {
  if ($("#bench").hidden) return;
  $("#bench").hidden = true; $("#bench-tab").setAttribute("aria-expanded", "false"); benchFor = -1; benchPick = null;
  if (mode === "live") { benchSeen = Date.now(); store.set(SEEN_KEY, String(benchSeen)); }   // 看过了，「新」标记清掉
  renderBench(lastStates);
}
function putOn(n, k) {
  if (k < 0 || k >= SLOT_N || !n) return;
  const out = slots[k], cur = slots.indexOf(n); if (cur === k) return;
  const next = slots.slice(); next[k] = n; if (cur >= 0) next[cur] = out;
  slots = next; saveSlots(); scene?.assign(slots); closeBench(); render();
  toast(t("toast.on", { who: esc(short(n)) }) + t(cur >= 0 ? "toast.swap" : "toast.out", { who: esc(short(out)) }), true);
}
function toast(msg, html = false) {
  const t = $("#swap-toast"); if (!t) return;
  if (html) t.innerHTML = msg; else t.textContent = msg;
  t.hidden = false; t.classList.remove("go"); void t.offsetWidth; t.classList.add("go"); clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 2600);
}
// 内容没变就不重建：新动态推送会频繁触发重画，重建会让正在点的卡片失效（点了没反应、替补席被关掉）
function setHTML(el, h) { if (el.dataset.h !== h) { el.innerHTML = h; el.dataset.h = h; } }
function renderBench(states) {
  lastStates = states; if (!$("#bench-tab")) return;
  const la = lastActOf(shown), bench = ROSTER.filter((b) => !slots.includes(b.name));
  const fresh = bench.filter((b) => isFresh(b.name, la));
  $("#bench-n").textContent = bench.length; $("#bench-n2").textContent = bench.length;
  const nb = $("#bench-new"); nb.hidden = !fresh.length; nb.textContent = fresh.length ? t("bench.new", { n: fresh.length }) : "";
  $("#bench-tab").title = fresh.length ? t("bench.newTip", { names: fresh.map((b) => b.short).join(t("listSep")) }) : t("bench.tip");
  if ($("#bench").hidden) return;
  const order = { on: 0, idle: 1, off: 2 };
  const list = bench.map((b) => ({ b, s: states[b.name] || { st: "none", group: "off" }, f: isFresh(b.name, la), t: la[b.name] || 0 }))
    .sort((x, y) => (y.f - x.f) || (order[x.s.group] - order[y.s.group]) || (y.t - x.t));
  const target = benchFor >= 0 ? slots[benchFor] : null;
  $("#bench-hint").innerHTML = target ? t("bench.hintSwap", { who: esc(short(target)), n: benchFor + 1 })
    : benchPick ? t("bench.hintPick", { who: esc(short(benchPick)) }) : t("bench.hint");
  const sl = $("#bench-slots"); sl.hidden = !benchPick;
  setHTML(sl, benchPick ? slots.map((n, i) => `<button data-k="${i}"><i>${i + 1}</i>${esc(short(n))}</button>`).join("") : "");
  setHTML($("#bench-grid"), list.map(({ b, s, f, t }, i) => `<li><button class="card${benchPick === b.name ? " sel" : ""}" data-bot="${esc(b.name)}" data-g="${s.group}" data-st="${s.st}"${f ? ' data-new="1"' : ""}>
      <span class="seal" aria-hidden="true">${esc(b.seal || [...b.short][0] || "")}</span><b>${esc(b.short)}</b><small>${esc(b.name)}</small>
      <em>${WORD[s.st]}${t ? `<time>${fmtHM.format(t)}</time>` : ""}</em>${f ? `<i class="nw">${t("bench.newMark")}</i>` : ""}</button></li>`).join("")
    || `<li class="empty">${t("bench.empty")}</li>`);
}
if (USE_SLOTS) {
  $("#bench-tab").onclick = () => ($("#bench").hidden ? (hidePop(), openBench(-1)) : closeBench());
  $("#bench-x").onclick = () => closeBench();
  $("#bench-grid").onclick = (e) => {
    const c = e.target.closest(".card"); if (!c) return;
    if (benchFor >= 0) putOn(c.dataset.bot, benchFor);
    else { benchPick = benchPick === c.dataset.bot ? null : c.dataset.bot; renderBench(lastStates); $("#bench-slots button")?.focus({ preventScroll: true }); }
  };
  $("#bench-slots").onclick = (e) => { const b = e.target.closest("button"); if (b && benchPick) putOn(benchPick, Number(b.dataset.k)); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (!$("#bench").hidden) closeBench(); else hidePop(); } });
  document.addEventListener("pointerdown", (e) => {
    if (!$("#pop").hidden && !e.target.closest("#pop, .lab, canvas")) hidePop();
    if (!$("#bench").hidden && !e.target.closest("#bench, #bench-tab")) closeBench();
  });
}

function renderMembers(states) {
  const order = { on: 0, idle: 1, off: 2 };
  const list = ROSTER.map((b) => ({ b, s: states[b.name] })).sort((x, y) => order[x.s.group] - order[y.s.group]);
  $("#mlist").innerHTML = list.map(({ b, s }) => {
    const r = s.ref;
    const note = !r ? "" : s.incoming ? t(r.type === "退回" ? "note.back" : "note.in", { who: short(r.bot), msg: r.message }) : r.message;
    return `<li data-bot="${esc(b.name)}" data-g="${s.group}" data-st="${s.st}" class="${focus === b.name ? "sel" : ""}">
      <i style="${LAMP[s.st] && s.group === "on" ? `--c:${LAMP[s.st]}` : ""}"></i><b>${esc(b.short)}</b><em>${WORD[s.st]}</em>
      <time>${r ? fmtHM.format(r._t) : ""}</time>${note ? `<p>${esc(note)}</p>` : ""}</li>`;
  }).join("");
}
function openMember(n) {
  focus = n; const d = $("#members");
  if (n) { $("#more").open = true; d.open = true; }
  render();
  if (n) $(`#mlist li[data-bot="${CSS.escape(n)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function projects() {
  const seen = new Map();
  for (const e of shown) if (e.project) seen.set(e.project, e._t);
  return [...seen.entries()].sort((a, b) => b[1] - a[1]).map(([p]) => p);
}
const projName = (p) => p.replace(/^\d{4}-?\d{2}-?\d{2}-?/, "");
function renderFlow() {
  const ps = projects();
  if (!pinned || !ps.includes(project)) project = ps[0] || null;
  const sel = $("#proj");
  sel.innerHTML = ps.length ? ps.map((p) => `<option value="${esc(p)}"${p === project ? " selected" : ""}>${esc(projName(p))}</option>`).join("") : `<option>${t("noTaskOpt")}</option>`;
  sel.disabled = ps.length < 2;
  const { steps, cur, latest } = pipeline(shown.filter((e) => e.project === project));
  const lastP = [...shown].reverse().find((e) => e.project === project);
  $("#flow-now").innerHTML = cur < 0 ? (lastP ? t("flow.last", { who: esc(short(lastP.bot)), ty: esc(tyOf(lastP.type)), msg: esc(lastP.message) }) + `<time>${fmtHM.format(lastP._t)}</time>` : t("noTask"))
    : t("flow.step", { n: cur + 1, total: STAGES.length, name: esc(STAGES[cur]) }) + (latest ? `<time>${fmtHM.format(latest._t)}</time>` : "");
  $("#steps").hidden = cur < 0;   // 名单里没配流程步骤、或这个任务没走到任何一步：不画步骤条，只留最新一句
  $("#steps").innerHTML = steps.map((s, i) => `<li data-st="${s.st}" title="${esc(s.name)}${s.e ? t("sep") + esc(s.e.message) : ""}"><span class="sr">${i + 1} ${esc(s.name)}</span></li>`).join("");
}
// 只显示真正要你动手的「待你确认」，有才显示。
function renderToday(states) {
  const nc = Object.values(states).filter((s) => s.st === "confirm").length;
  $("#d-conf").textContent = nc; $("#conf-cell").hidden = nc === 0;
}
function renderLog() {
  const evs = shown.slice(-40).reverse();
  $("#logn").textContent = shown.length;
  $("#log").innerHTML = evs.map((e) => `<li><time>${fmtHM.format(e._t)}</time><b>${esc(short(e.bot))}</b><span class="ty">${e.to ? t("log.to", { ty: esc(tyOf(e.type)), to: esc(short(e.to)) }) : esc(tyOf(e.type))}</span><p>${esc(e.message)}</p><em>${tagOf(e)}</em></li>`).join("") || `<li class="empty">${t("log.empty")}</li>`;
}
function animate(e) { if (e.to && (e.type === "交接" || e.type === "退回")) scene?.handoff(e.bot, e.to, e.type); }

$("#proj").onchange = (e) => { project = e.target.value; pinned = true; render(); };
$("#mlist").onclick = (e) => { const li = e.target.closest("li"); if (li) openMember(li.dataset.bot === focus ? null : li.dataset.bot); };

// ---------- 模式 ----------
let es = null, timer = null, raf = null, playing = true;
let rpIdx = 0, rpDay = [], rpStart = 0, rpEnd = 0, last = 0;
function setConn(k, t) { const c = $("#conn"); c.dataset.k = k; c.querySelector("span").textContent = t; }
function stopAll() { es?.close(); es = null; clearInterval(timer); timer = null; cancelAnimationFrame(raf); scene?.clearFlights(); }

function liveLabel() { setConn("ok", t("conn.live", { time: fmtHM.format(Date.now()) })); }
async function startLive() {
  setConn("wait", t("conn.wait"));
  await loadRoster(); await syncSlots(); if (mode !== "live") return;
  es?.close();
  es = new EventSource("/api/stream");
  es.onerror = () => setConn("bad", t("conn.bad"));
  es.addEventListener("init", (m) => { all = JSON.parse(m.data).filter((e) => !e.test).map(prep).sort(sortT); shown = all.slice(); vnow = Date.now(); applyDefaults(); liveLabel(); render(); });
  es.addEventListener("ev", (m) => {
    const e = prep(JSON.parse(m.data)); if (e.test || all.some((x) => x.id === e.id)) return;
    all.push(e); all.sort(sortT); shown = all.slice(); vnow = Date.now(); liveLabel(); animate(e); render();
  });
  timer = setInterval(() => { vnow = Date.now(); }, 30e3);
}

async function startReplay() {
  setConn("off", t("conn.replay"));
  await loadRoster(); await syncSlots();
  try { all = (await (await fetch("/api/events")).json()).filter((e) => !e.test).map(prep).sort(sortT); } catch { all = []; }
  applyDefaults();
  const days = [...new Set(all.map((e) => dayOf(e._t)))].sort().reverse();
  const sel = $("#day");
  sel.innerHTML = days.length ? days.map((d) => `<option value="${d}">${fmtDate.format(Date.parse(d + "T12:00:00Z"))}</option>`).join("") : `<option>${t("noDays")}</option>`;
  sel.onchange = () => loadDay(sel.value);
  if (days.length) loadDay(days[0]);
}
function loadDay(d) {
  rpDay = all.filter((e) => dayOf(e._t) === d);
  rpStart = rpDay.length ? rpDay[0]._t - 5 * 60e3 : Date.now(); rpEnd = rpDay.length ? rpDay[rpDay.length - 1]._t + 5 * 60e3 : Date.now();
  seek(rpStart); playing = true; syncPlay(); last = performance.now(); cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
}
function seek(t) { vnow = t; scene?.clearFlights(); shown = rpDay.filter((e) => e._t <= t); rpIdx = shown.length; render(); syncScrub(); }
function syncScrub() { $("#scrub").value = String(Math.round(((vnow - rpStart) / Math.max(1, rpEnd - rpStart)) * 1000)); }
function tick(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (playing && mode === "replay") {
    const rate = 600e3; // 每秒走 10 分钟
    vnow += dt * rate;
    const next = rpDay[rpIdx]; if (next && next._t - vnow > 8 * rate) vnow = next._t - 1.2 * rate;
    let ch = false;
    while (rpIdx < rpDay.length && rpDay[rpIdx]._t <= vnow) { const e = rpDay[rpIdx++]; shown.push(e); animate(e); ch = true; }
    if (vnow >= rpEnd) { vnow = rpEnd; playing = false; syncPlay(); }
    if (ch) render(); syncScrub();
  }
  raf = requestAnimationFrame(tick);
}
$("#scrub").oninput = (e) => mode === "replay" && seek(rpStart + (Number(e.target.value) / 1000) * (rpEnd - rpStart));
function syncPlay() { const b = $("#play"); b.textContent = playing ? t("pause") : t("play"); b.setAttribute("aria-label", b.textContent); }
$("#play").onclick = () => { playing = !playing; if (playing && vnow >= rpEnd) seek(rpStart); last = performance.now(); syncPlay(); };

let booted = false;
function setMode(m) {
  if (m !== "replay") m = "live";
  mode = m; stopAll(); pinned = false; focus = null;
  if ($("#bench")) { hidePop(); closeBench(); }
  if (booted) { const w = $(".wipe"); w.classList.remove("go"); void w.offsetWidth; w.classList.add("go"); }   // 红黑斜条横扫
  booted = true;
  document.body.dataset.mode = m;
  document.querySelectorAll(".modes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.m === m)));
  if (m === "replay") $("#more").open = true;
  const p = new URLSearchParams(location.search); if (m === "live") p.delete("mode"); else p.set("mode", m);
  const qs = p.toString(); history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  if (m === "live") startLive(); else startReplay();
}
document.querySelectorAll(".modes button").forEach((b) => (b.onclick = () => b.dataset.m !== mode && setMode(b.dataset.m)));
setMode(mode);
