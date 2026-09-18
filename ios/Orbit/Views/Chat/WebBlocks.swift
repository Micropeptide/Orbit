import SwiftUI
import WebKit

/// Maths and Mermaid diagrams, drawn the way the Mac draws them: with the
/// KaTeX and Mermaid copies the Mac already serves under `/vendor/`, so nothing
/// comes from the internet. Those files need the pairing token, which a web
/// view cannot send, so a small URL scheme fetches them through the paired
/// client and keeps them on the phone.

// ------------------------------------------------------------------ the Mac's libraries

@MainActor
final class VendorFiles {
    static let shared = VendorFiles()
    static let scheme = "orbit-vendor"
    /// Relative links inside KaTeX's stylesheet (its fonts) resolve against this.
    static let base = URL(string: "\(scheme)://mac/")!

    private var memory: [String: Data] = [:]
    private let dir: URL = {
        let d = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("orbit-vendor", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }()

    /// A file under /vendor/, from memory, then disk, then the Mac.
    func data(_ path: String) async throws -> Data {
        guard path.hasPrefix("/vendor/"), !path.contains("..") else { throw URLError(.badURL) }
        if let d = memory[path] { return d }
        let file = dir.appendingPathComponent(path.replacingOccurrences(of: "/", with: "_"))
        if let d = try? Data(contentsOf: file) { memory[path] = d; return d }
        guard let server = FileLinks.shared.server else { throw URLError(.notConnectedToInternet) }
        let d = try await server.fetchRaw(path)
        memory[path] = d
        try? d.write(to: file, options: .atomic)
        return d
    }

    static func mime(_ path: String) -> String {
        if path.hasSuffix(".css") { return "text/css" }
        if path.hasSuffix(".js") { return "application/javascript" }
        if path.hasSuffix(".woff2") { return "font/woff2" }
        if path.hasSuffix(".woff") { return "font/woff" }
        if path.hasSuffix(".ttf") { return "font/ttf" }
        return "application/octet-stream"
    }
}

final class VendorSchemeHandler: NSObject, WKURLSchemeHandler {
    private var stopped = Set<ObjectIdentifier>()

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        let id = ObjectIdentifier(task)
        guard let url = task.request.url else { return }
        Task { @MainActor in
            do {
                let data = try await VendorFiles.shared.data(url.path)
                guard !self.stopped.contains(id) else { return }
                task.didReceive(URLResponse(url: url, mimeType: VendorFiles.mime(url.path),
                                            expectedContentLength: data.count, textEncodingName: nil))
                task.didReceive(data)
                task.didFinish()
            } catch {
                guard !self.stopped.contains(id) else { return }
                task.didFailWithError(error)
            }
        }
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {
        stopped.insert(ObjectIdentifier(task))
    }
}

// ------------------------------------------------------------------ one drawn block

/// Holds the web view of a block so a menu can take a picture of it.
@MainActor
final class WebBlockHandle: ObservableObject {
    weak var webView: WKWebView?
    @Published var svg: String?
    @Published var failed: String?

    func snapshot() async -> UIImage? {
        guard let webView else { return nil }
        return try? await webView.takeSnapshot(configuration: nil)
    }
}

/// A small page that reports its own height, sized to fit in the transcript.
struct WebBlock: UIViewRepresentable {
    let html: String
    @Binding var height: CGFloat
    var handle: WebBlockHandle?
    var scrollable = false

    /// Heights already measured, so a row scrolled back into view keeps its size.
    @MainActor static var heights: [Int: CGFloat] = [:]

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.setURLSchemeHandler(VendorSchemeHandler(), forURLScheme: VendorFiles.scheme)
        cfg.userContentController.add(WeakScriptHandler(context.coordinator), name: "orbit")
        cfg.websiteDataStore = .nonPersistent()
        let v = WKWebView(frame: .zero, configuration: cfg)
        v.isOpaque = false
        v.backgroundColor = .clear
        v.scrollView.backgroundColor = .clear
        v.scrollView.isScrollEnabled = scrollable
        v.scrollView.bounces = scrollable
        handle?.webView = v
        context.coordinator.loaded = html
        v.loadHTMLString(html, baseURL: VendorFiles.base)
        return v
    }

    func updateUIView(_ v: WKWebView, context: Context) {
        context.coordinator.parent = self
        guard context.coordinator.loaded != html else { return }
        context.coordinator.loaded = html
        v.loadHTMLString(html, baseURL: VendorFiles.base)
    }

    static func dismantleUIView(_ v: WKWebView, coordinator: Coordinator) {
        v.configuration.userContentController.removeScriptMessageHandler(forName: "orbit")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler {
        var parent: WebBlock
        var loaded = ""
        init(_ p: WebBlock) { parent = p }

        func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let d = message.body as? [String: Any] else { return }
            let parent = self.parent
            Task { @MainActor in
                if let h = (d["h"] as? Double) ?? (d["h"] as? Int).map(Double.init), h > 0 {
                    let fit = CGFloat(min(h, 4000))
                    WebBlock.heights[parent.html.hashValue] = fit
                    if abs(parent.height - fit) > 1 { parent.height = fit }
                }
                if let svg = d["svg"] as? String { parent.handle?.svg = svg }
                if let f = d["fail"] as? String { parent.handle?.failed = f }
            }
        }
    }

    /// WKUserContentController keeps its handlers alive; this breaks the cycle.
    final class WeakScriptHandler: NSObject, WKScriptMessageHandler {
        weak var target: WKScriptMessageHandler?
        init(_ t: WKScriptMessageHandler) { target = t }
        func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
            target?.userContentController(c, didReceive: m)
        }
    }

    // ---- pages

    /// A JavaScript string literal, safe inside a <script>.
    static func jsString(_ s: String) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: [s])) ?? Data("[\"\"]".utf8)
        let arr = String(decoding: data, as: UTF8.self)
        return String(arr.dropFirst().dropLast()).replacingOccurrences(of: "</", with: "<\\/")
    }

    private static func page(dark: Bool, head: String, script: String) -> String {
        """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
        \(head)
        <style>html,body{margin:0;padding:0;background:transparent;color:\(dark ? "#f2f2f7" : "#1c1c1e");
        font:-apple-system-body;-webkit-text-size-adjust:none}#o{overflow-x:auto;overflow-y:hidden;padding:2px 0}
        .katex-display{margin:0}</style></head><body><div id="o"></div>
        <script>function post(x){window.webkit.messageHandlers.orbit.postMessage(x)}
        function size(){post({h:document.getElementById('o').scrollHeight+4})}</script>
        \(script)</body></html>
        """
    }

    static func math(_ tex: String, dark: Bool) -> String {
        page(dark: dark,
             head: #"<link rel="stylesheet" href="vendor/katex/dist/katex.min.css">"#,
             script: """
             <script src="vendor/katex/dist/katex.min.js"></script>
             <script>try{katex.render(\(jsString(tex)),document.getElementById('o'),{displayMode:true,throwOnError:false});
             size();document.fonts.ready.then(size);setTimeout(size,300)}catch(e){post({fail:String(e&&e.message||e)})}</script>
             """)
    }

    static func mermaid(_ src: String, dark: Bool) -> String {
        page(dark: dark, head: "", script: """
             <script src="vendor/mermaid/dist/mermaid.min.js"></script>
             <script>(async()=>{try{mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'\(dark ? "dark" : "default")'});
             const r=await mermaid.render('mm'+Date.now(),\(jsString(src)));const o=document.getElementById('o');o.innerHTML=r.svg;
             const s=o.querySelector('svg');if(s){s.style.maxWidth='100%';s.style.height='auto'}
             post({svg:r.svg});size();setTimeout(size,200)}catch(e){post({fail:String(e&&e.message||e)})}})()</script>
             """)
    }
}

// ------------------------------------------------------------------ maths

/// Display maths, typeset. Falls back to its source when the Mac's KaTeX cannot be had.
struct MathBlock: View {
    let tex: String
    @Environment(\.colorScheme) private var scheme
    @StateObject private var handle = WebBlockHandle()
    @State private var height: CGFloat = 0

    var body: some View {
        let html = WebBlock.math(tex, dark: scheme == .dark)
        Group {
            if handle.failed != nil {
                CodeBlock(language: "math", code: tex)
            } else {
                WebBlock(html: html, height: $height, handle: handle)
                    .frame(height: max(height, 28))
                    .onAppear { if height == 0, let h = WebBlock.heights[html.hashValue] { height = h } }
                    .contentShape(.rect)
                    .contextMenu { Self.copyItems(tex) }
            }
        }
    }

    @ViewBuilder
    static func copyItems(_ tex: String) -> some View {
        Button {
            UIPasteboard.general.string = "$$" + tex + "$$"
            Haptics.success()
        } label: { Label("Copy LaTeX", systemImage: "function") }
        Button {
            UIPasteboard.general.string = tex
            Haptics.success()
        } label: { Label("Copy LaTeX (no delimiters)", systemImage: "function") }
    }
}

// ------------------------------------------------------------------ diagrams

/// A Mermaid diagram, drawn; its source, SVG and a larger view are a tap away.
struct MermaidBlock: View {
    let source: String
    @Environment(\.colorScheme) private var scheme
    @StateObject private var handle = WebBlockHandle()
    @State private var height: CGFloat = 0
    @State private var enlarged = false
    @State private var share: [Any]?

    var body: some View {
        let html = WebBlock.mermaid(source, dark: scheme == .dark)
        if let why = handle.failed {
            VStack(alignment: .leading, spacing: 4) {
                Text("diagram could not be drawn: " + String(why.prefix(160)))
                    .font(.caption2).foregroundStyle(.orange)
                CodeBlock(language: "mermaid", code: source)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text("diagram").font(.caption2.smallCaps()).foregroundStyle(.secondary)
                    Spacer()
                    Menu {
                        menuItems
                    } label: {
                        Image(systemName: "ellipsis.circle").font(.caption)
                    }
                    .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 11).padding(.vertical, 6)
                WebBlock(html: html, height: $height, handle: handle)
                    .frame(height: max(height, 60))
                    .onAppear { if height == 0, let h = WebBlock.heights[html.hashValue] { height = h } }
                    .padding(.horizontal, 8).padding(.bottom, 8)
                    .onTapGesture { enlarged = true }
            }
            .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 10))
            .sheet(isPresented: $enlarged) { EnlargedDiagram(html: html, source: source) }
            .sheet(isPresented: Binding(get: { share != nil }, set: { if !$0 { share = nil } })) {
                ActivityView(items: share ?? []).ignoresSafeArea()
            }
        }
    }

    @ViewBuilder
    private var menuItems: some View {
        Button { enlarged = true } label: { Label("Enlarge", systemImage: "arrow.up.left.and.arrow.down.right") }
        Button {
            UIPasteboard.general.string = source
            Haptics.success()
        } label: { Label("Copy source", systemImage: "doc.on.doc") }
        if let svg = handle.svg {
            Button {
                UIPasteboard.general.string = svg
                Haptics.success()
            } label: { Label("Copy SVG", systemImage: "chevron.left.forwardslash.chevron.right") }
            Button {
                let url = FileManager.default.temporaryDirectory.appendingPathComponent("diagram.svg")
                try? Data(svg.utf8).write(to: url, options: .atomic)
                share = [url]
            } label: { Label("Save SVG…", systemImage: "square.and.arrow.down") }
        }
        Button {
            Task { if let img = await handle.snapshot() { share = [img] } }
        } label: { Label("Share as image", systemImage: "photo") }
    }
}

private struct EnlargedDiagram: View {
    let html: String
    let source: String
    @Environment(\.dismiss) private var dismiss
    @State private var height: CGFloat = 0

    var body: some View {
        NavigationStack {
            WebBlock(html: html, height: $height, scrollable: true)
                .padding()
                .navigationTitle("Diagram")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                    ToolbarItem(placement: .topBarLeading) {
                        Button {
                            UIPasteboard.general.string = source
                            Haptics.success()
                        } label: { Image(systemName: "doc.on.doc") }
                        .accessibilityLabel("Copy source")
                    }
                }
        }
    }
}

// ------------------------------------------------------------------ an HTML or SVG preview

/// Code an answer wrote as a page, rendered in a sandbox with no network or scripts.
struct HTMLPreviewSheet: View {
    let html: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            SandboxedPage(html: html)
                .ignoresSafeArea(edges: .bottom)
                .navigationTitle("Preview")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}

struct SandboxedPage: UIViewRepresentable {
    let html: String
    var allowScripts = false

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .nonPersistent()
        cfg.defaultWebpagePreferences.allowsContentJavaScript = allowScripts
        let v = WKWebView(frame: .zero, configuration: cfg)
        v.loadHTMLString(html, baseURL: nil)
        return v
    }

    func updateUIView(_ v: WKWebView, context: Context) {}
}
