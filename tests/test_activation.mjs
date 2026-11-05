// 激活显示状态。不连 Notion、不写文件。
//   node tests/test_activation.mjs
import { acceptSyncedActivation, deriveStates } from "../board/src/state.js";

let fails = 0, total = 0;
function check(name, cond) {
  total++;
  if (cond) console.log("ok  ", name);
  else { fails++; console.log("FAIL", name); }
}

const now = Date.parse("2026-11-05T12:00:00.000Z");
const roster = [{ name: "写手" }, { name: "画师" }, { name: "审核员" }];
const ev = (bot, type, minutesAgo, extra = {}) => ({ bot, type, to: extra.to || null, _t: now - minutesAgo * 60e3, message: extra.message || "" });

const none = deriveStates(roster, [], now, []);
check("没有事件的人是空闲，不是未激活", none["写手"].st === "idle" && none["写手"].group === "idle" && none["画师"].st === "idle" && none["审核员"].group === "idle");
check("默认不把任何人标成人工停用", Object.values(none).every((s) => !s.manual && s.st !== "disabled"));

const fresh = deriveStates(roster, [ev("写手", "开始", 30)], now, []);
check("近期开始显示进行中", fresh["写手"].st === "work" && fresh["写手"].group === "on");
check("同一次推导里没事件的人仍是空闲", fresh["画师"].st === "idle" && fresh["审核员"].st === "idle");

const stale = deriveStates(roster, [ev("写手", "开始", 180)], now, []);
check("超过两小时的开始回到空闲", stale["写手"].st === "idle" && stale["写手"].group === "idle");

const handed = deriveStates(roster, [ev("写手", "交接", 10, { to: "审核员" })], now, []);
check("交来的人待接手", handed["审核员"].st === "wait" && handed["审核员"].incoming);
check("刚交接的人显示刚交完", handed["写手"].st === "done");

const disabled = ["画师"];
const before = disabled.slice();
const held = deriveStates(roster, [ev("画师", "开始", 5), ev("写手", "开始", 5)], now, disabled);
check("有新事件也不改人工停用", held["画师"].st === "disabled" && held["画师"].group === "off" && held["画师"].manual);
check("推导不改停用名单本身", disabled.join() === before.join());
check("没被停用的人照常活动", held["写手"].st === "work");

const back = deriveStates(roster, [ev("画师", "开始", 5)], now, []);
check("从停用名单拿掉后，同一条新事件回到活动", back["画师"].st === "work" && back["画师"].manual === false);

const down = deriveStates(roster, [ev("写手", "开始", 5)], now, ["画师"], { linkDown: true });
check("断连或无心跳时，未停用的人显示离线", down["写手"].st === "none" && down["写手"].group === "off" && down["审核员"].st === "none");
check("断连时人工停用仍是停用，不会被画成普通离线", down["画师"].st === "disabled" && down["画师"].manual);

const up = deriveStates(roster, [ev("写手", "开始", 5), ev("审核员", "待确认", 1)], now, ["画师"], { linkDown: false });
check("心跳或事件恢复后，离线的人回到活动", up["写手"].st === "work" && up["审核员"].st === "confirm");
check("自动恢复不把人工停用的人抢回来", up["画师"].st === "disabled" && up["画师"].manual);

const local = { disabled: ["写手"], updatedAt: "2026-11-05T00:02:00.000Z", by: "人工选择（自动恢复不会覆盖）" };
const older = acceptSyncedActivation(local, { disabled: [], updatedAt: "2026-11-05T00:01:00.000Z" });
check("更旧的同步不覆盖已保存的停用", older.disabled.join() === "写手" && older.updatedAt === local.updatedAt);
const notime = acceptSyncedActivation(local, { disabled: [] });
check("没有时间的快照不覆盖已保存的停用", notime.disabled.join() === "写手");
const dup = acceptSyncedActivation(local, { disabled: ["画师", "画师"], updatedAt: "2026-11-05T00:09:00.000Z" });
check("重复名字的同步不覆盖", dup.disabled.join() === "写手");
const newer = acceptSyncedActivation(local, { disabled: [], updatedAt: "2026-11-05T00:03:00.000Z", by: "人工选择（自动恢复不会覆盖）" });
check("更新的全部恢复会覆盖", newer.disabled.length === 0 && newer.updatedAt === "2026-11-05T00:03:00.000Z");
check("接受同步时不改本地原名单", local.disabled.join() === "写手");
const first = acceptSyncedActivation(null, { disabled: ["审核员"], updatedAt: "2026-11-05T00:00:00.000Z" });
check("本地还没有记录时采用同步来的名单", first.disabled.join() === "审核员");

console.log(`${total - fails}/${total} passed`);
process.exit(fails === 0 ? 0 : 1);
