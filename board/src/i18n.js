// 看板界面文字：简体中文 / English。
// 用哪种语言：App 注入的 window.__LIVEBOARD_LANG（菜单或设置向导里选的）优先，其次网址里的 ?lang=zh / ?lang=en，
// 再看浏览器 / 系统语言（中文 → 中文，其他 → 英文）。App 里换语言会重新加载页面。
// 只翻译界面：成员名、任务名、动态内容、名单标题都是用户自己的数据，原样显示。
// 事件类型（接单 / 开始 / 产出 / 交接 / 退回 / 待确认 / 完成 / 报错）是数据格式的一部分，存的还是中文，显示时才翻译（ty.*）。

export const STRINGS = {
  zh: {
    "title": "实时看板",
    "conn.wait": "连接中", "conn.live": "实况，{time} 更新", "conn.bad": "连接断开，正在重连", "conn.replay": "回放",
    "stage.label": "{n} 个工位，点人物可以替换", "loading": "正在载入模型", "loadFail": "模型没载入：{msg}",
    "bench": "替补席", "bench.close": "关闭", "bench.closeLabel": "关闭替补席", "pop.label": "工位操作",
    "online.label": "在线状态", "on": "工作中", "idle": "空闲", "confirm": "待你确认",
    "flow.label": "当前任务流程", "flow.tag": "进度", "task": "任务", "noTask": "还没有任务", "noTaskOpt": "暂无任务",
    "flow.step": "第 <b>{n}</b> 步，共 {total} 步：{name}", "flow.last": "{who} {ty}：{msg}", "sep": "：",
    "more": "更多", "members": "成员", "log": "最近动态", "views": "视图", "live": "实况", "replay": "回放",
    "day": "回放日期", "pause": "暂停", "play": "播放", "scrub": "回放进度", "noDays": "没有记录",
    "st.work": "进行中", "st.wait": "待接手", "st.back": "被退回", "st.confirm": "待你确认", "st.error": "报错", "st.done": "刚交完", "st.idle": "空闲", "st.none": "未激活",
    "tag.test": "测试", "tag.watcher": "推断", "tag.backfill": "补记", "tag.checkin": "打卡",
    "unsigned": "未署名",
    "note.in": "{who}交来：{msg}", "note.back": "{who}退回：{msg}",
    "log.to": "{ty}给{to}", "log.empty": "还没有动态。成员打卡以后会出现在这里。",
    "pop.slot": "工位 {n}", "pop.swap": "替换", "pop.info": "详情",
    "toast.on": "<b>{who}</b> 上场", "toast.swap": "，和 <b>{who}</b> 换位", "toast.out": "，<b>{who}</b> 回替补席",
    "toast.notSaved": "没存到服务器，只有这台设备记得",
    "bench.new": "{n} 新", "bench.newTip": "替补席里有新动态：{names}", "bench.tip": "替补席：没上工位的成员", "listSep": "、",
    "bench.hintSwap": "换下 <b>{who}</b>（工位 {n}），点一位上场", "bench.hintPick": "<b>{who}</b> 坐哪个工位？点下面的工位",
    "bench.hint": "点一位成员，再选它坐哪个工位", "bench.newMark": "新", "bench.empty": "全员都在工位上",
    "meter": "{fps} fps · CPU {cpu} ms/帧 · {calls} 次绘制 · DPR {dpr}",
    "ty.接单": "接单", "ty.开始": "开始", "ty.产出": "产出", "ty.交接": "交接", "ty.退回": "退回", "ty.待确认": "待确认", "ty.完成": "完成", "ty.报错": "报错",
  },
  en: {
    "title": "Live Board",
    "conn.wait": "Connecting", "conn.live": "Live · updated {time}", "conn.bad": "Disconnected, reconnecting", "conn.replay": "Replay",
    "stage.label": "{n} desks. Click a figure to swap it", "loading": "Loading the 3D scene", "loadFail": "The 3D scene didn't load: {msg}",
    "bench": "Bench", "bench.close": "Close", "bench.closeLabel": "Close the bench", "pop.label": "Desk actions",
    "online.label": "Status", "on": "Working", "idle": "Idle", "confirm": "Needs you",
    "flow.label": "Current task progress", "flow.tag": "Progress", "task": "Task", "noTask": "No tasks yet", "noTaskOpt": "No tasks",
    "flow.step": "Step <b>{n}</b> of {total}: {name}", "flow.last": "{who} {ty}: {msg}", "sep": ": ",
    "more": "More", "members": "Members", "log": "Recent activity", "views": "View", "live": "Live", "replay": "Replay",
    "day": "Replay date", "pause": "Pause", "play": "Play", "scrub": "Replay position", "noDays": "No records",
    "st.work": "Working", "st.wait": "Up next", "st.back": "Sent back", "st.confirm": "Needs you", "st.error": "Error", "st.done": "Just handed off", "st.idle": "Idle", "st.none": "Not started",
    "tag.test": "test", "tag.watcher": "inferred", "tag.backfill": "backfill", "tag.checkin": "check-in",
    "unsigned": "Unknown",
    "note.in": "From {who}: {msg}", "note.back": "Sent back by {who}: {msg}",
    "log.to": "{ty} → {to}", "log.empty": "No activity yet. It shows up here once members check in.",
    "pop.slot": "Desk {n}", "pop.swap": "Swap", "pop.info": "Details",
    "toast.on": "<b>{who}</b> is in", "toast.swap": ", swapped with <b>{who}</b>", "toast.out": ", <b>{who}</b> goes to the bench",
    "toast.notSaved": "Not saved to the server. Only this device remembers it",
    "bench.new": "{n} new", "bench.newTip": "New activity on the bench: {names}", "bench.tip": "Bench: members without a desk", "listSep": ", ",
    "bench.hintSwap": "Replacing <b>{who}</b> (desk {n}). Pick someone to bring in", "bench.hintPick": "Which desk for <b>{who}</b>? Pick a desk below",
    "bench.hint": "Pick a member, then choose a desk", "bench.newMark": "new", "bench.empty": "Everyone has a desk",
    "meter": "{fps} fps · CPU {cpu} ms/frame · {calls} draws · DPR {dpr}",
    "ty.接单": "claim", "ty.开始": "start", "ty.产出": "output", "ty.交接": "handoff", "ty.退回": "return", "ty.待确认": "confirm", "ty.完成": "done", "ty.报错": "error",
  },
};

/** forced：App 注入的或网址里的；langs：浏览器语言列表。中文 → "zh"，英文 → "en"，都没有 → "en" */
export function pickLang(forced, langs) {
  if (forced === "zh" || forced === "en") return forced;
  for (const l of langs || []) {
    const s = String(l || "").toLowerCase();
    if (s.startsWith("zh")) return "zh";
    if (s.startsWith("en")) return "en";
  }
  return "en";
}

function detect() {
  if (typeof window === "undefined") return "en";
  let q = "";
  try { q = new URLSearchParams(window.location.search).get("lang") || ""; } catch { /* 没有 location */ }
  const nav = typeof navigator !== "undefined" ? (navigator.languages?.length ? navigator.languages : [navigator.language]) : [];
  return pickLang(window.__LIVEBOARD_LANG || q, nav);
}

export const LANG = detect();
const TABLE = STRINGS[LANG];

/** 取一条界面文字；{name} 换成 vars 里的值（值要先自己转义好） */
export function t(key, vars) {
  const s = TABLE[key] ?? STRINGS.zh[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}
/** 事件类型的显示名（存的是中文协议值） */
export const tyOf = (type) => TABLE["ty." + type] ?? type;
