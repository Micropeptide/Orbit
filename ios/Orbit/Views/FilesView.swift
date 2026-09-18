import SwiftUI
import QuickLook

/// Everything Orbit made or you gave it, grouped the way you think about them.
/// Files live on the Mac; this fetches on demand and caches nothing but the
/// thumbnail the system already holds.
struct FilesView: View {
    @EnvironmentObject var state: AppState
    @State private var files: [RemoteFile] = []
    @State private var total = 0
    @State private var loading = true
    @State private var loadingMore = false
    @State private var search = ""
    @State private var preview: URL?
    @State private var typed: RemoteFile?
    @State private var failed: String?
    @State private var shareURL: URL?
    @State private var toast: String?
    @State private var sort: FileSort = .newest
    @State private var type: FileType = .all
    @State private var area = "all"
    @State private var editMode: EditMode = .inactive
    @State private var selected = Set<String>()
    @State private var confirmBulkBin = false
    @State private var renaming: RemoteFile?
    @State private var newName = ""
    @State private var history: RemoteFile?

    static let pageSize = 200
    private static let areaOrder = ["generated", "uploaded", "papers"]
    private static let areaTitles = ["generated": "Made by Orbit", "uploaded": "You attached", "papers": "Papers"]

    private var filtered: [RemoteFile] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        return (q.isEmpty ? files : files.filter { $0.name.lowercased().contains(q) })
            .filter(type.matches)
            .filter { area == "all" || ($0.area ?? "generated") == area }
    }

    private var groups: [(String, [RemoteFile])] {
        let order = Dictionary(uniqueKeysWithValues: Self.areaOrder.enumerated().map { ($1, $0) })
        return Dictionary(grouping: filtered) { $0.area ?? "generated" }
            .sorted { (order[$0.key] ?? 9) < (order[$1.key] ?? 9) }
            .map { (Self.areaTitles[$0.key] ?? $0.key.capitalized, $0.value.sorted(by: sort.order)) }
    }

    /// How many loaded files sit in each area, for the filter.
    private func count(_ a: String) -> Int {
        a == "all" ? files.count : files.filter { ($0.area ?? "generated") == a }.count
    }

    var body: some View {
        NavigationStack {
            Group {
                if loading && files.isEmpty {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if files.isEmpty {
                    ContentUnavailableView(
                        "No files yet", systemImage: "folder",
                        description: Text("Anything Orbit writes, or you attach, shows up here."))
                } else {
                    list
                }
            }
            .navigationTitle("Files")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $search, prompt: "Search files")
            .toolbar { toolbar }
            .environment(\.editMode, $editMode)
            .refreshable { await load() }
            .task { await load() }
            .quickLookPreview($preview)
            .sheet(item: $typed) { TypedFilePreview(file: $0, server: state.server) }
            .sheet(item: $shareURL) { url in
                ActivityView(items: [url]).ignoresSafeArea()
            }
            .sheet(item: $history) { f in
                NavigationStack {
                    CheckpointsView(path: f.rel)
                        .toolbar {
                            ToolbarItem(placement: .confirmationAction) { Button("Done") { history = nil } }
                        }
                }
            }
            .alert("Rename", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
                TextField("New name", text: $newName)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Rename") {
                    if let f = renaming { Task { await rename(f, to: newName) } }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("It stays in the same folder on your Mac.")
            }
            .confirmationDialog("Move \(selected.count) file\(selected.count == 1 ? "" : "s") to the bin?",
                                isPresented: $confirmBulkBin, titleVisibility: .visible) {
                Button("Move to bin", role: .destructive) { Task { await binSelected() } }
                Button("Cancel", role: .cancel) {}
            }
            .overlay(alignment: .bottom) {
                if let toast {
                    Text(toast).font(.footnote.weight(.medium))
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(.thinMaterial, in: .capsule)
                        .padding(.bottom, 12)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .alert("Couldn't do that", isPresented: Binding(
                get: { failed != nil }, set: { if !$0 { failed = nil } })) {
                Button("OK") { failed = nil }
            } message: { Text(failed ?? "") }
        }
    }

    private var list: some View {
        List(selection: $selected) {
            Section {
                Picker("Show", selection: $area) {
                    Text("All (\(count("all")))").tag("all")
                    ForEach(Self.areaOrder.filter { count($0) > 0 }, id: \.self) { a in
                        Text("\(Self.areaTitles[a] ?? a) (\(count(a)))").tag(a)
                    }
                }
                .pickerStyle(.menu)
            }
            ForEach(groups, id: \.0) { title, items in
                Section(title) {
                    ForEach(items) { f in
                        row(f)
                            .tag(f.rel)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    Task { await bin(f) }
                                } label: { Label("Bin", systemImage: "trash") }
                            }
                            .swipeActions(edge: .leading) {
                                Button { share(f) } label: {
                                    Label("Share", systemImage: "square.and.arrow.up")
                                }.tint(.blue)
                            }
                            .contextMenu { menu(f) }
                    }
                }
            }
            if files.count < total {
                Section {
                    Button {
                        Task { await loadMore() }
                    } label: {
                        HStack {
                            Text("Load more · \(files.count) of \(total)")
                            if loadingMore { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(loadingMore)
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button(editMode.isEditing ? "Done" : "Select") {
                withAnimation {
                    editMode = editMode.isEditing ? .inactive : .active
                    if !editMode.isEditing { selected = [] }
                }
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Picker("Sort", selection: $sort) {
                    ForEach(FileSort.allCases, id: \.self) { Text($0.label).tag($0) }
                }
                Picker("Show", selection: $type) {
                    ForEach(FileType.allCases, id: \.self) { Text($0.label).tag($0) }
                }
            } label: {
                Image(systemName: type == .all ? "line.3.horizontal.decrease.circle"
                                               : "line.3.horizontal.decrease.circle.fill")
            }
            .accessibilityLabel("Sort and filter")
        }
        ToolbarItemGroup(placement: .bottomBar) {
            if editMode.isEditing {
                Button(selected.count == filtered.count ? "Select none" : "Select all") {
                    selected = selected.count == filtered.count ? [] : Set(filtered.map(\.rel))
                }
                Spacer()
                Text(selected.isEmpty ? "" : "\(selected.count) selected").font(.footnote)
                Spacer()
                Button {
                    Task { await addSelectedToKnowledge() }
                } label: { Image(systemName: "books.vertical") }
                .disabled(selected.isEmpty)
                .accessibilityLabel("Add to Knowledge")
                Button(role: .destructive) { confirmBulkBin = true } label: { Image(systemName: "trash") }
                    .disabled(selected.isEmpty)
                    .accessibilityLabel("Move to bin")
            }
        }
    }

    private func row(_ f: RemoteFile) -> some View {
        HStack(spacing: 12) {
            icon(for: f)
                .frame(width: 42, height: 42)
                .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 9))
            VStack(alignment: .leading, spacing: 2) {
                Text(f.name).lineLimit(1).font(.callout)
                Text(f.subtitleWithoutSource).font(.caption2).foregroundStyle(.secondary)
                if let from = f.from_title, !from.isEmpty {
                    if let sid = f.from_sid, !sid.isEmpty {
                        // the chat that made it, one tap away
                        Button {
                            state.tab = "chats"
                            state.deepLink = sid
                        } label: {
                            Text("← " + String(from.prefix(40))).font(.caption2).lineLimit(1)
                        }
                        .buttonStyle(.borderless)
                        .disabled(editMode.isEditing)
                    } else {
                        Text("from “\(from)”").font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
            }
            Spacer()
            if !editMode.isEditing {
                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 3)
        .contentShape(.rect)
        .onTapGesture { if !editMode.isEditing { open(f) } }
    }

    @ViewBuilder
    private func menu(_ f: RemoteFile) -> some View {
        Button { open(f) } label: { Label("Preview", systemImage: "eye") }
        Button { share(f) } label: { Label("Share", systemImage: "square.and.arrow.up") }
        Button {
            newName = f.name
            renaming = f
        } label: { Label("Rename…", systemImage: "pencil") }
        Button { history = f } label: { Label("Earlier versions", systemImage: "clock.arrow.circlepath") }
        Divider()
        if f.isText && (f.bytes ?? 0) < 2_000_000 {
            Button { Task { await copyContents(f) } } label: {
                Label("Copy contents", systemImage: "text.alignleft")
            }
        }
        Button { Task { await copyPath(f) } } label: { Label("Copy path", systemImage: "doc.on.doc") }
        Button { copy(f.rel, "Relative path copied") } label: {
            Label("Copy relative path", systemImage: "doc.on.doc")
        }
        Button {
            copy("[\(f.name)](\(f.rel.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? f.rel))", "Link copied")
        } label: { Label("Copy as Markdown link", systemImage: "link") }
        Divider()
        Button { attach(f) } label: { Label("Attach to your next message", systemImage: "paperclip") }
        Button {
            if state.openChat != nil {
                state.insertInDraft(f.rel)
                Task { await flash("Path added to your message") }
            } else {
                copy(f.rel, "No chat open — path copied instead")
            }
        } label: { Label("Insert path in message", systemImage: "text.insert") }
        Button {
            Task { await addToKnowledge(f) }
        } label: {
            Label("Add to Knowledge", systemImage: "books.vertical")
        }
        Button {
            Task { await state.askAbout(file: f) }
        } label: {
            Label("Ask Orbit about it", systemImage: "bubble.left.and.text.bubble.right")
        }
        Divider()
        Button(role: .destructive) {
            Task { await bin(f) }
        } label: { Label("Move to bin", systemImage: "trash") }
    }

    @ViewBuilder
    private func icon(for f: RemoteFile) -> some View {
        if f.isImage {
            // through RemoteImage, not AsyncImage: the thumbnail endpoint needs
            // the pairing token like everything else
            RemoteImage(path: "/api/thumb/\(f.rel)") {
                AnyView(Image(systemName: "photo").foregroundStyle(.secondary))
            }
            .clipShape(.rect(cornerRadius: 9))
        } else {
            Image(systemName: f.symbol).font(.title3).foregroundStyle(.tint)
        }
    }

    // ------------------------------------------------------------ loading

    private func load() async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        do {
            // a refresh keeps as many as you had loaded
            let page = try await server.filesPage(offset: 0, limit: max(Self.pageSize, files.count))
            files = page.items
            total = page.total
            selected = selected.intersection(files.map(\.rel))
        } catch { failed = error.localizedDescription }
    }

    private func loadMore() async {
        guard let server = state.server, !loadingMore else { return }
        loadingMore = true
        defer { loadingMore = false }
        do {
            let page = try await server.filesPage(offset: files.count, limit: Self.pageSize)
            let known = Set(files.map(\.rel))
            files += page.items.filter { !known.contains($0.rel) }
            total = page.total
        } catch { failed = error.localizedDescription }
    }

    // ------------------------------------------------------------ actions

    private func bin(_ f: RemoteFile) async {
        guard let server = state.server else { return }
        do {
            try await server.deleteFile(rel: f.rel)
            files.removeAll { $0.rel == f.rel }
            total = max(0, total - 1)
            await flash("Moved to the bin on your Mac")
        } catch { failed = error.localizedDescription }
    }

    private func binSelected() async {
        guard let server = state.server else { return }
        var done = 0
        for rel in selected {
            if (try? await server.deleteFile(rel: rel)) != nil {
                done += 1
                files.removeAll { $0.rel == rel }
            }
        }
        total = max(0, total - done)
        selected = []
        editMode = .inactive
        await flash("Moved \(done) file\(done == 1 ? "" : "s") to the bin")
    }

    private func addSelectedToKnowledge() async {
        guard let server = state.server else { return }
        var done = 0
        for rel in selected where (try? await server.addToKnowledge(rel: rel)) != nil { done += 1 }
        await flash("Added \(done) to Knowledge")
    }

    private func rename(_ f: RemoteFile, to name: String) async {
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let server = state.server, !n.isEmpty, n != f.name else { return }
        do {
            try await server.renameFile(rel: f.rel, to: n)
            await load()
            await flash("Renamed to \(n)")
        } catch { failed = error.localizedDescription }
    }

    private func share(_ f: RemoteFile) {
        guard let server = state.server else { return }
        Task {
            do { shareURL = try await server.download(rel: f.rel, name: f.name) }
            catch { failed = error.localizedDescription }
        }
    }

    /// A paper you downloaded on the phone becomes searchable on the Mac.
    private func addToKnowledge(_ f: RemoteFile) async {
        guard let server = state.server else { return }
        do {
            try await server.addToKnowledge(rel: f.rel)
            await flash("Added to Knowledge — it is searchable now")
        } catch { failed = error.localizedDescription }
    }

    private func copyContents(_ f: RemoteFile) async {
        guard let server = state.server else { return }
        do {
            let data = try await server.workspaceBytes(rel: f.rel)
            UIPasteboard.general.string = String(decoding: data, as: UTF8.self)
            Haptics.success()
            await flash("Contents copied")
        } catch { failed = error.localizedDescription }
    }

    /// The full path on the Mac, which only the Mac knows.
    private func copyPath(_ f: RemoteFile) async {
        guard let server = state.server else { return }
        let r = try? await server.resolvePathsWithFolder(sid: "", [f.rel])
        if let p = r?.items[f.rel]?.path { copy(p, "Path copied") }
        else if let c = r?.cwd { copy(c + "/" + f.rel, "Path copied") }
        else { copy(f.rel, "Relative path copied") }
    }

    private func attach(_ f: RemoteFile) {
        state.attachments.append(Attachment(name: f.name, kind: "file",
                                            payload: ["kind": "file", "name": f.name, "rel": f.rel]))
        Task { await flash("Attached — it goes with your next message") }
    }

    private func copy(_ s: String, _ note: String) {
        UIPasteboard.general.string = s
        Haptics.success()
        Task { await flash(note) }
    }

    private func flash(_ text: String) async {
        withAnimation { toast = text }
        try? await Task.sleep(nanoseconds: 2_200_000_000)
        withAnimation { if toast == text { toast = nil } }
    }

    /// Text, tables, notebooks and pages open in Orbit's own preview; the rest
    /// downloads to a temporary spot for QuickLook — the viewer Mail and Files use.
    private func open(_ f: RemoteFile) {
        if TypedFilePreview.handles(f) { typed = f; return }
        guard let server = state.server else { return }
        Task {
            do { preview = try await server.download(rel: f.rel, name: f.name) }
            catch { failed = error.localizedDescription }
        }
    }
}

enum FileSort: CaseIterable {
    case newest, name, size, type
    var label: String {
        switch self {
        case .newest: return "Newest first"; case .name: return "By name"
        case .size: return "Largest first"; case .type: return "By type"
        }
    }
    var order: (RemoteFile, RemoteFile) -> Bool {
        switch self {
        case .newest: return { $0.mtime > $1.mtime }
        case .name:   return { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        case .size:   return { ($0.bytes ?? 0) > ($1.bytes ?? 0) }
        case .type:   return { ($0.typeRank, $0.ext, $0.name) < ($1.typeRank, $1.ext, $1.name) }
        }
    }
}

enum FileType: CaseIterable {
    case all, images, pdf, docs, data, code
    var label: String {
        switch self {
        case .all: return "Everything"; case .images: return "Pictures"; case .pdf: return "PDFs"
        case .docs: return "Documents"; case .data: return "Tables"; case .code: return "Code"
        }
    }
    func matches(_ f: RemoteFile) -> Bool {
        switch self {
        case .all:    return true
        case .images: return f.isImage
        case .pdf:    return f.ext == "pdf"
        case .docs:   return ["md", "txt", "docx", "doc", "pptx", "rtf"].contains(f.ext)
        case .data:   return ["csv", "tsv", "xlsx", "json"].contains(f.ext)
        case .code:   return ["py", "swift", "js", "sh", "r", "ipynb"].contains(f.ext)
        }
    }
}

struct RemoteFile: Identifiable, Codable, Hashable {
    var name: String
    var rel: String
    var kind: String?
    var bytes: Int?
    var mtime: Double
    var area: String?
    var from_title: String?
    /// The chat that made it, to open from the list.
    var from_sid: String?

    var id: String { rel }
    var isImage: Bool {
        ["png", "jpg", "jpeg", "gif", "webp", "heic"].contains(ext)
    }
    var ext: String { (name as NSString).pathExtension.lowercased() }
    var isText: Bool {
        ["md", "markdown", "txt", "csv", "tsv", "json", "jsonl", "py", "r", "swift", "js", "ts", "sh", "html", "htm",
         "xml", "yaml", "yml", "toml", "tex", "bib", "log", "ipynb", "sql", "css", "c", "h", "cpp", "go", "rs"].contains(ext)
    }

    var symbol: String {
        switch ext {
        case "pdf": return "doc.richtext"
        case "csv", "xlsx", "tsv": return "tablecells"
        case "md", "txt": return "doc.text"
        case "py", "swift", "js", "json", "sh": return "chevron.left.forwardslash.chevron.right"
        case "ipynb": return "book.pages"
        case "html", "htm": return "globe"
        case "docx", "doc": return "doc"
        case "pptx": return "rectangle.on.rectangle"
        default: return "doc"
        }
    }

    var subtitle: String {
        subtitleWithoutSource + (from_title.flatMap { $0.isEmpty ? nil : " · from “\($0)”" } ?? "")
    }

    var subtitleWithoutSource: String {
        var bits: [String] = []
        if let b = bytes {
            bits.append(ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .file))
        }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .abbreviated
        bits.append(f.localizedString(for: Date(timeIntervalSince1970: mtime), relativeTo: .now))
        return bits.joined(separator: " · ")
    }
}


extension URL: @retroactive Identifiable { public var id: String { absoluteString } }

/// The system share sheet.
struct ActivityView: UIViewControllerRepresentable {
    var items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
