// 实时看板 · Mac 菜单栏小程序
// Swift / AppKit 单文件，无第三方依赖。菜单栏单色立方体图标，左键弹出 21:9 小窗（约占屏幕 1/4），点别处收起，不进 Dock。
// - 数据：写入端把事件、名单、工位写进你自己 Notion 里的私有「看板数据」表，这里从那张表读（换人也写回那张表）。
//   不连任何服务器、不走任何隧道。
// - 看板网页打包在 App 里（Contents/Resources/board），用 liveboard://local/ 提供。
// - 网页里的 relay.js 把看板要的接口接到 Notion；Notion 请求由这里发（window.webkit.messageHandlers.notion），
//   只放行两种：查这张表、在这张表里加「换人」行。连接密钥只在原生层，网页读不到。
// - 第一次打开（或菜单「重新设置…」）弹出设置向导 setup.html：粘贴密钥当场验证 → 自动建中转页和表 → 保存。
//   向导的 Notion 请求走另一个只放行设置用接口的通道（window.webkit.messageHandlers.setup）。
// - 存放位置：~/Library/Application Support/LiveBoard/
//     notion_token（连接密钥，600 权限）  config.json（表 ID 等，不是密钥）
// - 登录 Mac 时自动打开：用系统的「登录项」（SMAppService，macOS 13+），菜单里可以开关。
// - 界面语言：跟随系统 / 简体中文 / English（Lang.swift）。菜单「语言」或向导右上角切换，当场生效，不用重启；
//   网页通过 window.__LIVEBOARD_LANG 拿到语言。文字表在 Contents/Resources/<语言>.lproj/Localizable.strings。
import AppKit
import WebKit
import ObjectiveC
import ServiceManagement

let kNotionVersion = "2022-06-28"

/// 解除 macOS 13–15 WKWebView 的 60 帧上限（同 v1；接口不在就什么都不做）。
func unlockHighRefresh(_ prefs: WKPreferences) {
    let setSel = NSSelectorFromString("_setEnabled:forFeature:")
    guard prefs.responds(to: setSel), let setM = class_getInstanceMethod(WKPreferences.self, setSel) else { return }
    typealias ListFn = @convention(c) (AnyClass, Selector) -> Unmanaged<NSArray>?
    typealias SetFn = @convention(c) (AnyObject, Selector, ObjCBool, AnyObject) -> Void
    var features: [NSObject] = []
    for name in ["_features", "_experimentalFeatures"] {
        let sel = NSSelectorFromString(name)
        guard let m = class_getClassMethod(WKPreferences.self, sel) else { continue }
        let list = unsafeBitCast(method_getImplementation(m), to: ListFn.self)
        if let arr = list(WKPreferences.self, sel)?.takeUnretainedValue() as? [NSObject] { features += arr }
    }
    let setEnabled = unsafeBitCast(method_getImplementation(setM), to: SetFn.self)
    let keySel = NSSelectorFromString("key")
    for f in features where f.responds(to: keySel) && (f.value(forKey: "key") as? String) == "PreferPageRenderingUpdatesNear60FPSEnabled" {
        setEnabled(prefs, setSel, ObjCBool(false), f)
    }
}

/// 小窗尺寸：宽取可用区域 50%，按 21:9 算高；高超过可用高度 50% 时按高反算。
func popupSize(for screen: NSScreen?) -> NSSize {
    let vf = (screen ?? NSScreen.main)?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1470, height: 919)
    var w = vf.width * 0.5
    var h = w * 9 / 21
    if h > vf.height * 0.5 { h = vf.height * 0.5; w = h * 21 / 9 }
    let minW = min(640, vf.width * 0.9)
    if w < minW { w = minW; h = w * 9 / 21 }
    return NSSize(width: w.rounded(), height: h.rounded())
}

// MARK: - 设置和密钥：见 Store.swift

// MARK: - 打包在 App 里的看板网页
let kScheme = "liveboard"
let kStart = URL(string: "liveboard://local/index.html")!
let kSetup = URL(string: "liveboard://local/setup.html")!

final class LocalBoardScheme: NSObject, WKURLSchemeHandler {
    let root: URL? = Bundle.main.resourceURL?.appendingPathComponent("board", isDirectory: true).standardizedFileURL
    static let types: [String: String] = [
        "html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8", "json": "application/json", "glb": "model/gltf-binary", "gltf": "model/gltf+json",
        "woff2": "font/woff2", "woff": "font/woff", "ttf": "font/ttf", "png": "image/png", "jpg": "image/jpeg",
        "svg": "image/svg+xml", "webp": "image/webp", "wasm": "application/wasm", "bin": "application/octet-stream"]

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url else { return task.didFailWithError(URLError(.badURL)) }
        var path = url.path
        if path.isEmpty || path == "/" { path = "/index.html" }
        guard let root = root else { return reply(task, url, 404, "text/plain", Data()) }
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.path + "/"), let data = try? Data(contentsOf: file) else {
            return reply(task, url, 404, "text/plain", Data("not found".utf8))
        }
        reply(task, url, 200, Self.types[file.pathExtension.lowercased()] ?? "application/octet-stream", data)
    }
    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}

    private func reply(_ task: WKURLSchemeTask, _ url: URL, _ code: Int, _ type: String, _ data: Data) {
        let headers = ["Content-Type": type, "Content-Length": String(data.count), "Cache-Control": "no-cache", "Access-Control-Allow-Origin": "*"]
        let resp = HTTPURLResponse(url: url, statusCode: code, httpVersion: "HTTP/1.1", headerFields: headers)!
        task.didReceive(resp); task.didReceive(data); task.didFinish()
    }
}

// MARK: - 发 Notion 请求（密钥只在这里加上）
func sendNotion(_ method: String, _ path: String, _ body: String, token: String, reply: @escaping (Any?, String?) -> Void) {
    guard let url = URL(string: "https://api.notion.com" + path) else { return reply(["status": 400, "body": "{}"], nil) }
    var req = URLRequest(url: url)
    req.httpMethod = method
    req.timeoutInterval = 20
    req.cachePolicy = .reloadIgnoringLocalCacheData
    req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
    req.setValue(kNotionVersion, forHTTPHeaderField: "Notion-Version")
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    if !body.isEmpty && method != "GET" { req.httpBody = Data(body.utf8) }
    notionSession.dataTask(with: req) { data, resp, _ in
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        let text = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        DispatchQueue.main.async { reply(["status": code, "body": text], nil) }
    }.resume()
}
let notionSession: URLSession = {
    let c = URLSessionConfiguration.ephemeral
    c.timeoutIntervalForRequest = 20
    c.requestCachePolicy = .reloadIgnoringLocalCacheData
    return URLSession(configuration: c)
}()
// MARK: - 看板用的 Notion 通道（只放行两种）
final class NotionBridge: NSObject, WKScriptMessageHandlerWithReply {
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        guard let m = message.body as? [String: Any], let method = m["method"] as? String, let path = m["path"] as? String else {
            return replyHandler(["status": 400, "body": "{\"code\":\"bad_request\"}"], nil)
        }
        let body = (m["body"] as? String) ?? ""
        guard Policy.boardAllowed(method, path, body, db: Store.databaseID) else { return replyHandler(["status": 403, "body": "{\"code\":\"not_allowed\"}"], nil) }
        guard let token = Store.token() else { return replyHandler(["status": 0, "body": "{\"code\":\"no_token\"}"], nil) }
        sendNotion(method, path, body, token: token, reply: replyHandler)
    }
}

// MARK: - 设置向导用的通道
// op: state / token / notion / choose / open / copy / lang / finish。密钥先只放在内存里（pending），点「打开看板」时才写进文件。
final class SetupBridge: NSObject, WKScriptMessageHandlerWithReply {
    var pending: String?
    var scope = SetupScope()
    var onFinish: (() -> Void)?
    var onLanguage: (() -> Void)?

    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        guard let m = message.body as? [String: Any], let op = m["op"] as? String else { return replyHandler(["ok": false], nil) }
        switch op {
        case "state":
            replyHandler(["ok": true, "hasToken": Store.token() != nil, "configured": Store.isConfigured, "language": L10n.preference, "lang": L10n.web], nil)
        case "lang":
            // 向导右上角换语言：存下来，回传网页该用的语言；菜单、看板跟着换
            L10n.preference = (m["value"] as? String) ?? "system"
            replyHandler(["ok": true, "language": L10n.preference, "lang": L10n.web], nil)
            DispatchQueue.main.async { self.onLanguage?() }
        case "token":
            if (m["useSaved"] as? Bool) == true {
                pending = nil
                replyHandler(["ok": Store.token() != nil], nil)
            } else {
                let t = ((m["token"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                let ok = Policy.tokenLooksOK(t)
                if ok { pending = t }
                replyHandler(["ok": ok], nil)
            }
        case "notion":
            let method = (m["method"] as? String) ?? "", path = (m["path"] as? String) ?? "", body = (m["body"] as? String) ?? ""
            guard scope.allows(method, path, body) else { return replyHandler(["status": 403, "body": "{\"code\":\"not_allowed\"}"], nil) }
            guard let token = pending ?? Store.token() else { return replyHandler(["status": 0, "body": "{\"code\":\"no_token\"}"], nil) }
            sendNotion(method, path, body, token: token) { [weak self] r, e in
                if let o = r as? [String: Any] { self?.scope.record(method, path, status: (o["status"] as? Int) ?? 0, response: (o["body"] as? String) ?? "") }
                replyHandler(r, e)
            }
        case "choose":
            // 用户粘贴了已有表的链接：只放行这一张
            replyHandler(["ok": scope.choose((m["database_id"] as? String) ?? "")], nil)
        case "open":
            // 只打开 Notion 自己的网页
            if let s = m["url"] as? String, Policy.openAllowed(s), let u = URL(string: s) { NSWorkspace.shared.open(u) }
            replyHandler(["ok": true], nil)
        case "copy":
            // 只复制短文本（向导里只有那条命令）；60 秒后剪贴板若还是这段内容就清掉
            let t = (m["text"] as? String) ?? ""
            guard !t.isEmpty, t.count <= 500 else { return replyHandler(["ok": false], nil) }
            let pb = NSPasteboard.general
            pb.clearContents(); pb.setString(t, forType: .string)
            let stamp = pb.changeCount
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) { if pb.changeCount == stamp { pb.clearContents() } }
            replyHandler(["ok": true], nil)
        case "finish":
            guard scope.canFinish((m["database_id"] as? String) ?? "") else { return replyHandler(["ok": false, "error": L("err.notThisTable")], nil) }
            if let err = Store.commitSetup(pending: pending, databaseID: (m["database_id"] as? String) ?? "") { return replyHandler(["ok": false, "error": err], nil) }
            pending = nil
            replyHandler(["ok": true], nil)
            DispatchQueue.main.async { self.onFinish?() }
        default:
            replyHandler(["ok": false], nil)
        }
    }
}

/// 只在 App 自己的页面里打开链接；外部链接交给浏览器
final class LinkPolicy: NSObject, WKNavigationDelegate, WKUIDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let u = action.request.url else { return decisionHandler(.cancel) }
        if u.scheme == kScheme || u.scheme == "about" { return decisionHandler(.allow) }
        if u.scheme == "https" { NSWorkspace.shared.open(u) }
        decisionHandler(.cancel)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = action.request.url, u.scheme == "https" { NSWorkspace.shared.open(u) }
        return nil
    }
}

// MARK: - 设置窗口
final class SetupWindow: NSObject, NSWindowDelegate {
    let window: NSWindow
    let web: WKWebView
    let bridge = SetupBridge()
    let links = LinkPolicy()

    init(onFinish: @escaping () -> Void) {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .nonPersistent()
        cfg.setURLSchemeHandler(LocalBoardScheme(), forURLScheme: kScheme)
        cfg.userContentController.addScriptMessageHandler(bridge, contentWorld: .page, name: "setup")
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 680, height: 620), configuration: cfg)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 620), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        super.init()
        window.title = L("setup.title")
        window.isReleasedWhenClosed = false
        window.contentView = web
        window.delegate = self
        web.navigationDelegate = links
        web.uiDelegate = links
        bridge.onFinish = { [weak self] in self?.window.close(); onFinish() }
    }
    /// 页面加载前告诉向导用哪种语言
    func injectLang() {
        let ucc = web.configuration.userContentController
        ucc.removeAllUserScripts()
        ucc.addUserScript(WKUserScript(source: "window.__LIVEBOARD_LANG = \"\(L10n.web)\";", injectionTime: .atDocumentStart, forMainFrameOnly: true))
        window.title = L("setup.title")
    }
    func show() {
        bridge.pending = nil; bridge.scope = SetupScope()
        injectLang()
        web.load(URLRequest(url: kSetup, cachePolicy: .reloadIgnoringLocalCacheData))
        window.center()
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }
    func windowWillClose(_ notification: Notification) { bridge.pending = nil }   // 没点完成就关掉：内存里的密钥丢掉
}

// MARK: - 小窗内容
final class BoardViewController: NSViewController, WKNavigationDelegate, WKUIDelegate {
    let web: WKWebView
    let notice = NSTextField(labelWithString: "")
    let links = LinkPolicy()
    private(set) var lastLoadFailed = true

    override init(nibName: NSNib.Name?, bundle: Bundle?) {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()
        cfg.setURLSchemeHandler(LocalBoardScheme(), forURLScheme: kScheme)
        cfg.userContentController.addScriptMessageHandler(NotionBridge(), contentWorld: .page, name: "notion")
        unlockHighRefresh(cfg.preferences)
        web = WKWebView(frame: NSRect(origin: .zero, size: popupSize(for: NSScreen.main)), configuration: cfg)
        super.init(nibName: nil, bundle: nil)
        web.navigationDelegate = self
        web.uiDelegate = links
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let size = popupSize(for: NSScreen.main)
        let v = NSView(frame: NSRect(origin: .zero, size: size))
        web.autoresizingMask = [.width, .height]
        web.frame = v.bounds
        v.addSubview(web)
        notice.font = .systemFont(ofSize: 14, weight: .semibold)
        notice.alignment = .center
        notice.textColor = .labelColor
        notice.frame = NSRect(x: 16, y: size.height / 2 - 12, width: size.width - 32, height: 24)
        notice.autoresizingMask = [.width, .minYMargin, .maxYMargin]
        notice.isHidden = true
        v.addSubview(notice)
        view = v
        preferredContentSize = size
    }

    /// 页面加载前注入设置（表 ID、时区），relay.js 和看板都从这里读
    func injectConfig() {
        let ucc = web.configuration.userContentController
        ucc.removeAllUserScripts()
        let c = Store.config()
        // 多久读一次 Notion：打开时 / 收起时（毫秒）。config.json 里可以改，限制在合理范围内，免得把 Notion 读到限流
        func ms(_ k: String, _ def: Int, _ lo: Int, _ hi: Int) -> Int { min(max((c[k] as? Int) ?? def, lo), hi) }
        var cfg: [String: Any] = ["database_id": Store.databaseID, "active_ms": ms("active_ms", 3000, 1000, 60000), "idle_ms": ms("idle_ms", 30000, 5000, 600000)]
        let tz = (c["timezone"] as? String) ?? ""
        if !tz.isEmpty, TimeZone(identifier: tz) != nil { cfg["timezone"] = tz }
        guard let d = try? JSONSerialization.data(withJSONObject: cfg), let js = String(data: d, encoding: .utf8) else { return }
        var src = "window.__LIVEBOARD_CFG = \(js); window.__LIVEBOARD_LANG = \"\(L10n.web)\";"
        if cfg["timezone"] != nil { src += " window.__LIVEBOARD_TZ = window.__LIVEBOARD_CFG.timezone;" }
        ucc.addUserScript(WKUserScript(source: src, injectionTime: .atDocumentStart, forMainFrameOnly: true))
    }

    func load() {
        guard Store.isConfigured else {
            web.isHidden = true
            notice.stringValue = L("notice.notSetUp")
            notice.isHidden = false
            lastLoadFailed = true
            return
        }
        notice.isHidden = true
        web.isHidden = false
        injectConfig()
        web.load(URLRequest(url: kStart, cachePolicy: .reloadIgnoringLocalCacheData))
    }

    func setActive(_ on: Bool) {
        web.evaluateJavaScript("window.__relay && window.__relay.setActive(\(on ? "true" : "false"))", completionHandler: nil)
    }

    func showError(_ text: String) {
        lastLoadFailed = true
        web.isHidden = true
        notice.stringValue = text
        notice.isHidden = false
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        links.webView(webView, decidePolicyFor: action, decisionHandler: decisionHandler)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { lastLoadFailed = false }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError(L("notice.loadFailed")) }
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError(L("notice.loadFailed")) }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { load() }
}

// MARK: - 登录时自动打开（系统「登录项」）
enum LoginItem {
    static var enabled: Bool { SMAppService.mainApp.status == .enabled }
    static var needsApproval: Bool { SMAppService.mainApp.status == .requiresApproval }
    @discardableResult static func set(_ on: Bool) -> Bool {
        do { if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }; return true } catch { return false }
    }
}

// MARK: - 菜单栏
final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate, NSMenuDelegate {
    var item: NSStatusItem!
    let popover = NSPopover()
    let board = BoardViewController(nibName: nil, bundle: nil)
    let menu = NSMenu()
    var loginItem: NSMenuItem!
    var langItems: [NSMenuItem] = []
    lazy var setup: SetupWindow = {
        let w = SetupWindow { [weak self] in
            guard let self = self else { return }
            self.board.load()
            self.showPopover()
        }
        w.bridge.onLanguage = { [weak self] in self?.languageChanged(fromSetup: true) }
        return w
    }()

    func applicationDidFinishLaunching(_ n: Notification) {
        // 卸载脚本用：取消登录时自动打开后直接退出
        if CommandLine.arguments.contains("--unregister-login") { LoginItem.set(false); NSApp.terminate(nil); return }
        // 已经开着一个就不再开第二个
        if let bid = Bundle.main.bundleIdentifier,
           NSRunningApplication.runningApplications(withBundleIdentifier: bid).contains(where: { $0 != NSRunningApplication.current }) {
            NSApp.terminate(nil); return
        }
        installEditMenu()
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let b = item.button {
            b.image = Self.icon()
            b.toolTip = L("app.name")
            b.target = self
            b.action = #selector(clicked(_:))
            b.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        popover.behavior = .transient
        popover.animates = true
        popover.delegate = self
        popover.contentViewController = board
        popover.contentSize = popupSize(for: NSScreen.main)

        buildMenu()
        menu.delegate = self

        // 第一次打开：默认设成登录时自动打开（之后以菜单里的开关为准）
        let ud = UserDefaults.standard
        if !ud.bool(forKey: "loginItemAsked") {
            ud.set(true, forKey: "loginItemAsked")
            LoginItem.set(true)
        }

        _ = board.view
        board.load()
        if !Store.isConfigured { DispatchQueue.main.async { self.setup.show() } }
        let args = CommandLine.arguments
        if let a = args.first(where: { $0.hasPrefix("--open-popover") }) {
            let delay = Double(a.split(separator: "=").dropFirst().first ?? "") ?? 1.5
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.showPopover() }
        }
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self = self else { return }
            if self.board.lastLoadFailed { self.board.load() } else if self.popover.isShown { self.board.setActive(true) }
        }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self = self, self.popover.isShown, let b = self.item.button else { return }
            self.fitPopover(to: b.window?.screen)
        }
    }

    /// 右键菜单。换语言时整个重建
    func buildMenu() {
        menu.removeAllItems()
        menu.addItem(withTitle: L("menu.refresh"), action: #selector(reload), keyEquivalent: "r")
        menu.addItem(withTitle: L("menu.setup"), action: #selector(openSetup), keyEquivalent: ",")
        loginItem = menu.addItem(withTitle: L("menu.login"), action: #selector(toggleLogin), keyEquivalent: "")
        let langItem = menu.addItem(withTitle: L("menu.language"), action: nil, keyEquivalent: "")
        let sub = NSMenu()
        langItems = zip(L10n.choices, [L("lang.system"), "简体中文", "English"]).map { code, title in
            let it = sub.addItem(withTitle: title, action: #selector(chooseLanguage(_:)), keyEquivalent: "")
            it.representedObject = code; it.target = self
            return it
        }
        langItem.submenu = sub
        menu.addItem(.separator())
        menu.addItem(withTitle: L("menu.about"), action: #selector(about), keyEquivalent: "")
        menu.addItem(withTitle: L("menu.quit"), action: #selector(quit), keyEquivalent: "q")
        menu.items.forEach { if $0.action != nil { $0.target = self } }
    }

    @objc func chooseLanguage(_ sender: NSMenuItem) {
        guard let code = sender.representedObject as? String, code != L10n.preference else { return }
        L10n.preference = code
        languageChanged(fromSetup: false)
    }

    /// 换了语言：菜单、提示、设置窗口和看板都当场换，不用重启
    func languageChanged(fromSetup: Bool) {
        buildMenu()
        installEditMenu()
        item.button?.toolTip = L("app.name")
        board.load()
        setup.injectLang()
        if !fromSetup, setup.window.isVisible {   // 向导开着：就地换文字，已填的内容不丢
            setup.web.evaluateJavaScript("window.__lbSetLang && window.__lbSetLang(\"\(L10n.web)\")", completionHandler: nil)
        }
    }

    @objc func about() {
        let v = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? ""
        let credits = NSAttributedString(string: L("about.credits", v), attributes: [.font: NSFont.systemFont(ofSize: 11), .foregroundColor: NSColor.labelColor])
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [.applicationName: L("app.name"), .credits: credits, .version: ""])
    }

    /// 菜单栏小程序没有菜单栏菜单，⌘C / ⌘V / ⌘A 要靠这个「编辑」菜单才能在输入框里用
    func installEditMenu() {
        let main = NSMenu(), appItem = NSMenuItem(), editItem = NSMenuItem()
        main.addItem(appItem); main.addItem(editItem)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: L("menu.quit"), action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); appItem.submenu = appMenu
        let edit = NSMenu(title: L("edit.title"))
        edit.addItem(withTitle: L("edit.undo"), action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: L("edit.redo"), action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: L("edit.cut"), action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: L("edit.copy"), action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: L("edit.paste"), action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: L("edit.selectAll"), action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        NSApp.mainMenu = main
    }

    func menuWillOpen(_ menu: NSMenu) {
        loginItem.state = LoginItem.enabled ? .on : .off
        langItems.forEach { $0.state = ($0.representedObject as? String) == L10n.preference ? .on : .off }
    }

    func fitPopover(to screen: NSScreen?) {
        let size = popupSize(for: screen)
        board.preferredContentSize = size
        popover.contentSize = size
    }

    static func icon() -> NSImage {
        let img = NSImage(systemSymbolName: "cube", accessibilityDescription: L("app.name"))
            ?? NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
                let p = NSBezierPath(); p.lineWidth = 1.4
                p.move(to: NSPoint(x: 9, y: 16)); p.line(to: NSPoint(x: 16, y: 12.5)); p.line(to: NSPoint(x: 16, y: 5.5))
                p.line(to: NSPoint(x: 9, y: 2)); p.line(to: NSPoint(x: 2, y: 5.5)); p.line(to: NSPoint(x: 2, y: 12.5)); p.close()
                p.move(to: NSPoint(x: 2, y: 12.5)); p.line(to: NSPoint(x: 9, y: 9)); p.line(to: NSPoint(x: 16, y: 12.5))
                p.move(to: NSPoint(x: 9, y: 9)); p.line(to: NSPoint(x: 9, y: 2))
                NSColor.black.setStroke(); p.stroke(); return true
            }
        img.isTemplate = true
        return img
    }

    @objc func clicked(_ sender: NSStatusBarButton) {
        let ev = NSApp.currentEvent
        if ev?.type == .rightMouseUp || ev?.modifierFlags.contains(.control) == true {
            popover.performClose(nil)
            item.menu = menu
            item.button?.performClick(nil)
            item.menu = nil
            return
        }
        if popover.isShown { popover.performClose(sender); return }
        if !Store.isConfigured { setup.show(); return }
        showPopover()
    }

    func showPopover() {
        guard let b = item.button, !popover.isShown else { return }
        if board.lastLoadFailed { board.load() }
        fitPopover(to: b.window?.screen)
        popover.show(relativeTo: b.bounds, of: b, preferredEdge: .minY)
        board.setActive(true)   // 一弹出就马上问一次 Notion，之后 3 秒一次
        NSApp.activate(ignoringOtherApps: true)
        popover.contentViewController?.view.window?.makeKey()
    }
    func popoverDidClose(_ notification: Notification) { board.setActive(false) }   // 收起后 30 秒一次

    @objc func reload() { board.load() }
    @objc func quit() { NSApp.terminate(nil) }
    @objc func openSetup() { popover.performClose(nil); setup.show() }
    @objc func toggleLogin() {
        let want = !LoginItem.enabled
        LoginItem.set(want)
        if want && !LoginItem.enabled {
            let a = NSAlert()
            a.messageText = L("login.title")
            a.informativeText = L("login.body")
            a.addButton(withTitle: L("login.open")); a.addButton(withTitle: L("login.cancel"))
            NSApp.activate(ignoringOtherApps: true)
            if a.runModal() == .alertFirstButtonReturn { SMAppService.openSystemSettingsLoginItems() }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
