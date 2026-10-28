// 原生层放行规则的测试。Linux / Mac 都能跑：
//   swiftc app/LiveBoard/Policy.swift app/LiveBoard/Store.swift tests/swift/main.swift -o /tmp/policy-tests && /tmp/policy-tests
import Foundation

var fails = 0, total = 0
func check(_ name: String, _ cond: Bool) {
    total += 1
    if cond { print("ok   \(name)") } else { fails += 1; print("FAIL \(name)") }
}
let db = "0123456789abcdef0123456789abcdef"
let dbDash = "01234567-89ab-cdef-0123-456789abcdef"
let other = "ffffffffffffffffffffffffffffffff"
func swapRow(_ parent: String, kind: String = "换人") -> String {
    "{\"parent\":{\"database_id\":\"\(parent)\"},\"properties\":{\"类型\":{\"select\":{\"name\":\"\(kind)\"}}}}"
}

check("normID 去横线、转小写", normID(dbDash.uppercased()) == db)
check("normID 拒绝长度不对", normID("abc") == nil)
check("normID 拒绝非十六进制", normID(String(repeating: "g", count: 32)) == nil)

check("看板：查这张表", Policy.boardAllowed("POST", "/v1/databases/\(db)/query", "{}", db: db))
check("看板：不许查别的表", !Policy.boardAllowed("POST", "/v1/databases/\(other)/query", "{}", db: db))
check("看板：没设置表时什么都不放行", !Policy.boardAllowed("POST", "/v1/databases//query", "{}", db: ""))
check("看板：可以加换人行（带横线 ID 也行）", Policy.boardAllowed("POST", "/v1/pages", swapRow(dbDash), db: db))
check("看板：不许加事件行", !Policy.boardAllowed("POST", "/v1/pages", swapRow(db, kind: "事件"), db: db))
check("看板：不许往别的表加行", !Policy.boardAllowed("POST", "/v1/pages", swapRow(other), db: db))
check("看板：不许改行", !Policy.boardAllowed("PATCH", "/v1/pages/\(db)", "{}", db: db))
check("看板：不许搜索", !Policy.boardAllowed("POST", "/v1/search", "{}", db: db))
check("看板：不许带查询参数绕过", !Policy.boardAllowed("POST", "/v1/databases/\(db)/query?x=1", "{}", db: db))
check("看板：坏 JSON 拒绝", !Policy.boardAllowed("POST", "/v1/pages", "{oops", db: db))

// ---- 设置通道（DS-3：放行范围随向导一步步收窄） ----
let pageA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", relay = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", table = "cccccccccccccccccccccccccccccccc"
let pageSearch = "{\"filter\":{\"property\":\"object\",\"value\":\"page\"},\"page_size\":100}"
func under(_ pid: String) -> String { "{\"parent\":{\"type\":\"page_id\",\"page_id\":\"\(pid)\"},\"properties\":{}}" }
var sc = SetupScope()
check("设置：验证密钥", sc.allows("GET", "/v1/users/me", ""))
check("设置：列出页面（只搜页面）", sc.allows("POST", "/v1/search", pageSearch))
check("DS-3 设置：不许不带过滤地搜索（会列出别的表）", !sc.allows("POST", "/v1/search", "{}"))
check("DS-3 设置：不许搜表", !sc.allows("POST", "/v1/search", "{\"filter\":{\"property\":\"object\",\"value\":\"database\"}}"))
check("DS-3 设置：没选定表时不许读任何表结构", !sc.allows("GET", "/v1/databases/\(other)", ""))
check("DS-3 设置：不许在没列出来的页面下建页面", !sc.allows("POST", "/v1/pages", under(pageA)))
check("DS-3 设置：不许在任意页面下建表", !sc.allows("POST", "/v1/databases", under(pageA)))
sc.record("POST", "/v1/search", status: 403, response: "{\"results\":[{\"object\":\"page\",\"id\":\"\(pageA)\"}]}")
check("DS-3 设置：失败的响应不算数", !sc.allows("POST", "/v1/pages", under(pageA)))
sc.record("POST", "/v1/search", status: 200, response: "{\"results\":[{\"object\":\"page\",\"id\":\"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa\"},{\"object\":\"database\",\"id\":\"\(other)\"}]}")
check("设置：在列出来的页面下建中转页", sc.allows("POST", "/v1/pages", under(pageA)))
check("DS-3 设置：搜索结果里的表不算页面", !sc.allows("POST", "/v1/pages", under(other)))
check("设置：不许往表里加行", !sc.allows("POST", "/v1/pages", "{\"parent\":{\"database_id\":\"\(pageA)\"},\"properties\":{}}"))
check("设置：不许带正文内容建页面", !sc.allows("POST", "/v1/pages", "{\"parent\":{\"page_id\":\"\(pageA)\"},\"children\":[]}"))
sc.record("POST", "/v1/pages", status: 200, response: "{\"object\":\"page\",\"id\":\"\(relay)\"}")
check("设置：在刚建的中转页下建表", sc.allows("POST", "/v1/databases", under(relay)))
check("DS-3 设置：不许在别的页面下建表", !sc.allows("POST", "/v1/databases", under(pageA)))
sc.record("POST", "/v1/databases", status: 200, response: "{\"object\":\"database\",\"id\":\"\(table)\"}")
check("设置：完成时接受刚建的表", sc.canFinish(table))
check("DS-3 设置：完成时不接受别的表", !sc.canFinish(other))
check("DS-3 设置：建完表后仍不许读别的表结构", !sc.allows("GET", "/v1/databases/\(other)", ""))
var s2 = SetupScope()
check("设置：粘贴已有表（带横线）", s2.choose(dbDash))
check("设置：读选定那张表的结构", s2.allows("GET", "/v1/databases/\(dbDash)", ""))
check("DS-3 设置：粘贴后也不许读别的表", !s2.allows("GET", "/v1/databases/\(other)", ""))
check("设置：不许查表内容", !s2.allows("POST", "/v1/databases/\(db)/query", "{}"))
check("设置：不许 GET 路径穿越", !s2.allows("GET", "/v1/databases/\(db)/../../users", ""))
check("设置：不许删除 / 改", !s2.allows("PATCH", "/v1/pages/\(db)", "{\"archived\":true}"))
check("设置：不许列用户", !s2.allows("GET", "/v1/users", ""))
check("设置：选定的表可以完成", s2.canFinish(db) && !s2.canFinish(other))
check("设置：坏 ID 不能选", !s2.choose("not-an-id"))

check("打开链接：Notion 连接页", Policy.openAllowed("https://www.notion.so/profile/integrations"))
check("打开链接：拒绝别的网站", !Policy.openAllowed("https://example.com/"))
check("打开链接：拒绝 http", !Policy.openAllowed("http://www.notion.so/"))
check("打开链接：拒绝伪装域名", !Policy.openAllowed("https://www.notion.so.example.com/"))
check("打开链接：拒绝 file", !Policy.openAllowed("file:///etc/passwd"))

check("密钥格式：正常", Policy.tokenLooksOK("ntn_" + String(repeating: "a", count: 46)))
check("密钥格式：空", !Policy.tokenLooksOK(""))
check("密钥格式：带空格", !Policy.tokenLooksOK("ntn_abc def"))

// ---- 密钥和设置文件（DS-6 原子写入；DS-7 完成设置失败要回滚） ----
let fm = FileManager.default
func freshDir() -> URL { let d = fm.temporaryDirectory.appendingPathComponent("lb-test-\(UUID().uuidString)"); Store.dirOverride = d; return d }
func tok(_ c: Character) -> String { "ntn_" + String(repeating: c, count: 46) }
final class Flag: @unchecked Sendable { var stop = false; var missing = 0 }

var dir = freshDir()
check("存密钥", Store.saveToken(tok("a")) && Store.token() == tok("a"))
let perm = (try? fm.attributesOfItem(atPath: Store.tokenFile.path)[.posixPermissions] as? Int) ?? -1
check("DS-6 密钥文件权限 600", perm == 0o600)
let flag = Flag()
let reader = Thread { while !flag.stop { if (try? Data(contentsOf: Store.tokenFile)) == nil { flag.missing += 1 } } }
reader.start()
for i in 0..<2000 { _ = Store.saveToken(tok(i % 2 == 0 ? "b" : "c")) }
flag.stop = true; Thread.sleep(forTimeInterval: 0.05)
check("DS-6 换密钥时文件一刻也不缺（另一个线程读了一直在，缺失 \(flag.missing) 次）", flag.missing == 0)
let perm2 = (try? fm.attributesOfItem(atPath: Store.tokenFile.path)[.posixPermissions] as? Int) ?? -1
let left = ((try? fm.contentsOfDirectory(atPath: dir.path)) ?? []).filter { $0 != "notion_token" }
check("DS-6 换完仍是 600，不留临时文件", perm2 == 0o600 && left.isEmpty)

dir = freshDir()
_ = Store.saveToken(tok("a")); _ = Store.saveConfig(["database_id": db])
try? fm.removeItem(at: Store.configFile); try? fm.createDirectory(at: Store.configFile, withIntermediateDirectories: true)
fm.createFile(atPath: Store.configFile.appendingPathComponent("x").path, contents: Data())   // config.json 写不进去
let e1 = Store.commitSetup(pending: tok("b"), databaseID: other)
check("DS-7 设置存不进去时报错，原来的密钥不被换掉", e1 != nil && Store.token() == tok("a"))

dir = freshDir()
_ = Store.saveToken(tok("a")); _ = Store.saveConfig(["database_id": db, "keep": 1])
try? fm.removeItem(at: Store.tokenFile); try? fm.createDirectory(at: Store.tokenFile, withIntermediateDirectories: true)
fm.createFile(atPath: Store.tokenFile.appendingPathComponent("x").path, contents: Data())     // 密钥写不进去
let e2 = Store.commitSetup(pending: tok("b"), databaseID: other)
check("DS-7 密钥存不进去时报错，设置退回原样", e2 != nil && Store.databaseID == db && (Store.config()["keep"] as? Int) == 1)

dir = freshDir()
let e3 = Store.commitSetup(pending: tok("d"), databaseID: dbDash)
check("完成设置：密钥和表 ID 都存好", e3 == nil && Store.token() == tok("d") && Store.databaseID == db)
check("完成设置：没有密钥时报错", { _ = freshDir(); return Store.commitSetup(pending: nil, databaseID: db) != nil && !fm.fileExists(atPath: Store.configFile.path) }())

print("\(total - fails)/\(total) passed")
exit(fails == 0 ? 0 : 1)
