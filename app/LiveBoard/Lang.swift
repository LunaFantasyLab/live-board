// 界面语言：跟随系统 / 简体中文 / English。只用 Foundation，Linux 上也能跑单元测试（tests/swift/main.swift）。
// 选择存在 UserDefaults 的 "language" 里；切换后菜单、提示和网页马上换（网页靠重新加载）。
// 访达和「登录项」里的 App 名由 macOS 按系统语言取 <语言>.lproj/InfoPlist.strings，不跟这个设置走。
import Foundation

enum L10n {
    static let prefKey = "language"
    static let choices = ["system", "zh-Hans", "en"]
    static var defaults: UserDefaults = .standard
    static var systemLanguages: () -> [String] = { Locale.preferredLanguages }
    static var resourceDir: URL? = Bundle.main.resourceURL { didSet { cache = [:] } }
    private static var cache: [String: [String: String]] = [:]

    /// 用户的选择："system"（默认）/ "zh-Hans" / "en"；不认识的值当 "system"
    static var preference: String {
        get {
            let v = defaults.string(forKey: prefKey) ?? "system"
            return choices.contains(v) ? v : "system"
        }
        set { defaults.set(choices.contains(newValue) ? newValue : "system", forKey: prefKey) }
    }

    /// 实际用哪套文字。手动选的优先；跟随系统时按系统语言顺序找第一个中文或英文，都没有就用英文
    static func resolve(_ pref: String, system: [String]) -> String {
        if pref == "zh-Hans" || pref == "en" { return pref }
        for l in system {
            let s = l.lowercased()
            if s.hasPrefix("zh") { return "zh-Hans" }
            if s.hasPrefix("en") { return "en" }
        }
        return "en"
    }

    static var current: String { resolve(preference, system: systemLanguages()) }
    /// 交给网页的语言代码（window.__LIVEBOARD_LANG）
    static var web: String { current == "en" ? "en" : "zh" }

    static func table(_ lang: String) -> [String: String] {
        if let t = cache[lang] { return t }
        var t: [String: String] = [:]
        if let dir = resourceDir,
           let data = try? Data(contentsOf: dir.appendingPathComponent("\(lang).lproj/Localizable.strings")),
           let o = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: String] {
            t = o
        }
        cache[lang] = t
        return t
    }

    /// 取一条文字：当前语言 → 简体中文 → key 本身
    static func t(_ key: String) -> String {
        table(current)[key] ?? table("zh-Hans")[key] ?? key
    }
}

func L(_ key: String) -> String { L10n.t(key) }
func L(_ key: String, _ args: CVarArg...) -> String { String(format: L10n.t(key), arguments: args) }
