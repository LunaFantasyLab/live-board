// 实时看板 · 原生层放行规则（只依赖 Foundation，Linux 上也能编译和测试：见 tests/swift/）
import Foundation

/// 32 位十六进制 ID（Notion 的页面 / 表 ID 去掉横线）
func normID(_ s: String) -> String? {
    let h = s.replacingOccurrences(of: "-", with: "").lowercased()
    guard h.count == 32, h.allSatisfy({ $0.isHexDigit }) else { return nil }
    return h
}

func jsonObject(_ body: String) -> [String: Any]? { (try? JSONSerialization.jsonObject(with: Data(body.utf8))) as? [String: Any] }


enum Policy {
    /// 看板通道：只放行「查这张表」和「在这张表里加换人行」
    static func boardAllowed(_ method: String, _ path: String, _ body: String, db: String) -> Bool {
        guard !db.isEmpty else { return false }
        if method == "POST" && path == "/v1/databases/\(db)/query" { return true }
        if method == "POST" && path == "/v1/pages",
           let o = jsonObject(body),
           let parent = o["parent"] as? [String: Any],
           let pid = parent["database_id"] as? String, normID(pid) == db,
           let props = o["properties"] as? [String: Any],
           let kind = (props["类型"] as? [String: Any])?["select"] as? [String: Any],
           (kind["name"] as? String) == "换人" { return true }
        return false
    }
    /// 设置向导里「打开 Notion 连接页面」只许打开 Notion 自己的网页
    static func openAllowed(_ s: String) -> Bool {
        guard let u = URL(string: s), u.scheme == "https", let h = u.host else { return false }
        return ["www.notion.so", "notion.so", "www.notion.com", "notion.com", "developers.notion.com"].contains(h)
    }
    static func tokenLooksOK(_ t: String) -> Bool { !t.isEmpty && t.count < 300 && !t.contains(where: { $0.isWhitespace }) }
}

/// 设置向导这一次打开期间的放行范围：随向导一步步收窄，关掉向导就清空。
/// - 验证密钥：GET /v1/users/me
/// - 列页面：POST /v1/search，且只许带「只要页面」的过滤（列不出任何表）
/// - 建中转页：POST /v1/pages，父页面必须是刚才搜索结果里出现过的普通页面
/// - 建表：POST /v1/databases，父页面必须是向导刚建的那个中转页
/// - 读表结构：GET /v1/databases/{id}，只许读向导刚建的表，或用户粘贴链接选定的那一张
/// 只有 Notion 返回 200 的响应才会放宽范围。
struct SetupScope {
    private(set) var pages = Set<String>()
    private(set) var relayPage: String?
    private(set) var table: String?

    func allows(_ method: String, _ path: String, _ body: String) -> Bool {
        if method == "GET" && path == "/v1/users/me" { return true }
        if method == "POST" && path == "/v1/search" {
            guard let o = jsonObject(body), let f = o["filter"] as? [String: Any] else { return false }
            return (f["property"] as? String) == "object" && (f["value"] as? String) == "page"
        }
        if method == "GET", path.hasPrefix("/v1/databases/") {
            guard let t = table, let id = normID(String(path.dropFirst("/v1/databases/".count))) else { return false }
            return id == t
        }
        if method == "POST" && (path == "/v1/pages" || path == "/v1/databases") {
            guard let o = jsonObject(body), o["children"] == nil, let parent = o["parent"] as? [String: Any],
                  let pid = normID((parent["page_id"] as? String) ?? "") else { return false }
            return path == "/v1/pages" ? pages.contains(pid) : pid == relayPage
        }
        return false
    }
    /// 用户粘贴了已有表的链接：从此只许读这一张（换一张就替换掉上一张）
    mutating func choose(_ id: String) -> Bool { guard let h = normID(id) else { return false }; table = h; return true }
    /// 请求成功后，按 Notion 的响应放宽下一步需要的范围
    mutating func record(_ method: String, _ path: String, status: Int, response: String) {
        guard status == 200, let o = jsonObject(response) else { return }
        if method == "POST" && path == "/v1/search" {
            for r in (o["results"] as? [[String: Any]]) ?? [] where (r["object"] as? String) == "page" {
                if let id = normID((r["id"] as? String) ?? "") { pages.insert(id) }
            }
        } else if method == "POST" && path == "/v1/pages", (o["object"] as? String) == "page" {
            relayPage = normID((o["id"] as? String) ?? "")
        } else if method == "POST" && path == "/v1/databases", (o["object"] as? String) == "database" {
            table = normID((o["id"] as? String) ?? "")
        }
    }
    /// 完成时只接受这次向导建的 / 选定的那张表
    func canFinish(_ id: String) -> Bool { guard let h = normID(id), let t = table else { return false }; return h == t }
}
