# 示例文件

| 文件 | 放到哪里 | 说明 |
|---|---|---|
| `roster.example.json` | 写入端：`~/.liveboard/roster.json`（`init` 时没有名单会自动复制这份） | 名单：看板标题、流程步骤、成员 |
| `events.example.jsonl` | 只用来看格式 | 事件格式示例：平时用 `liveboard.py ev` 打卡，不用手写 |
| `app-config.example.json` | Mac：`~/Library/Application Support/LiveBoard/config.json` | 设置向导会自动写；一般不用手改。`timezone` 可省略（默认按本机时区） |

## 名单字段

- `title`：看板左上角的标题（可省略，默认「实时看板」）
- `stages`：流程步骤（可省略；省略就不显示步骤条）
- `bots[]`：成员
  - `name`：成员名（必填，唯一；打卡时 `--bot` 用它）
  - `short`：工位名牌上的短名（可省略，默认等于 name）
  - `seal`：成员列表里的一个字标记（可省略，默认取 short 的第一个字）
  - `stage`：这个成员负责 `stages` 里的第几步（从 0 开始，可省略）

工位一共 6 个。名单超过 6 人时，其余成员在「替补席」里，点工位上的人可以换。

## Mac App 设置（config.json）可选项

- `timezone`：看板显示时间用的时区，如 `"Asia/Tokyo"`；不写按本机时区
- `active_ms` / `idle_ms`：小窗打开 / 收起时多久读一次 Notion（毫秒），默认 3000 / 30000
