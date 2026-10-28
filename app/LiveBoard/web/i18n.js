// 实时看板 · 设置向导和 Notion 中转层（relay.js）的界面文字：简体中文 / English。
// 用哪种语言：App 注入的 window.__LIVEBOARD_LANG（菜单或向导里选的）优先，其次网址里的 ?lang=，再看浏览器 / 系统语言，都不是中文就用英文。
// Notion 表的列名和选项（名称 / 类型 / 事件 …）是数据格式的一部分，两种语言下都不变。
(() => {
  "use strict";
  const STRINGS = {
    zh: {
      "title": "设置实时看板",
      "steps": "进度", "dot.1": "连接", "dot.2": "选位置", "dot.3": "完成", "lang.label": "语言", "lang.system": "跟随系统",
      "s1.h": "第 1 步：粘贴 Notion 连接密钥",
      "s1.how1": "点下面的按钮，打开 Notion 的「连接」页面，新建一个<b>内部连接</b>（名字随意，比如「实时看板」）。",
      "s1.how2": "建好后复制它的密钥（以 <code>ntn_</code> 或 <code>secret_</code> 开头），粘贴到下面。",
      "s1.open": "打开 Notion 连接页面", "s1.label": "连接密钥", "s1.placeholder": "粘贴到这里", "s1.verify": "验证",
      "s1.keep": "这台 Mac 上已经保存过密钥。", "s1.useSaved": "沿用已保存的密钥",
      "s1.note": "密钥只保存在这台 Mac 上（权限 600 的文件），看板网页读不到它。",
      "s2.h": "第 2 步：选一个 Notion 页面放看板数据",
      "s2.how1": "在 Notion 里打开一个页面（建议新建一个空页面）。",
      "s2.how2": "点右上角「⋯」→「连接」，选你刚建的连接。",
      "s2.how3": "回到这里点「刷新列表」，选中那个页面。",
      "s2.reload": "刷新列表", "s2.pages": "可用的页面", "s2.back": "上一步", "s2.create": "在这个页面里新建看板表",
      "s2.existing": "已经有看板数据表了？", "s2.dbLabel": "表的链接或 ID", "s2.dbPlaceholder": "https://www.notion.so/… 或 32 位 ID", "s2.useDb": "用这张表",
      "s3.h": "第 3 步：设置好了", "s3.dbid": "看板数据表 ID（不是密钥，可以放心复制）：",
      "s3.next": "接下来在<b>写入数据的那台电脑</b>上运行一次（会提示你粘贴同一个连接密钥）：",
      "s3.copy": "复制这行命令", "s3.finish": "打开看板",
      "why.401": "密钥不对：请确认复制的是完整的连接密钥",
      "why.403": "这个连接没有权限做这件事（检查连接的权限设置是否允许读取、插入、更新内容）",
      "why.404": "找不到：这个页面或表还没加上你的连接",
      "why.429": "Notion 说请求太快了，请稍等几秒再试",
      "why.0": "连不上 Notion，请检查网络",
      "why.other": "Notion 出错了（{status}）{detail}", "why.detail": "：{message}",
      "m.pasteFirst": "请先粘贴连接密钥",
      "m.notToken": "看起来不像 Notion 连接密钥：应该以 ntn_ 或 secret_ 开头，中间没有空格",
      "m.notSaved": "没存进去，请再试一次", "m.noSaved": "这台 Mac 上没有已保存的密钥，请粘贴", "m.verifying": "正在验证…",
      "m.valid": "密钥有效", "m.validName": "：连接「{name}」", "m.validWs": "，工作区「{ws}」",
      "m.loadingPages": "正在读取这个连接能看到的页面…",
      "m.noPages": "还没有页面加上这个连接。按上面 1–3 做完再点「刷新列表」。",
      "m.foundPages": "找到 {n} 个页面，选一个：", "m.untitled": "（无标题页面）",
      "m.creatingRoot": "正在「{page}」里新建「{root}」页面…", "m.creatingDb": "正在新建「{db}」表…",
      "m.created": "已在「{page}」里新建「{root}」页面和「{db}」表",
      "m.badId": "没认出表的 ID：请粘贴表的链接，或 32 位 ID", "m.checking": "正在检查这张表…",
      "m.badCols": "这张表缺少或类型不对的列：{cols}", "m.colSep": "、", "m.col": "{name}（{type}）",
      "m.usingDb": "用已有的表「{title}」", "m.copied": "已复制", "m.saveFailed": "没保存成功，请再试一次", "m.saved": "已保存",
      "notion.root": "实时看板中转", "notion.db": "看板数据",
      "r.401": "还没连上数据：连接密钥不对", "r.403": "还没连上数据：这个连接没有权限",
      "r.404": "还没连上数据：Notion 里的看板中转页还没加上连接", "r.noToken": "还没连上数据：还没填连接密钥",
      "r.offline": "连不上 Notion，正在重试", "r.error": "Notion 暂时出错（{status}），正在重试",
      "r.pending": "换人还没生效：写入端（liveboard.py sync）好像没在运行",
      "r.badSlots": "slots 要是 {n} 个不重复、名单里有的名字", "r.noDb": "还没连上数据：缺少看板中转表的设置",
    },
    en: {
      "title": "Set up Live Board",
      "steps": "Progress", "dot.1": "Connect", "dot.2": "Location", "dot.3": "Done", "lang.label": "Language", "lang.system": "System default",
      "s1.h": "Step 1: Paste your Notion integration token",
      "s1.how1": "Click the button below to open Notion's Integrations page and create a new <b>internal integration</b> (any name, e.g. “Live Board”).",
      "s1.how2": "Copy its secret (it starts with <code>ntn_</code> or <code>secret_</code>) and paste it below.",
      "s1.open": "Open Notion integrations", "s1.label": "Integration token",
      "s1.placeholder": "Paste it here", "s1.verify": "Verify",
      "s1.keep": "A token is already saved on this Mac.", "s1.useSaved": "Use the saved token",
      "s1.note": "The token is stored only on this Mac (a file with 600 permissions). The board page can't read it.",
      "s2.h": "Step 2: Pick a Notion page to hold the board data",
      "s2.how1": "Open a page in Notion (a new empty page works best).",
      "s2.how2": "Click “⋯” in the top-right corner → “Connections” and choose the integration you just created.",
      "s2.how3": "Come back here, click “Refresh list” and select that page.",
      "s2.reload": "Refresh list", "s2.pages": "Available pages", "s2.back": "Back", "s2.create": "Create the board table in this page",
      "s2.existing": "Already have a board data table?", "s2.dbLabel": "Table link or ID", "s2.dbPlaceholder": "https://www.notion.so/… or a 32-character ID", "s2.useDb": "Use this table",
      "s3.h": "Step 3: All set", "s3.dbid": "Board table ID (not a secret, safe to copy):",
      "s3.next": "Next, run this once on <b>the computer that writes the data</b> (it will ask you to paste the same integration token):",
      "s3.copy": "Copy this command", "s3.finish": "Open the board",
      "why.401": "Wrong token: make sure you copied the whole integration token",
      "why.403": "This integration isn't allowed to do that (check that its capabilities allow reading, inserting and updating content)",
      "why.404": "Not found: this page or table hasn't been connected to your integration yet",
      "why.429": "Notion says the requests are too fast. Please wait a few seconds and try again",
      "why.0": "Can't reach Notion. Please check your network",
      "why.other": "Notion returned an error ({status}){detail}", "why.detail": ": {message}",
      "m.pasteFirst": "Please paste the integration token first",
      "m.notToken": "That doesn't look like a Notion integration token: it should start with ntn_ or secret_ and contain no spaces",
      "m.notSaved": "Couldn't save it. Please try again", "m.noSaved": "There's no saved token on this Mac. Please paste one", "m.verifying": "Verifying…",
      "m.valid": "Token is valid", "m.validName": ": integration “{name}”", "m.validWs": ", workspace “{ws}”",
      "m.loadingPages": "Loading the pages this integration can see…",
      "m.noPages": "No page is connected to this integration yet. Finish steps 1–3 above, then click “Refresh list”.",
      "m.foundPages": "Found {n} page(s). Pick one:", "m.untitled": "(Untitled page)",
      "m.creatingRoot": "Creating the “{root}” page in “{page}”…", "m.creatingDb": "Creating the “{db}” table…",
      "m.created": "Created the “{root}” page and the “{db}” table in “{page}”",
      "m.badId": "Couldn't find a table ID: paste the table's link or its 32-character ID", "m.checking": "Checking this table…",
      "m.badCols": "This table is missing columns or has the wrong column types: {cols}", "m.colSep": ", ", "m.col": "{name} ({type})",
      "m.usingDb": "Using the existing table “{title}”", "m.copied": "Copied", "m.saveFailed": "Couldn't save. Please try again", "m.saved": "Saved",
      "notion.root": "Live Board relay", "notion.db": "Board data",
      "r.401": "Not connected yet: the integration token is wrong", "r.403": "Not connected yet: this integration doesn't have permission",
      "r.404": "Not connected yet: the board relay page in Notion isn't connected to the integration", "r.noToken": "Not connected yet: no integration token has been entered",
      "r.offline": "Can't reach Notion, retrying", "r.error": "Notion error ({status}), retrying",
      "r.pending": "The swap hasn't taken effect: the writer (liveboard.py sync) doesn't seem to be running",
      "r.badSlots": "slots must be {n} distinct names from the roster", "r.noDb": "Not connected yet: the board relay table isn't configured",
    },
  };
  function pick(forced, langs) {
    if (forced === "zh" || forced === "en") return forced;
    for (const l of langs || []) {
      const s = String(l || "").toLowerCase();
      if (s.startsWith("zh")) return "zh";
      if (s.startsWith("en")) return "en";
    }
    return "en";
  }
  function detect() {
    let q = "";
    try { q = new URLSearchParams(location.search).get("lang") || ""; } catch { /* 没有 location */ }
    const nav = typeof navigator !== "undefined" ? (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language]) : [];
    return pick(window.__LIVEBOARD_LANG || q, nav);
  }
  const I = {
    STRINGS, pick, detect, lang: detect(),
    t(key, vars) {
      const s = (STRINGS[I.lang] && STRINGS[I.lang][key]) ?? STRINGS.zh[key] ?? key;
      return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
    },
  };
  window.__LB_I18N = I;
})();
