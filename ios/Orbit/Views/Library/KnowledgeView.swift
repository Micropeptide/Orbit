import SwiftUI
import UniformTypeIdentifiers

/// The document library: papers, protocols, anything readable. Orbit searches it
/// before the web. A document can belong to every chat or to one project.
struct KnowledgeView: View {
    @EnvironmentObject var state: AppState
    @State private var docs: [KnowledgeDoc] = []
    @State private var loading = true
    @State private var busy: String?
    @State private var note: String?
    @State private var picking = false
    @State private var confirmDelete: KnowledgeDoc?
    @State private var failures: [KnowledgeIndexStats.Failure] = []

    private var totalChunks: Int { docs.reduce(0) { $0 + ($1.chunks ?? 0) } }

    var body: some View {
        List {
            if docs.isEmpty && !loading {
                ContentUnavailableView("No documents yet", systemImage: "books.vertical",
                                       description: Text("Add PDFs, papers, protocols — anything readable. "
                                                         + "Orbit searches them before the web."))
            }
            if !docs.isEmpty {
                Section {
                    ForEach(docs) { d in row(d) }
                } header: {
                    Text("\(docs.count) document\(docs.count == 1 ? "" : "s") · \(totalChunks) chunk\(totalChunks == 1 ? "" : "s")")
                } footer: {
                    Text("Hold a document to scope it to a project, or swipe to move it to the bin on your Mac.")
                }
            }
            if !failures.isEmpty {
                Section("Could not index") {
                    ForEach(failures, id: \.self) { f in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(f.doc ?? "?").font(.subheadline)
                            Text(f.why ?? "").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .overlay { if loading && docs.isEmpty { ProgressView() } }
        .safeAreaInset(edge: .bottom) {
            if let busy {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(busy).font(.footnote)
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(.thinMaterial, in: .capsule)
                .padding(.bottom, 8)
            }
        }
        .navigationTitle("Knowledge")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Menu {
                    Button { picking = true } label: {
                        Label("Add documents", systemImage: "doc.badge.plus")
                    }
                    Button { Task { await reindex() } } label: {
                        Label("Reindex", systemImage: "arrow.clockwise")
                    }
                } label: { Image(systemName: "plus") }
                .disabled(busy != nil)
                .accessibilityLabel("Add or reindex")
            }
        }
        .fileImporter(isPresented: $picking, allowedContentTypes: [.item],
                      allowsMultipleSelection: true) { result in
            if case .success(let urls) = result { Task { await add(urls) } }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Move \(confirmDelete?.name ?? "") to the bin?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Move to bin", role: .destructive) {
                if let d = confirmDelete { Task { await delete(d) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It leaves the library and the search index. You can restore it from the bin on your Mac.")
        }
        .libraryNote($note)
    }

    private func projectName(_ id: String?) -> String? {
        guard let id else { return nil }
        return state.projects.first { $0.id == id }?.name ?? id
    }

    private func row(_ d: KnowledgeDoc) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon(for: d.name)).foregroundStyle(.secondary).frame(width: 22)
            VStack(alignment: .leading, spacing: 3) {
                Text(d.name).lineLimit(2)
                HStack(spacing: 4) {
                    Text("\(d.sizeText) · \(d.chunks ?? 0) chunk\((d.chunks ?? 0) == 1 ? "" : "s")")
                    if (d.chunks ?? 0) == 0 {
                        Text("· not indexed").foregroundStyle(.orange)
                    }
                }
                .font(.caption).foregroundStyle(.secondary)
                Text(projectName(d.project).map { "Project: \($0)" } ?? "Every chat")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) { confirmDelete = d } label: {
                Label("Bin", systemImage: "trash")
            }
        }
        .contextMenu {
            Menu {
                Button { Task { await assign(d, to: nil) } } label: {
                    if d.project == nil { Label("Every chat", systemImage: "checkmark") }
                    else { Text("Every chat") }
                }
                ForEach(state.projects) { p in
                    Button { Task { await assign(d, to: p.id) } } label: {
                        if d.project == p.id { Label(p.name, systemImage: "checkmark") }
                        else { Text(p.name) }
                    }
                }
            } label: {
                Label("Searched in…", systemImage: "folder")
            }
            Button(role: .destructive) { confirmDelete = d } label: {
                Label("Move to bin", systemImage: "trash")
            }
        }
    }

    private func icon(for name: String) -> String {
        switch (name as NSString).pathExtension.lowercased() {
        case "pdf": return "doc.richtext"
        case "md", "txt": return "doc.plaintext"
        case "csv", "tsv", "xlsx", "xls": return "tablecells"
        case "docx", "doc": return "doc.text"
        default: return "doc"
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        do { docs = try await server.knowledge() }
        catch { note = error.localizedDescription }
        if state.projects.isEmpty { await state.loadProjects() }
        loading = false
    }

    private func add(_ urls: [URL]) async {
        guard let server = state.server else { return }
        var added = 0
        var last: KnowledgeIndexStats?
        for (i, url) in urls.enumerated() {
            busy = urls.count > 1 ? "Adding and indexing \(i + 1) of \(urls.count)…" : "Adding and indexing…"
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let data = try Data(contentsOf: url)
                let mime = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
                    ?? "application/octet-stream"
                last = try await server.uploadKnowledge(data: data, filename: url.lastPathComponent, mime: mime)
                added += 1
            } catch {
                note = "\(url.lastPathComponent): \(error.localizedDescription)"
            }
        }
        busy = nil
        if let last {
            failures = last.failures ?? []
            note = "Added \(added) · \(last.docs ?? 0) documents, \(last.chunks ?? 0) chunks"
            Haptics.success()
        }
        await load()
    }

    private func reindex() async {
        guard let server = state.server else { return }
        busy = "Reindexing…"
        do {
            let r = try await server.reindexKnowledge()
            failures = r.failures ?? []
            note = "\(r.docs ?? 0) documents · \(r.chunks ?? 0) chunks"
        } catch { note = error.localizedDescription }
        busy = nil
        await load()
    }

    private func assign(_ d: KnowledgeDoc, to project: String?) async {
        guard let server = state.server else { return }
        do {
            try await server.setKnowledgeProject(name: d.name, project: project)
            note = project == nil ? "Searched in every chat" : "Scoped to \(projectName(project) ?? "project")"
        } catch { note = error.localizedDescription }
        await load()
    }

    private func delete(_ d: KnowledgeDoc) async {
        guard let server = state.server else { return }
        busy = "Moving to the bin…"
        do {
            try await server.deleteKnowledge(name: d.name)
            note = "Moved \(d.name) to the bin"
        } catch { note = error.localizedDescription }
        busy = nil
        await load()
    }
}
