import SwiftUI

/// Claude Code's own instructions and memory: the CLAUDE.md files and the notes
/// Claude keeps per folder — the same files a terminal session reads, edited in
/// place (the Mac backs up the previous version).
struct ClaudeMemoryView: View {
    @EnvironmentObject var state: AppState
    var sid: String?

    @State private var data: ClaudeMemoryState?
    @State private var cwd: String?
    @State private var chatInstructions = ""
    @State private var savedChatInstructions = ""
    @State private var loading = true
    @State private var note: String?
    @State private var confirmDelete: ClaudeMemoryState.Item?
    /// Any folder on the Mac, typed: Claude keeps memory for folders it has not worked in yet too.
    @State private var askFolder = false
    @State private var otherFolder = ""

    var body: some View {
        List {
            if let d = data {
                folderSection(d)

                Section {
                    ForEach(d.instructions ?? []) { f in
                        NavigationLink {
                            ClaudeTextEditor(title: f.label, subtitle: Self.tilde(f.path),
                                             initial: f.text ?? "",
                                             placeholder: "Nothing yet — what should Claude always know here?") { text in
                                try await state.server?.saveClaudeInstructions(scope: f.scope, cwd: d.cwd, text: text)
                                await load()
                            }
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(f.label)
                                Text(Self.tilde(f.path) + (f.exists == true ? "" : " · not created yet"))
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                            }
                        }
                    }
                } header: {
                    Text("Instructions")
                } footer: {
                    Text("CLAUDE.md files Claude reads in this folder.")
                }

                if let sid {
                    Section {
                        LibraryTextEditor(placeholder: "e.g. Answer in Chinese in this chat.",
                                          text: $chatInstructions, minHeight: 70)
                        if chatInstructions != savedChatInstructions {
                            Button("Save for this chat") { Task { await saveChat(sid) } }
                        }
                    } header: {
                        Text("This chat's instructions")
                    } footer: {
                        Text("Added to Claude's system prompt for this chat only.")
                    }
                }

                Section {
                    let items = d.memory?.items ?? []
                    if items.isEmpty {
                        Text("No memories in this folder yet. Claude writes them as it works, or add one.")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    ForEach(items) { m in
                        NavigationLink {
                            ClaudeTextEditor(title: m.name, subtitle: m.file, initial: m.text ?? "",
                                             placeholder: "") { text in
                                try await state.server?.saveClaudeMemory(cwd: d.cwd, file: m.file, text: text)
                                await load()
                            }
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(m.name).font(.body.weight(.medium))
                                Text([m.type ?? "", m.description ?? "", LibraryNames.ago(m.mtime)]
                                        .filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) { confirmDelete = m } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                    NavigationLink {
                        NewClaudeMemory(cwd: d.cwd, existing: items.map(\.file)) { await load() }
                    } label: {
                        Label("Add a memory", systemImage: "plus")
                    }
                    if let index = d.memory?.index, !index.isEmpty {
                        NavigationLink {
                            ScrollView {
                                Text(index).font(.caption.monospaced()).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading).padding()
                            }
                            .navigationTitle("MEMORY.md")
                            .navigationBarTitleDisplayMode(.inline)
                        } label: {
                            Label("MEMORY.md, the index Claude loads", systemImage: "list.bullet.rectangle")
                        }
                    }
                } header: {
                    Text("Claude's memory · \(d.memory?.items?.count ?? 0)")
                } footer: {
                    Text(Self.tilde(d.memory?.dir ?? ""))
                }
            }
        }
        .overlay { if loading && data == nil { ProgressView() } }
        .navigationTitle("Claude Code memory")
        .navigationBarTitleDisplayMode(.inline)
        .task { if data == nil { await load() } }
        .refreshable { await load() }
        .confirmationDialog("Delete \(confirmDelete?.file ?? "")?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Move to Trash", role: .destructive) {
                if let m = confirmDelete { Task { await delete(m) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The file goes to the Mac's Trash and its line leaves MEMORY.md.")
        }
        .libraryNote($note)
        .alert("Folder on the Mac", isPresented: $askFolder) {
            TextField("/path/to/folder", text: $otherFolder)
                .autocorrectionDisabled().textInputAutocapitalization(.never)
            Button("Open") {
                let p = otherFolder.trimmingCharacters(in: .whitespaces)
                guard !p.isEmpty else { return }
                cwd = p
                Task { await load() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The folder's full path. Its CLAUDE.md files and Claude's memory for it are shown.")
        }
    }

    private func folderSection(_ d: ClaudeMemoryState) -> some View {
        Section {
            Menu {
                Button {
                    cwd = nil
                    Task { await load() }
                } label: {
                    Text(sid == nil ? "Default folder" : "This chat's folder")
                }
                ForEach((d.folders ?? []).filter { $0.path != d.cwd }) { f in
                    Button {
                        cwd = f.path
                        Task { await load() }
                    } label: {
                        Text("\(Self.tilde(f.path)) · \(f.count ?? 0)")
                    }
                }
                Divider()
                Button {
                    otherFolder = cwd ?? d.cwd
                    askFolder = true
                } label: {
                    Label("Another folder…", systemImage: "folder")
                }
            } label: {
                HStack {
                    Text("Folder").foregroundStyle(.primary)
                    Spacer()
                    Text(Self.tilde(d.cwd)).foregroundStyle(.secondary)
                        .lineLimit(1).truncationMode(.head)
                    Image(systemName: "chevron.up.chevron.down").font(.caption).foregroundStyle(.secondary)
                }
            }
        } footer: {
            Text("Claude Code chats use these files, not Orbit's memory.")
        }
    }

    /// Shows a home folder as ~ so paths stay short on a phone.
    static func tilde(_ p: String) -> String {
        guard let re = try? NSRegularExpression(pattern: "^/Users/[^/]+") else { return p }
        return re.stringByReplacingMatches(in: p, range: NSRange(location: 0, length: (p as NSString).length),
                                           withTemplate: "~")
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            let d = try await server.claudeMemory(sid: sid, cwd: cwd)
            data = d
            let t = d.chat_instructions ?? ""
            if chatInstructions == savedChatInstructions { chatInstructions = t }
            savedChatInstructions = t
        } catch { note = error.localizedDescription }
        loading = false
    }

    private func saveChat(_ sid: String) async {
        guard let server = state.server else { return }
        do {
            try await server.setClaudeChatInstructions(sid: sid, text: chatInstructions)
            savedChatInstructions = chatInstructions
            note = "This chat's instructions saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func delete(_ m: ClaudeMemoryState.Item) async {
        guard let server = state.server, let d = data else { return }
        do {
            try await server.deleteClaudeMemory(cwd: d.cwd, file: m.file)
            note = "Moved \(m.file) to the Trash"
            Haptics.success()
        } catch { note = error.localizedDescription }
        await load()
    }
}

/// Edit one of Claude's files in place.
struct ClaudeTextEditor: View {
    @Environment(\.dismiss) private var dismiss
    let title: String
    let subtitle: String
    let initial: String
    let placeholder: String
    var onSave: (String) async throws -> Void

    @State private var text = ""
    @State private var filled = false
    @State private var saving = false
    @State private var note: String?

    var body: some View {
        Form {
            Section {
                LibraryTextEditor(placeholder: placeholder, text: $text, minHeight: 320, monospaced: true)
            } footer: {
                Text(subtitle + " · the previous version is backed up on the Mac")
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }.disabled(text == initial)
                }
            }
        }
        .onAppear { if !filled { text = initial; filled = true } }
        .libraryNote($note)
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            try await onSave(text)
            Haptics.success()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}

struct NewClaudeMemory: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let cwd: String
    var existing: [String] = []
    var onSaved: () async -> Void

    @State private var file = ""

    private var fileName: String {
        let f = file.trimmingCharacters(in: .whitespaces)
        return f.isEmpty || f.hasSuffix(".md") ? f : f + ".md"
    }
    @State private var text = "---\nname: \ndescription: \nmetadata:\n  type: user\n---\n\n"
    @State private var saving = false
    @State private var note: String?

    var body: some View {
        Form {
            Section {
                TextField("File name, e.g. lab-context.md", text: $file)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } footer: {
                if existing.contains(fileName) {
                    Text("A memory with that name exists — open it from the list to edit it.")
                        .foregroundStyle(.orange)
                } else {
                    Text("A new memory is also listed in MEMORY.md.")
                }
            }
            Section("Memory") {
                LibraryTextEditor(placeholder: "", text: $text, minHeight: 260, monospaced: true)
            }
        }
        .navigationTitle("New memory")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }
                        .disabled(fileName.isEmpty || existing.contains(fileName))
                }
            }
        }
        .libraryNote($note)
    }

    private func save() async {
        guard let server = state.server else { return }
        saving = true
        defer { saving = false }
        do {
            try await server.saveClaudeMemory(cwd: cwd, file: fileName, text: text)
            Haptics.success()
            await onSaved()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}
