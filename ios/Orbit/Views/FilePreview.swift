import SwiftUI
import WebKit

/// A file named in an answer, shown without leaving the chat.
///
/// Pictures, PDFs and pages come as a preview link the Mac hands out; a
/// document or spreadsheet is rendered on the Mac first. Nothing here needs
/// the pairing token — a preview link is its own, narrow permission.
struct FilePreviewSheet: View {
    let target: FilePreviewTarget
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    enum Shown { case image(UIImage), page(URL) }

    @State private var shown: Shown?
    @State private var previewPath: String?
    @State private var failed: String?
    @State private var loading = true
    @State private var shareURL: URL?
    @State private var sharing = false

    private var info: ResolvedPath { target.info }

    var body: some View {
        NavigationStack {
            Group {
                if info.isFolder {
                    details(icon: "folder", note: "A folder — there is nothing to preview on the phone.")
                } else if let shown {
                    switch shown {
                    case .image(let img): ZoomingImage(image: img)
                    case .page(let url): WebPage(url: url).ignoresSafeArea(edges: .bottom)
                    }
                } else if loading {
                    ProgressView("Asking your Mac").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    details(icon: "doc", note: failed ?? "This file has no preview.")
                }
            }
            .navigationTitle(info.displayName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        if previewPath != nil {
                            Button { share() } label: {
                                Label("Share", systemImage: "square.and.arrow.up")
                            }
                        }
                        // copy paths and links, attach it or put its path in your message
                        FileMenuItems(file: info, sid: target.sid, showPreview: false)
                        Button {
                            UIPasteboard.general.string = info.displayName
                            Haptics.success()
                        } label: { Label("Copy name", systemImage: "textformat") }
                    } label: {
                        if sharing { ProgressView().controlSize(.small) }
                        else { Image(systemName: "square.and.arrow.up") }
                    }
                    .accessibilityLabel("Share or copy")
                }
            }
            .sheet(item: $shareURL) { ActivityView(items: [$0]).ignoresSafeArea() }
            .task { await load() }
        }
    }

    private func details(icon: String, note: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: icon).font(.system(size: 44)).foregroundStyle(.secondary)
            Text(info.displayName).font(.headline).multilineTextAlignment(.center)
            if let p = info.path {
                Text((info.host.map { "\($0): " } ?? "") + p)
                    .font(.caption.monospaced()).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center).textSelection(.enabled)
            }
            if let s = info.size, !info.isFolder {
                Text(ByteCountFormatter.string(fromByteCount: Int64(s), countStyle: .file))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text(note).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func load() async {
        defer { loading = false }
        guard !info.isFolder, let server = state.server, let path = info.path else { return }
        var link = info.url
        var kind: String? = info.category == "image" ? "image" : nil
        let rendered = ["doc", "sheet", "archive"].contains(info.category ?? "")
        if link == nil {
            do {
                let r = try await server.fileAction(sid: target.sid, path: path,
                                                    action: rendered ? "render" : "preview")
                link = r.url
                kind = r.kind ?? kind
            } catch {
                failed = error.localizedDescription
            }
        }
        // a file the Mac will not show as it is may still render (HEIC, a slide deck…)
        if link == nil, !rendered,
           let r = try? await server.fileAction(sid: target.sid, path: path, action: "render") {
            link = r.url; kind = r.kind; failed = nil
        }
        guard let link, let url = await server.absolute(link) else { return }
        previewPath = link
        if kind == "image" {
            if let (data, _) = try? await URLSession.shared.data(from: url), let img = UIImage(data: data) {
                shown = .image(img); return
            }
        }
        shown = .page(url)
    }

    /// Pull the bytes down under the file's own name, then the share sheet.
    private func share() {
        guard let server = state.server, let previewPath else { return }
        sharing = true
        Task {
            defer { sharing = false }
            // a rendered preview is not the file itself: keep its own extension
            var name = info.displayName
            if let ext = URL(string: previewPath)?.pathExtension, !ext.isEmpty,
               (name as NSString).pathExtension.lowercased() != ext.lowercased() {
                name = (name as NSString).deletingPathExtension + "." + ext
            }
            do { shareURL = try await server.downloadPreview(previewPath, name: name) }
            catch { failed = error.localizedDescription }
        }
    }
}

/// A page from the Mac, in a web view — PDFs and HTML render natively.
struct WebPage: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .nonPersistent()
        let v = WKWebView(frame: .zero, configuration: cfg)
        v.allowsBackForwardNavigationGestures = true
        v.load(URLRequest(url: url))
        return v
    }

    func updateUIView(_ v: WKWebView, context: Context) {
        if v.url == nil { v.load(URLRequest(url: url)) }
    }
}

/// Fit to the screen; pinch or double-tap to look closer.
struct ZoomingImage: View {
    let image: UIImage
    @State private var scale: CGFloat = 1
    @State private var base: CGFloat = 1

    var body: some View {
        GeometryReader { geo in
            ScrollView([.horizontal, .vertical], showsIndicators: false) {
                Image(uiImage: image)
                    .resizable().scaledToFit()
                    .frame(width: geo.size.width * scale)
                    .frame(minHeight: geo.size.height)
            }
            .defaultScrollAnchor(.center)
        }
        .gesture(MagnifyGesture()
            .onChanged { scale = max(1, min(6, base * $0.magnification)) }
            .onEnded { _ in base = scale })
        .onTapGesture(count: 2) { withAnimation { scale = scale > 1 ? 1 : 2.5; base = scale } }
    }
}
