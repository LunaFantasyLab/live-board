// 实时看板 · 设置和密钥文件（只依赖 Foundation，Linux 上也能编译和测试：见 tests/swift/）
import Foundation

let kAppName = "LiveBoard"

enum Store {
    /// 测试时把目录指到临时文件夹
    static var dirOverride: URL?
    static var dir: URL {
        if let d = dirOverride { return d }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent(kAppName, isDirectory: true)
    }
    static var tokenFile: URL { dir.appendingPathComponent("notion_token") }
    static var configFile: URL { dir.appendingPathComponent("config.json") }

    static func ensureDir() throws {
        let fm = FileManager.default
        try fm.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try? fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: dir.path)
    }
    static func token() -> String? {
        guard let t = try? String(contentsOf: tokenFile, encoding: .utf8) else { return nil }
        let s = t.trimmingCharacters(in: .whitespacesAndNewlines)
        return s.isEmpty ? nil : s
    }
    @discardableResult static func saveToken(_ t: String) -> Bool {
        let s = t.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return false }
        do { try ensureDir() } catch { return false }
        return writeSecretFile(Data((s + "\n").utf8), to: tokenFile)
    }
    /// 写只有自己能读的文件（600）：先写同目录下的临时文件，再原子替换，替换过程中旧文件一直完整可读
    static func writeSecretFile(_ data: Data, to url: URL) -> Bool {
        let tmp = url.deletingLastPathComponent().appendingPathComponent(".\(url.lastPathComponent).\(UUID().uuidString).tmp")
        let fd = open(tmp.path, O_WRONLY | O_CREAT | O_EXCL, 0o600)   // 一创建就是 600，不经过别的权限
        guard fd >= 0 else { return false }
        var ok = fchmod(fd, 0o600) == 0
        ok = ok && data.withUnsafeBytes { b -> Bool in
            var off = 0
            while off < b.count {
                let n = write(fd, b.baseAddress!.advanced(by: off), b.count - off)
                if n <= 0 { return false }
                off += n
            }
            return true
        }
        ok = ok && fsync(fd) == 0
        close(fd)
        if ok && rename(tmp.path, url.path) == 0 { return true }
        unlink(tmp.path)
        return false
    }
    static func config() -> [String: Any] {
        guard let d = try? Data(contentsOf: configFile), let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return [:] }
        return o
    }
    @discardableResult static func saveConfig(_ o: [String: Any]) -> Bool {
        guard let d = try? JSONSerialization.data(withJSONObject: o, options: [.prettyPrinted, .sortedKeys]) else { return false }
        do { try ensureDir(); try d.write(to: configFile, options: .atomic); return true } catch { return false }
    }
    /// 看板数据表的 ID（设置向导写进 config.json，不是密钥）
    static var databaseID: String { normID((config()["database_id"] as? String) ?? "") ?? "" }
    static var isConfigured: Bool { !databaseID.isEmpty && token() != nil }
    /// 设置向导点「完成」：先写设置，再提交密钥；密钥存不进去就把设置退回原样。
    /// 返回 nil 表示成功，否则是给人看的错误。
    static func commitSetup(pending: String?, databaseID: String) -> String? {
        guard let id = normID(databaseID) else { return L("err.badTable") }
        guard pending != nil || token() != nil else { return L("err.noToken") }
        let before = try? Data(contentsOf: configFile)
        var c = config(); c["database_id"] = id
        guard saveConfig(c) else { return L("err.saveConfig") }
        if let t = pending, !saveToken(t) {
            if let d = before { try? d.write(to: configFile, options: .atomic) } else { try? FileManager.default.removeItem(at: configFile) }
            return L("err.saveToken")
        }
        return nil
    }
}
