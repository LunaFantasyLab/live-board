// 成员显示状态。只影响看板怎么画，不启动、不唤醒、不派活。
// 人工停用（disabled）是唯一会保存的开关，默认空 = 名单里每个人都已激活。
// 从没出现在事件里 = 空闲，不是未激活。
// linkDown：连接断开或心跳超时。这时未人工停用的人显示离线；心跳或新事件到来后按事件回到活动。
// 人工停用的人保持停用，自动恢复不会把他们从名单里拿掉。

const H = 3600e3;
const ACTIVE = new Set(["work", "wait", "back", "confirm", "error"]);

export function deriveStates(roster, evs, now, disabledNames, opts = {}) {
  const disabled = new Set(Array.isArray(disabledNames) ? disabledNames : []);
  const linkDown = !!opts.linkDown;
  const last = {}, lastIn = {};
  for (const e of evs || []) {
    if (!e || typeof e.bot !== "string") continue;
    last[e.bot] = e;
    if (e.to && (e.type === "交接" || e.type === "退回")) lastIn[e.to] = e;
  }
  const out = {};
  for (const b of roster || []) {
    if (!b || typeof b.name !== "string" || !b.name) continue;
    const l = last[b.name] || null, i = lastIn[b.name];
    if (disabled.has(b.name)) {
      out[b.name] = { st: "disabled", group: "off", ref: l, incoming: false, manual: true };
      continue;
    }
    if (linkDown) {
      out[b.name] = { st: "none", group: "off", ref: l, incoming: false, manual: false };
      continue;
    }
    let st = "idle", ref = l, incoming = false;
    if (i && (!l || i._t >= l._t) && now - i._t < 24 * H) {
      st = i.type === "退回" ? "back" : "wait"; ref = i; incoming = true;
    } else if (l) {
      const age = now - l._t;
      if (l.type === "报错") st = "error";
      else if (l.type === "待确认") st = "confirm";
      else if (["交接", "完成", "退回"].includes(l.type)) st = age < 8 * H ? "done" : "idle";
      else st = age < 2 * H ? "work" : "idle";
    }
    out[b.name] = { st, group: ACTIVE.has(st) ? "on" : "idle", ref, incoming, manual: false };
  }
  return out;
}

function copyRec(r) {
  return { disabled: (r.disabled || []).slice(), updatedAt: r.updatedAt || "", by: r.by || "" };
}

/** 刷新和自动同步带来的名单：比本地已保存的旧，或没有时间，就不覆盖。用户点击保存不走这里。 */
export function acceptSyncedActivation(local, incoming) {
  const base = local && Array.isArray(local.disabled) ? local : { disabled: [], updatedAt: "", by: "" };
  if (!incoming || !Array.isArray(incoming.disabled) || incoming.disabled.some((n) => typeof n !== "string")) return copyRec(base);
  if (new Set(incoming.disabled).size !== incoming.disabled.length) return copyRec(base);
  const incAt = typeof incoming.updatedAt === "string" ? incoming.updatedAt : "";
  const locAt = typeof base.updatedAt === "string" ? base.updatedAt : "";
  if (locAt && (!incAt || incAt < locAt)) return copyRec(base);
  return { disabled: incoming.disabled.slice(), updatedAt: incAt, by: typeof incoming.by === "string" ? incoming.by : "" };
}
