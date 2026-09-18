import SwiftUI

/// Orbit's own memory and standing instructions — added to every Orbit chat.
/// Chats that run through Claude Code use Claude's files instead.
struct MemoryView: View {
    @EnvironmentObject var state: AppState
    @State private var notes: [MemoryNote] = []
    @State private var instructions = ""
    @State private var savedInstructions = ""
    @State private var loading = true
    @State private var savingInstructions = false
    @State private var note: String?
    @State private var confirmDelete: MemoryNote?

    var body: some View {
        List {
            Section {
                if loading && savedInstructions.isEmpty && instructions.isEmpty {
                    ProgressView()
                } else {
                    LibraryTextEditor(placeholder: "e.g. Prefer concise answers with citations. Always give exact gene IDs.",
                                      text: $instructions, minHeight: 120)
                }
            } header: {
                HStack {
                    Text("Standing instructions")
                    Spacer()
                    if instructions != savedInstructions {
                        if savingInstructions { ProgressView().controlSize(.mini) }
                        else { Button("Save") { Task { await saveInstructions() } }.font(.caption.weight(.semibold)) }
                    }
                }
            } footer: {
                Text("Always added to Orbit chats, like a CLAUDE.md.")
            }

            Section {
                if notes.isEmpty && !loading {
                    Text("No memories yet.").foregroundStyle(.secondary)
                }
                ForEach(notes) { m in
                    NavigationLink {
                        MemoryEditor(original: m) { await load() }
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(m.name).font(.body.weight(.medium))
                            Text([m.title ?? "", LibraryNames.ago(m.mtime)].filter { !$0.isEmpty }
                                    .joined(separator: " · "))
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
                    MemoryEditor(original: nil) { await load() }
                } label: {
                    Label("Add a memory", systemImage: "plus")
                }
            } header: {
                Text("Memories")
            } footer: {
                Text("Durable facts, put into every Orbit chat. To pull some out of a conversation, "
                     + "use Suggest memories in that chat's Library options.")
            }

            Section {
                NavigationLink { SystemPromptView() } label: {
                    Label("System prompt", systemImage: "doc.plaintext")
                }
                NavigationLink { ClaudeMemoryView(sid: state.openChat?.sid) } label: {
                    Label("Claude Code memory", systemImage: "sparkles")
                }
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle("Memory & instructions")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete the memory \(confirmDelete?.name ?? "")?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let m = confirmDelete { Task { await delete(m) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .libraryNote($note)
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            notes = try await server.memories()
            let text = try await server.instructions()
            // don't overwrite something being typed
            if instructions == savedInstructions { instructions = text }
            savedInstructions = text
        } catch { note = error.localizedDescription }
        loading = false
    }

    private func saveInstructions() async {
        guard let server = state.server else { return }
        savingInstructions = true
        defer { savingInstructions = false }
        do {
            try await server.saveInstructions(instructions)
            savedInstructions = instructions
            note = "Instructions saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func delete(_ m: MemoryNote) async {
        guard let server = state.server else { return }
        do {
            try await server.deleteMemory(name: m.name)
            note = "Deleted \(m.name)"
            Haptics.success()
        } catch { note = error.localizedDescription }
        await load()
    }
}

struct MemoryEditor: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let original: MemoryNote?
    var onSaved: () async -> Void

    @State private var name = ""
    @State private var text = ""
    @State private var loading = false
    @State private var saving = false
    @State private var filled = false
    @State private var note: String?

    var body: some View {
        Form {
            Section {
                TextField("Name, e.g. lab-context", text: $name)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } footer: {
                Text("Letters, digits, - and _.")
            }
            Section("Memory") {
                if loading {
                    ProgressView()
                } else {
                    LibraryTextEditor(placeholder: "What should Orbit always know?", text: $text, minHeight: 200)
                }
            }
        }
        .navigationTitle(original?.name ?? "New memory")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }
                        .disabled(LibraryNames.safe(name).isEmpty || loading
                                  || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .task {
            guard !filled else { return }
            filled = true
            guard let o = original, let server = state.server else { return }
            name = o.name
            loading = true
            do { text = try await server.memoryText(name: o.name) }
            catch { note = error.localizedDescription }
            loading = false
        }
        .libraryNote($note)
    }

    private func save() async {
        guard let server = state.server else { return }
        saving = true
        defer { saving = false }
        do {
            let saved = try await server.saveMemory(name: LibraryNames.safe(name), text: text)
            if let o = original, o.name != saved {
                try await server.deleteMemory(name: o.name)
            }
            Haptics.success()
            await onSaved()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}

/// The base system prompt, whether instructions and memory go in, and the prompt
/// actually sent once they do.
struct SystemPromptView: View {
    @EnvironmentObject var state: AppState
    @State private var prompt = ""
    @State private var savedPrompt = ""
    @State private var useInstructions = false
    @State private var useMemory = false
    @State private var saved: (Bool, Bool) = (false, false)
    @State private var preview: String?
    @State private var loading = true
    @State private var busy = false
    @State private var note: String?

    private var dirty: Bool {
        prompt != savedPrompt || useInstructions != saved.0 || useMemory != saved.1
    }

    var body: some View {
        Form {
            Section {
                if loading { ProgressView() } else {
                    LibraryTextEditor(placeholder: "Blank uses Orbit's built-in prompt.",
                                      text: $prompt, minHeight: 200, monospaced: true)
                }
            } header: {
                Text("Base system prompt")
            } footer: {
                Text("What every Orbit chat is told first. A chat can add its own on top, "
                     + "from its Library options.")
            }
            Section {
                Toggle("Add standing instructions", isOn: $useInstructions)
                Toggle("Add memories", isOn: $useMemory)
                Button("Put back Orbit's default prompt") { Task { await loadDefault() } }
                    .disabled(busy)
            } footer: {
                Text("Putting back the default fills the box; nothing changes on the Mac until you save.")
            }
            Section {
                if let preview {
                    Text(preview)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Button("Show the prompt actually sent") { Task { await loadPreview() } }
                        .disabled(busy)
                }
            } header: {
                Text("As sent")
            } footer: {
                if preview != nil {
                    Text("As the Mac builds it now, with instructions and memory in place. Saved changes show after a refresh.")
                }
            }
        }
        .navigationTitle("System prompt")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if busy { ProgressView() } else {
                    Button("Save") { Task { await save() } }.disabled(!dirty || loading)
                }
            }
        }
        .task { await load() }
        .refreshable {
            await load()
            if preview != nil { await loadPreview() }
        }
        .libraryNote($note)
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            let s = try await server.systemPromptSettings()
            if !dirty || loading {
                prompt = s.prompt; useInstructions = s.useInstructions; useMemory = s.useMemory
            }
            savedPrompt = s.prompt; saved = (s.useInstructions, s.useMemory)
        } catch { note = error.localizedDescription }
        loading = false
    }

    private func loadDefault() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            prompt = try await server.defaultPrompt()
            note = "Default prompt filled in — save to use it"
        } catch { note = error.localizedDescription }
    }

    private func loadPreview() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do { preview = try await server.systemPreview() }
        catch { note = error.localizedDescription }
    }

    private func save() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            try await server.setSystemPromptSettings(["system_prompt": prompt,
                                                      "use_instructions": useInstructions,
                                                      "use_memory": useMemory])
            savedPrompt = prompt; saved = (useInstructions, useMemory)
            note = "Saved"
            Haptics.success()
            if preview != nil { preview = try? await server.systemPreview() }
        } catch { note = error.localizedDescription }
    }
}
