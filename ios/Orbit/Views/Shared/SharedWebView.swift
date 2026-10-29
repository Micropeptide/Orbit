import SwiftUI
import UIKit
import WebKit

/// One shared project, shown the way the Mac itself shows it: the page at
/// `/shared/<id>/`, served by Orbit on the Mac. The Mac adds the owner's
/// sign-in to the page's calls, so all this has to do is prove the *phone* is
/// paired — which it does with the pairing token as a cookie, because a web
/// view cannot put a header on the page's own requests.
///
/// What a web view does not do by itself, this does: file downloads (to the
/// share sheet), page dialogs, links that leave the project, a page that
/// cannot be reached (retry, then say so), and pull to refresh.
@MainActor
final class SharedWebController: NSObject, ObservableObject {
    enum Phase: Equatable {
        case loading
        case ready
        case reconnecting(Int)
        case failed(String)
    }

    @Published private(set) var phase: Phase = .loading
    @Published private(set) var progress = 0.0
    @Published private(set) var pageTitle = ""
    /// A file the page produced, ready for the share sheet.
    @Published var finishedDownload: URL?
    @Published private(set) var downloadingName: String?
    @Published var notice: String?

    /// One store for the whole run of the app, so the page's own small memory
    /// (what you were typing, the outbox) survives closing and reopening a
    /// project — and none of it, nor the cookie, is ever written to disk.
    private static let store = WKWebsiteDataStore.nonPersistent()

    let webView: WKWebView
    private let base: URL
    private let token: String
    private let accessHeaders: [String: String]
    private let pairing: Pairing
    private let startURL: URL
    private var observers: [NSKeyValueObservation] = []
    private var attempts = 0
    private var retryTask: Task<Void, Never>?
    private var activeDownloads: [ObjectIdentifier: URL] = [:]
    private let refresh = UIRefreshControl()
    #if DEBUG
    private var debugJSRan = false
    #endif

    init?(pairing: Pairing, project: String, chat: String?) {
        guard let base = pairing.base, base.host != nil else { return nil }
        self.base = base
        self.token = pairing.token
        self.accessHeaders = pairing.accessHeaders(for: pairing.base)
        self.pairing = pairing

        // The "t=orbit" placeholder is what the Mac's own sidebar uses: the page
        // wants a token to hold, Orbit swaps in the real sign-in on the Mac.
        var frag = "p=\(project)&t=orbit&n=Me"
        if let chat, !chat.isEmpty,
           let c = chat.addingPercentEncoding(withAllowedCharacters: .alphanumerics) { frag += "&c=\(c)" }
        guard let url = URL(string: "\(base.absoluteString)/shared/\(project)/#\(frag)") else { return nil }
        self.startURL = url

        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = Self.store
        cfg.allowsInlineMediaPlayback = true
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true
        // Safari zooms the page in when a field with small text gets focus, and leaves it zoomed
        // (the Send button then sits off the right edge). The page is built for a phone's width.
        cfg.userContentController.addUserScript(WKUserScript(source: """
        (function(){var m=document.querySelector('meta[name=viewport]');
        if(!m){m=document.createElement('meta');m.name='viewport';document.head.appendChild(m);}
        m.content=(m.content||'width=device-width,initial-scale=1').replace(/,?\\s*(maximum-scale|user-scalable)\\s*=\\s*[^,]*/g,'')+',maximum-scale=1,user-scalable=no';})();
        """, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: cfg)
        super.init()

        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.scrollView.keyboardDismissMode = .interactive
        webView.underPageBackgroundColor = .systemBackground
        webView.backgroundColor = .systemBackground
        #if DEBUG
        webView.isInspectable = true
        // development only: the page's console and errors into a file the simulator host can read
        if ProcessInfo.processInfo.environment["ORBIT_WEBLOG"] != nil {
            cfg.userContentController.add(DebugLog.shared, name: "dbg")
            cfg.userContentController.addUserScript(WKUserScript(source: """
            (function(){const send=(k,a)=>{try{webkit.messageHandlers.dbg.postMessage(k+': '+a.map(x=>{try{return typeof x==='string'?x:(x&&x.message)||JSON.stringify(x)}catch(e){return String(x)}}).join(' '))}catch(e){}};
            ['log','warn','error'].forEach(k=>{const o=console[k];console[k]=function(){send(k,[].slice.call(arguments));o.apply(console,arguments)}});
            window.addEventListener('error',e=>send('onerror',[e.message,e.filename+':'+e.lineno]));
            window.addEventListener('unhandledrejection',e=>send('rejection',[e.reason]));
            const f=window.fetch;window.fetch=function(u,o){return f.apply(this,arguments).then(r=>{send('fetch',[String(u).slice(0,120),r.status]);return r},e=>{send('fetchfail',[String(u).slice(0,120),e&&e.message]);throw e})};})();
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        #endif

        refresh.addTarget(self, action: #selector(pulled), for: .valueChanged)
        webView.scrollView.refreshControl = refresh

        observers = [
            webView.observe(\.estimatedProgress, options: [.new]) { [weak self] wv, _ in
                let p = wv.estimatedProgress
                Task { @MainActor in self?.progress = p }
            },
            webView.observe(\.title, options: [.new]) { [weak self] wv, _ in
                let t = wv.title ?? ""
                Task { @MainActor in self?.pageTitle = t }
            },
        ]
    }

    // ------------------------------------------------------------ loading

    /// A first load, or a start from scratch.
    func load() {
        retryTask?.cancel()
        phase = attempts == 0 ? .loading : phase
        Task {
            await installCookie()
            var first = URLRequest(url: startURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25)
            // Cloudflare Access trades its service token for a cookie on this first request; the page's own calls ride on that
            for (k, v) in accessHeaders { first.setValue(v, forHTTPHeaderField: k) }
            webView.load(first)
        }
    }

    /// Reload what is showing; if nothing ever loaded, start again.
    func reload() {
        if case .ready = phase, webView.url != nil {
            webView.reload()
        } else {
            attempts = 0
            load()
        }
    }

    /// The page cannot hold the Orbit token (HttpOnly, and never on disk).
    private func installCookie() async {
        guard let host = base.host else { return }
        var props: [HTTPCookiePropertyKey: Any] = [
            .name: "orbit_token", .value: token, .path: "/", .domain: host,
            .originURL: base, HTTPCookiePropertyKey("HttpOnly"): "TRUE",
        ]
        if base.scheme == "https" { props[.secure] = "TRUE" }
        if let cookie = HTTPCookie(properties: props) {
            await Self.store.httpCookieStore.setCookie(cookie)
        }
        // a Mac on the internet: the page's own calls must pass Cloudflare Access too (see AccessCookie)
        if let access = await AccessCookie.fetch(pairing: pairing) {
            await Self.store.httpCookieStore.setCookie(access)
        }
    }

    /// Leave nothing behind: the cookie goes when the project is closed.
    func tearDown() async {
        retryTask?.cancel()
        webView.stopLoading()
        let jar = Self.store.httpCookieStore
        for c in await jar.allCookies() where c.name == "orbit_token" || c.name == "CF_Authorization" { await jar.deleteCookie(c) }
        // downloaded files were handed to the share sheet; do not keep copies in the app
        try? FileManager.default.removeItem(
            at: FileManager.default.temporaryDirectory.appendingPathComponent("orbit-shared-downloads", isDirectory: true))
    }

    /// Coming back to the foreground: a dead connection should not need a tap.
    func resumed() {
        switch phase {
        case .failed: attempts = 0; load()
        case .ready:
            // the page's live stream stopped when the phone slept; tell it the network is back
            webView.evaluateJavaScript("window.dispatchEvent(new Event('online'));", completionHandler: nil)
        default: break
        }
    }

    @objc private func pulled() {
        Haptics.tap()
        reload()
    }

    private func endRefreshing() {
        if refresh.isRefreshing { refresh.endRefreshing() }
    }

    private func fail(_ message: String, retry: Bool) {
        endRefreshing()
        guard retry, attempts < 3 else { phase = .failed(message); return }
        attempts += 1
        phase = .reconnecting(attempts)
        let delay = UInt64(pow(2.0, Double(attempts))) * 1_000_000_000      // 2 s, 4 s, 8 s
        retryTask?.cancel()
        retryTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled else { return }
            self?.load()
        }
    }

    private func sentence(for code: Int) -> String {
        switch code {
        case 401: return "This Mac no longer accepts the pairing. Scan its QR code again in Settings."
        case 403: return "This phone is set to use chats only, so it can't open shared projects. Allow it more on the Mac, in Settings, Phone."
        case 404: return "That shared project isn't there any more, or shared projects are switched off on the Mac."
        case 502, 503: return "Shared projects aren't running on your Mac right now."
        default: return "Your Mac answered \(code)."
        }
    }

    private func sameOrigin(_ url: URL) -> Bool {
        url.scheme == base.scheme && url.host == base.host && (url.port ?? defaultPort(url)) == (base.port ?? defaultPort(base))
    }
    private func defaultPort(_ u: URL) -> Int { u.scheme == "https" ? 443 : 80 }

    private func suggestedURL(for name: String) -> URL {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-shared-downloads", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var clean = name.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "..", with: "_")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if clean.isEmpty { clean = "download" }
        return dir.appendingPathComponent(clean)
    }
}

// ---------------------------------------------------------------- navigation

extension SharedWebController: WKNavigationDelegate {
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        // <a download>, including a blob the page made itself
        if action.shouldPerformDownload { decisionHandler(.download); return }
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        switch url.scheme {
        case "about", "blob", "data": decisionHandler(.allow)
        default:
            if sameOrigin(url) {
                // only the project's own pages; the rest of the Mac's address is not for this view
                if url.path.hasPrefix("/shared/") { decisionHandler(.allow) }
                else { notice = "That link isn't part of the project."; decisionHandler(.cancel) }
            } else {
                // a link out of the project goes to the phone's browser, on a tap only
                if action.navigationType == .linkActivated, ["http", "https", "mailto"].contains(url.scheme ?? "") {
                    UIApplication.shared.open(url)
                }
                decisionHandler(.cancel)
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if response.isForMainFrame, let http = response.response as? HTTPURLResponse {
            if http.statusCode >= 400 {
                // the Mac's own refusals are final; a gateway that did not answer is worth retrying
                fail(sentence(for: http.statusCode), retry: http.statusCode == 502 || http.statusCode == 503)
                decisionHandler(.cancel)
                return
            }
            if (http.value(forHTTPHeaderField: "Content-Disposition") ?? "").lowercased().hasPrefix("attachment") {
                decisionHandler(.download); return
            }
        }
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        if case .ready = phase { return }       // a reload of a page that works: keep showing it
        if case .reconnecting = phase { return }
        phase = .loading
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        attempts = 0
        phase = .ready
        endRefreshing()
        #if DEBUG
        // development only: ORBIT_WEBJS="delaySeconds|javascript" runs a script in the page (to drive it without a finger)
        if let spec = ProcessInfo.processInfo.environment["ORBIT_WEBJS"], !debugJSRan,
           let bar = spec.firstIndex(of: "|"), let delay = Double(spec[..<bar]) {
            debugJSRan = true
            let js = String(spec[spec.index(after: bar)...])
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { webView.evaluateJavaScript(js) }
        }
        #endif
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        navigationFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        navigationFailed(error)
    }

    private func navigationFailed(_ error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorCancelled { return }
        if ns.domain == "WebKitErrorDomain", ns.code == 102 || ns.code == 204 { return }   // became a download
        let msg: String
        switch ns.code {
        case NSURLErrorNotConnectedToInternet, NSURLErrorCannotConnectToHost, NSURLErrorTimedOut,
             NSURLErrorNetworkConnectionLost, NSURLErrorCannotFindHost:
            msg = "Can't reach your Mac. It may be asleep, or this phone may be off the tailnet."
        default:
            msg = ns.localizedDescription
        }
        fail(msg, retry: true)
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        // iOS reclaims a web view's process when memory is short; bring the page back
        attempts = 0
        load()
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }
}

// ---------------------------------------------------------------- downloads

extension SharedWebController: WKDownloadDelegate {
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let dest = suggestedURL(for: suggestedFilename)
        activeDownloads[ObjectIdentifier(download)] = dest
        downloadingName = dest.lastPathComponent
        completionHandler(dest)
    }

    func downloadDidFinish(_ download: WKDownload) {
        let key = ObjectIdentifier(download)
        downloadingName = nil
        if let url = activeDownloads.removeValue(forKey: key) {
            Haptics.success()
            finishedDownload = url         // the share sheet: Save to Files, AirDrop, open in…
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let url = activeDownloads.removeValue(forKey: ObjectIdentifier(download)) {
            try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
        }
        downloadingName = nil
        notice = "That file didn't download. Try again."
    }
}

// ---------------------------------------------------------------- the page's own dialogs

extension SharedWebController: WKUIDelegate {
    private func present(_ alert: UIAlertController) {
        var top = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.keyWindow }.first?.rootViewController
        while let next = top?.presentedViewController { top = next }
        top?.present(alert, animated: true)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        present(a)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        present(a)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText }
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(a.textFields?.first?.text) })
        present(a)
    }

    /// target="_blank" and window.open: stay in the project if it is the project, else the phone's browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = action.request.url else { return nil }
        if sameOrigin(url), url.path.hasPrefix("/shared/") {
            webView.load(action.request)
        } else if ["http", "https", "mailto"].contains(url.scheme ?? "") {
            UIApplication.shared.open(url)
        }
        return nil
    }
}

// ---------------------------------------------------------------- SwiftUI

private struct WebHost: UIViewRepresentable {
    let webView: WKWebView
    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}

/// The full-screen project: a bar with Back and Reload, the page, and the states
/// a page on another machine needs (loading, reconnecting, unreachable).
struct SharedWebScreen: View {
    let target: SharedTarget
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var web: SharedWebController

    init?(target: SharedTarget, pairing: Pairing) {
        guard let c = SharedWebController(pairing: pairing, project: target.project.id, chat: target.chat)
        else { return nil }
        self.target = target
        _web = StateObject(wrappedValue: c)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemBackground)
                WebHost(webView: web.webView)
                    .opacity(web.phase == .ready || isReconnecting ? 1 : 0.001)

                switch web.phase {
                case .loading:
                    VStack(spacing: 10) {
                        ProgressView()
                        Text("Opening \(target.project.name)").font(.footnote).foregroundStyle(.secondary)
                    }
                case .failed(let message):
                    ContentUnavailableView {
                        Label("Can't open the project", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text(message)
                    } actions: {
                        Button("Try again") { Haptics.tap(); web.reload() }
                            .buttonStyle(.borderedProminent)
                    }
                default: EmptyView()
                }
            }
            .overlay(alignment: .top) {
                VStack(spacing: 0) {
                    if web.progress > 0, web.progress < 1 {
                        ProgressView(value: web.progress).progressViewStyle(.linear)
                    }
                    if case .reconnecting(let n) = web.phase {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("Reconnecting to your Mac… (\(n) of 3)").font(.footnote)
                        }
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .frame(maxWidth: .infinity)
                        .background(.thinMaterial)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            .overlay(alignment: .bottom) { toast }
            .navigationTitle(target.project.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { dismiss() } label: {
                        Label("Back", systemImage: "chevron.left")
                    }
                    .accessibilityLabel("Back to Shared")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Haptics.tap(); web.reload() } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Reload")
                }
            }
            .sheet(item: $web.finishedDownload) { url in
                ActivityView(items: [url]).ignoresSafeArea()
            }
        }
        .task { web.load() }
        .onChange(of: scenePhase) { _, new in if new == .active { web.resumed() } }
        .onDisappear {
            let id = target.project.id
            let server = state.server
            Task {
                await web.tearDown()
                await state.shared.markSeen(id, using: server)
                await state.shared.refresh(using: server, quiet: true)
            }
        }
    }

    private var isReconnecting: Bool {
        if case .reconnecting = web.phase { return true }
        return false
    }

    @ViewBuilder private var toast: some View {
        if let name = web.downloadingName {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text("Downloading \(name)").font(.footnote).lineLimit(1)
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(.regularMaterial, in: Capsule())
            .padding(.bottom, 16)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if let note = web.notice {
            Text(note).font(.footnote)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(.regularMaterial, in: Capsule())
                .padding(.bottom, 16)
                .task {
                    try? await Task.sleep(nanoseconds: 3_000_000_000)
                    web.notice = nil
                }
        }
    }
}

#if DEBUG
final class DebugLog: NSObject, WKScriptMessageHandler {
    static let shared = DebugLog()
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        let line = "\(Date()) \(m.body)\n"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("orbit-webdbg.log")
        if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
        else { try? line.write(to: url, atomically: false, encoding: .utf8) }
    }
}
#endif
