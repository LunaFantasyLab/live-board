// 看板的固定词表。成员名单、标题、流程步骤都不写死在这里：运行时从 /api/roster（也就是 Notion 表里的「名单」行，
// 内容就是写入端的 roster.json）读取。
export const TYPES = ["接单", "开始", "产出", "交接", "退回", "待确认", "完成", "报错"];

// 名单没给标题时用这个
export const DEFAULT_TITLE = "实时看板";

// 工位数量和 3D 模型（studio6.glb）一一对应
export const SLOT_N = 6;
