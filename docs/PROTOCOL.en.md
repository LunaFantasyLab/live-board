# Data format and Notion protocol

[简体中文](PROTOCOL.md) | **English**

The writer and the Mac app exchange data only through one table in your Notion, "Board data" (`看板数据` when created in Chinese). Both sides use only the public Notion API (`Notion-Version: 2022-06-28`).

> **Fixed identifiers.** Column names (`名称`, `类型`, `序号`, `数据`, `状态`) and select values (`事件`, `工位`, `名单`, `换人`, `待处理`, `已处理`, `已拒绝`) are protocol identifiers. They are the same in every UI language and must not be renamed or translated. Only the titles of the relay page and the table may differ.

## The "Board data" table

| Column | Notion type | Meaning |
|---|---|---|
| `名称` (name) | Title | Event row: the event ID; roster / desk rows: `名单` / `工位`; desk-swap row: `换人 <time>` |
| `类型` (kind) | Select | `事件` (event) / `工位` (desks) / `名单` (roster) / `换人` (desk swap) |
| `序号` (sequence) | Number | Assigned by the writer, only ever increases; the board reads incrementally by it |
| `数据` (data) | Text | A JSON string (longer than 1000 characters it's split into several text segments and joined when read) |
| `状态` (state) | Select | Desk-swap rows only: `待处理` (pending) / `已处理` (done) / `已拒绝` (rejected) |

Who writes what:

| Row | Written by | How |
|---|---|---|
| Event | Writer | One row per check-in, append-only |
| Roster | Writer | A single row, updated (with a new sequence number) when the roster changes |
| Desks | Writer | A single row, updated (with a new sequence number) when the desks change |
| Desk swap | Mac app | One `待处理` row per swap; the writer checks it, sets it to `已处理` or `已拒绝`, and archives it |

How the board reads: a full read the first time; after that only rows with `序号 > highest seen − 50` (a margin of 50 because new Notion rows can take a moment to become queryable).
Every 15 minutes it also asks for the latest roster row and desk row (sequence descending, one row each) so nothing is missed.

## Event (one line of events.jsonl, and the `数据` of an event row)

```json
{"v":1,"id":"01J…","ts":"2026-01-31T09:05:00+00:00","bot":"Researcher","type":"接单","project":"Example task",
 "task_id":null,"to":null,"gate":null,"message":"Got it, looking for sources","files":[],"source":"cli"}
```

| Field | Meaning |
|---|---|
| `id` | Unique, time-ordered ID; the writer de-duplicates by it |
| `ts` | Time with time zone |
| `bot` | Member name; must be in the roster |
| `type` | `接单` claim / `开始` start / `产出` output / `交接` handoff / `退回` return / `待确认` confirm / `完成` done / `报错` error — always stored as the Chinese value; the English names are accepted on the command line and shown in the English UI |
| `project` | Task name (optional); the board groups progress by it |
| `to` | Receiver of a handoff or return |
| `gate` | Optional short tag (letters and digits, at most 16 characters) |
| `message` | One sentence, at most 80 characters; anything that looks like a secret is rejected |
| `files` | File names only, never paths |
| `source` | `cli` (check-in) or `backfill` |
| `test` | When `true`, stays on the local machine: not synced, not shown |

## Roster (roster.json, and the `数据` of the roster row)

See [examples/roster.example.en.json](../examples/roster.example.en.json), [examples/roster.example.json](../examples/roster.example.json) and [examples/README.md](../examples/README.md). Optional field `notice`: a one-line note shown at the top of the board.

## Desks (state/slots.json, and the `数据` of the desk row)

```json
{"slots":["Dispatch","Researcher","Writer","Artist","Editor","Reviewer"],"updatedAt":"2026-01-31T10:00:00+00:00","by":"手动替换"}
```

`by` is a stored note about where the assignment came from; it is not displayed.

## The `数据` of a desk-swap row

```json
{"slots":["Dispatch","Researcher","Writer","Artist","Editor","Analyst"],"ifEmpty":false,"reason":"manual","at":"2026-01-31T10:00:00.000Z"}
```

What the writer does: the six names must be distinct and all in the roster, otherwise the row becomes `已拒绝`; if `ifEmpty` is true and desks already exist, nothing changes.
After writing a desk-swap row the Mac app waits up to 60 seconds; if no new desk row arrives in that time, the board goes back to the previous desks and says the writer doesn't seem to be running.

## Requests the Mac app's native layer allows

Board page (relay.js):

- `POST /v1/databases/{this table}/query`
- `POST /v1/pages`: only rows with `类型 = 换人` in this table

Setup window (setup.js). Every time the setup window opens it starts from zero and unlocks step by step with the wizard:

- `GET /v1/users/me` (verify the token)
- `POST /v1/search`: only with the "pages only" filter (`filter.property = object`, `filter.value = page`), so no table can be listed
- `POST /v1/pages`: the parent must be one of the pages just listed, with no body content (creates the relay page)
- `POST /v1/databases`: the parent must be the relay page the wizard just created, with no body content
- `GET /v1/databases/{id}`: only the table the wizard just created, or the one table the user picked by pasting its link (picking another replaces the previous one)
- **Done** also accepts only that table; the settings are written first, then the token; if the token can't be saved, the settings are rolled back
- The token file is written to a temporary file in the same folder (mode 600) and then atomically replaced

Every other request is refused. The rules are in `app/LiveBoard/Policy.swift`; the tests are in `tests/swift/main.swift`.

## Rate limits

Notion allows about 3 requests per second on average. The writer waits at least about 0.45 s between requests and retries after `Retry-After` on 429.
The board and the setup window wait at least 350 ms between requests and retry up to 3 times on 429 or 5xx.
