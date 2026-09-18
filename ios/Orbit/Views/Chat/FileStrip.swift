import SwiftUI

/// Files an answer wrote or points to, as cards under it; every file a chat
/// names, in one sheet; and what to do with a path that is not there.
/// Wording follows the Mac's web UI (fileStrip, showChatFiles, findNamed).

extension ResolvedPath {
    var symbol: String {
        if isFolder { return "folder" }
        switch category ?? "" {
        case "image": return "photo"
        case "pdf": return "doc.richtext"
        case "html": return "globe"
        case "markdown": return "doc.text"
        case "table", "sheet": return "tablecells"
        case "notebook": return "book.pages"
        case "data": return "cylinder.split.1x2"
        case "audio": return "waveform"
        case "video": return "film"
        case "archive": return "archivebox"
        case "code": return "chevron.left.forwardslash.chevron.right"
        default: return "doc"
        }
    }

    /// Pictures first, then what was likely made for you, then the rest.
    var stripRank: Int {
        switch category ?? "" {
        case "image": return 0
        case "html", "pdf": return 1
        case "table", "sheet", "doc", "notebook": return 2
        case "markdown", "video", "audio": return 3
        default: return 5
        }
    }

    /// "12 KB · ~/project/results"
    var metaLine: String {
        let size = isFolder ? "folder" : ByteCountFormatter.string(fromByteCount: Int64(self.size ?? 0), countStyle: .file)
        var d = dir ?? ((path ?? "") as NSString).deletingLastPathComponent
        if let r = d.range(of: #"^/Users/[^/]+"#, options: .regularExpression) { d.replaceSubrange(r, with: "~") }
        if d.count > 42 { d = "…" + d.suffix(41) }
        return size + " · " + (host.map { $0 + ":" } ?? "") + d
    }

    var isTextLike: Bool {
        ["text", "code", "markdown", "table", "data", "html", "notebook"].contains(category ?? "") && (size ?? 0) < 2_000_000
    }
}

// ------------------------------------------------------------------ under an answer

struct AnswerFileStrip: View {
    let message: Message
    @Environment(\.fileLinkSid) private var sid
    @ObservedObject private var links = FileLinks.shared
    @State private var names: [String] = []
    @State private var showAll = false

    private var files: [ResolvedPath] {
        guard let sid, let map = links.resolved[sid] else { return [] }
        var seen = Set<String>()
        var out: [ResolvedPath] = []
        for n in names {
            guard let f = map[n], f.exists, !f.isFolder, let p = f.path, !seen.contains(p) else { continue }
            seen.insert(p)
            out.append(f)
        }
        return out.enumerated().sorted { ($0.element.stripRank, $0.offset) < ($1.element.stripRank, $1.offset) }.map(\.element)
    }

    var body: some View {
        let list = files
        Group {
            if !list.isEmpty, let sid {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(list.count == 1 ? "1 file in this answer" : "\(list.count) files in this answer")
                            .font(.caption2).foregroundStyle(.secondary)
                        Spacer()
                        if list.count > 6 {
                            Button(showAll ? "show fewer" : "show all") { withAnimation { showAll.toggle() } }
                                .font(.caption2).buttonStyle(.plain).foregroundStyle(.tint)
                        }
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(showAll ? list : Array(list.prefix(6))) { f in
                                FileCard(file: f, sid: sid)
                            }
                        }
                    }
                }
            }
        }
        .task(id: sid.map { $0 + "\u{0}" + message.id.uuidString + "\(message.text.count)" }) {
            guard let sid else { return }
            let found = FileLinks.names(in: message)
            if found != names { names = found }
            links.request(sid: sid, names: found)
        }
    }
}

/// A file as a small card: a thumbnail for a picture, else its kind.
struct FileCard: View {
    let file: ResolvedPath
    let sid: String

    var body: some View {
        Button {
            Haptics.tap()
            FileLinks.shared.presenting = FilePreviewTarget(sid: sid, info: file)
        } label: {
            HStack(spacing: 8) {
                Group {
                    if file.category == "image", let url = file.url, (file.size ?? 0) < 25_000_000 {
                        RemoteImage(path: url) { AnyView(Image(systemName: "photo").foregroundStyle(.secondary)) }
                            .frame(width: 38, height: 38)
                            .clipShape(.rect(cornerRadius: 6))
                    } else {
                        Image(systemName: file.symbol).font(.title3).foregroundStyle(.tint)
                            .frame(width: 38, height: 38)
                    }
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(file.displayName).font(.caption.weight(.medium)).lineLimit(1)
                    Text(file.metaLine).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
                .frame(maxWidth: 150, alignment: .leading)
            }
            .padding(7)
            .background(.quaternary.opacity(0.35), in: .rect(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .contextMenu { FileMenuItems(file: file, sid: sid) }
    }
}

// ------------------------------------------------------------------ a file's menu

/// What you can do with a file an answer named, from the phone.
struct FileMenuItems: View {
    let file: ResolvedPath
    let sid: String
    var showPreview = true
    @EnvironmentObject var state: AppState

    var body: some View {
        let path = file.path ?? file.displayName
        let remote = file.host?.isEmpty == false
        if showPreview {
            Button {
                FileLinks.shared.presenting = FilePreviewTarget(sid: sid, info: file)
            } label: { Label("Preview", systemImage: "eye") }
        }
        Button { copy(path) } label: { Label("Copy path", systemImage: "doc.on.doc") }
        let rel = FileLinks.shared.relative(path, sid: sid)
        if rel != path {
            Button { copy(rel) } label: { Label("Copy relative path", systemImage: "doc.on.doc") }
        }
        if remote, let host = file.host {
            Button { copy("scp \(host):\(Self.shellQuote(path)) .") } label: {
                Label("Copy scp command", systemImage: "terminal")
            }
        }
        Button {
            let enc = remote ? path : (path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path)
            copy("[\(file.displayName)](\(enc))")
        } label: { Label("Copy as Markdown link", systemImage: "link") }
        if file.isTextLike && !file.isFolder {
            Button { Task { await copyContents() } } label: {
                Label("Copy contents", systemImage: "text.alignleft")
            }
        }
        // both go into the open chat's message box, so they need that chat on screen
        let inChat = state.openChat?.sid == sid
        if !file.isFolder && !remote {
            Button {
                Task { await state.attachExisting(file) }
            } label: { Label("Attach to your next message", systemImage: "paperclip") }
            .disabled(!inChat)
        }
        Button { state.insertInDraft(remote ? path : rel) } label: {
            Label("Insert path in message", systemImage: "text.insert")
        }
        .disabled(!inChat)
    }

    private func copy(_ s: String) {
        UIPasteboard.general.string = s
        Haptics.success()
        state.toast("Copied")
    }

    private func copyContents() async {
        guard let server = state.server, let path = file.path else { return }
        do {
            var link = file.url
            if link == nil { link = try await server.fileAction(sid: sid, path: path, action: "preview").url }
            guard let link else { return }
            guard let url = await server.absolute(link) else { return }
            let (data, _) = try await URLSession.shared.data(from: url)
            UIPasteboard.general.string = String(decoding: data, as: UTF8.self)
            Haptics.success()
            state.toast("Contents copied")
        } catch { state.toast("Could not read it: \(error.localizedDescription)") }
    }

    static func shellQuote(_ s: String) -> String {
        if s.range(of: #"^[\w@%+=:,./-]+$"#, options: .regularExpression) != nil { return s }
        return "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

// ------------------------------------------------------------------ files in this chat

struct ChatFilesSheet: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @ObservedObject private var links = FileLinks.shared
    @Environment(\.dismiss) private var dismiss
    @State private var files: [ResolvedPath]?
    @State private var preview: FilePreviewTarget?

    var body: some View {
        NavigationStack {
            List {
                if let files {
                    if files.isEmpty {
                        Text("This chat names no files yet.").foregroundStyle(.secondary)
                    } else {
                        Section {
                            ForEach(files) { f in
                                Button {
                                    preview = FilePreviewTarget(sid: sid, info: f)
                                } label: { row(f) }
                                .buttonStyle(.plain)
                                .contextMenu { FileMenuItems(file: f, sid: sid, showPreview: false) }
                            }
                        } header: {
                            Text("\(files.count) files and folders, newest first"
                                 + (links.cwd[sid].map { " · this chat works in \($0)" } ?? ""))
                                .textCase(nil)
                        }
                    }
                } else {
                    ProgressView().frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Files in this chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            // the preview opens over this list, so you come back to it
            .sheet(item: $preview) { FilePreviewSheet(target: $0) }
            .task { files = await state.chatFiles(sid: sid) }
        }
    }

    private func row(_ f: ResolvedPath) -> some View {
        HStack(spacing: 12) {
            Group {
                if f.category == "image", let url = f.url {
                    RemoteImage(path: url) { AnyView(Image(systemName: "photo").foregroundStyle(.secondary)) }
                        .clipShape(.rect(cornerRadius: 7))
                } else {
                    Image(systemName: f.symbol).font(.title3).foregroundStyle(.tint)
                }
            }
            .frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(f.displayName).font(.callout).lineLimit(1)
                Text(f.metaLine).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
        }
        .contentShape(.rect)
    }
}

// ------------------------------------------------------------------ a path that is not there

struct MissingFileSheet: View {
    let target: FilePreviewTarget
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var found: [ResolvedPath]?
    @State private var searching = false
    @State private var preview: FilePreviewTarget?

    private var path: String { target.info.path ?? target.info.displayName }
    private var name: String { (path as NSString).lastPathComponent }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Not found" + (target.info.host.map { " on \($0)" } ?? " on the Mac"))
                            .font(.subheadline.weight(.semibold))
                        Text(path).font(.caption.monospaced()).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    Button {
                        Task { await find() }
                    } label: {
                        HStack {
                            Label("Find files named \(name)", systemImage: "magnifyingglass")
                            if searching { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(searching)
                    Button {
                        UIPasteboard.general.string = path
                        Haptics.success()
                        state.toast("Copied")
                    } label: { Label("Copy path", systemImage: "doc.on.doc") }
                    Button {
                        state.insertInDraft(path)
                        dismiss()
                    } label: { Label("Insert path in message", systemImage: "text.insert") }
                }
                if let found {
                    Section(found.isEmpty ? "No file named \(name) found" : "Files named \(name)") {
                        ForEach(found) { f in
                            Button { preview = FilePreviewTarget(sid: target.sid, info: f) } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Label(f.home ?? f.path ?? f.displayName, systemImage: f.symbol)
                                        .font(.callout).lineLimit(2)
                                    Text(f.metaLine).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                            .contextMenu { FileMenuItems(file: f, sid: target.sid, showPreview: false) }
                        }
                    }
                }
            }
            .navigationTitle(name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .sheet(item: $preview) { FilePreviewSheet(target: $0) }
        }
    }

    private func find() async {
        guard let server = state.server else { return }
        searching = true
        defer { searching = false }
        do { found = try await server.findFiles(sid: target.sid, name: path) }
        catch { state.toast("Search failed: \(error.localizedDescription)") }
    }
}
