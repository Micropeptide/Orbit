import SwiftUI
import QuickLook

/// Everything Orbit made or you gave it, grouped the way you think about them.
/// Files live on the Mac; this fetches on demand and caches nothing but the
/// thumbnail the system already holds.
struct FilesView: View {
    @EnvironmentObject var state: AppState
    @State private var files: [RemoteFile] = []
    @State private var loading = true
    @State private var search = ""
    @State private var preview: URL?
    @State private var failed: String?
    @State private var shareURL: URL?
    @State private var toast: String?
    @State private var sort: FileSort = .newest
    @State private var type: FileType = .all

    private var groups: [(String, [RemoteFile])] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        let matched = (q.isEmpty ? files : files.filter { $0.name.lowercased().contains(q) })
            .filter(type.matches)
        let order = ["generated": 0, "uploaded": 1, "papers": 2]
        let titles = ["generated": "Made by Orbit", "uploaded": "You attached",
                      "papers": "Papers"]
        return Dictionary(grouping: matched) { $0.area ?? "generated" }
            .sorted { (order[$0.key] ?? 9) < (order[$1.key] ?? 9) }
            .map { (titles[$0.key] ?? $0.key.capitalized, $0.value.sorted(by: sort.order)) }
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
                    List {
                        ForEach(groups, id: \.0) { title, items in
                            Section(title) {
                                ForEach(items) { f in
                                    Button { open(f) } label: { row(f) }
                                        .buttonStyle(.plain)
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
                                        .contextMenu {
                                            Button { open(f) } label: {
                                                Label("Preview", systemImage: "eye")
                                            }
                                            Button { share(f) } label: {
                                                Label("Share", systemImage: "square.and.arrow.up")
                                            }
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
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Files")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $search, prompt: "Search files")
            .toolbar {
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
            }
            .refreshable { await load() }
            .task { await load() }
            .quickLookPreview($preview)
            .sheet(item: $shareURL) { url in
                ActivityView(items: [url]).ignoresSafeArea()
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

    private func row(_ f: RemoteFile) -> some View {
        HStack(spacing: 12) {
            icon(for: f)
                .frame(width: 42, height: 42)
                .background(.quaternary.opacity(0.4), in: .rect(cornerRadius: 9))
            VStack(alignment: .leading, spacing: 2) {
                Text(f.name).lineLimit(1).font(.callout)
                Text(f.subtitle).font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
        }
        .padding(.vertical, 3)
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

    private func load() async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        do { files = try await server.files() }
        catch { failed = error.localizedDescription }
    }

    private func bin(_ f: RemoteFile) async {
        guard let server = state.server else { return }
        do {
            try await server.deleteFile(rel: f.rel)
            files.removeAll { $0.rel == f.rel }
            await flash("Moved to the bin on your Mac")
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

    private func flash(_ text: String) async {
        withAnimation { toast = text }
        try? await Task.sleep(nanoseconds: 2_200_000_000)
        withAnimation { toast = nil }
    }

    /// Files stay on the Mac, so opening one downloads it to a temporary spot
    /// and hands it to QuickLook — the same viewer Mail and Files use.
    private func open(_ f: RemoteFile) {
        guard let server = state.server else { return }
        Task {
            do { preview = try await server.download(rel: f.rel, name: f.name) }
            catch { failed = error.localizedDescription }
        }
    }
}

enum FileSort: CaseIterable {
    case newest, name, size
    var label: String {
        switch self { case .newest: return "Newest first"; case .name: return "By name"; case .size: return "Largest first" }
    }
    var order: (RemoteFile, RemoteFile) -> Bool {
        switch self {
        case .newest: return { $0.mtime > $1.mtime }
        case .name:   return { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        case .size:   return { ($0.bytes ?? 0) > ($1.bytes ?? 0) }
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

    var id: String { rel }
    var isImage: Bool {
        ["png", "jpg", "jpeg", "gif", "webp", "heic"].contains(ext)
    }
    var ext: String { (name as NSString).pathExtension.lowercased() }

    var symbol: String {
        switch ext {
        case "pdf": return "doc.richtext"
        case "csv", "xlsx", "tsv": return "tablecells"
        case "md", "txt": return "doc.text"
        case "py", "swift", "js", "json", "sh": return "chevron.left.forwardslash.chevron.right"
        case "docx", "doc": return "doc"
        case "pptx": return "rectangle.on.rectangle"
        default: return "doc"
        }
    }

    var subtitle: String {
        var bits: [String] = []
        if let b = bytes {
            bits.append(ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .file))
        }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .abbreviated
        bits.append(f.localizedString(for: Date(timeIntervalSince1970: mtime), relativeTo: .now))
        if let from = from_title, !from.isEmpty { bits.append("from “\(from)”") }
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
