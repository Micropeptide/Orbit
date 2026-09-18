import SwiftUI

/// Saved prompts. Each becomes a slash command: `/review the methods` puts the
/// prompt in the message box with the words filled in.
struct PromptsView: View {
    @EnvironmentObject var state: AppState
    @State private var prompts: [SavedPrompt] = []
    @State private var loading = true
    @State private var note: String?
    @State private var confirmDelete: SavedPrompt?

    var body: some View {
        List {
            if prompts.isEmpty && !loading {
                ContentUnavailableView("No saved prompts", systemImage: "text.bubble",
                                       description: Text("Save a prompt you use often; type / and its name in any chat."))
            }
            ForEach(prompts) { p in
                NavigationLink {
                    PromptEditor(original: p) { await load() }
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text("/" + p.name).font(.body.monospaced().weight(.medium))
                            if p.builtin {
                                Text("built in").font(.caption2.weight(.semibold))
                                    .padding(.horizontal, 6).padding(.vertical, 1)
                                    .background(.quaternary, in: .capsule)
                            }
                        }
                        Text(p.desc.isEmpty ? String(p.text.prefix(90)) : p.desc)
                            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                .swipeActions(edge: .trailing) {
                    if !p.builtin {
                        Button(role: .destructive) { confirmDelete = p } label: {
                            Label("Delete", systemImage: "trash")
                        }
                    }
                }
            }
        }
        .overlay { if loading && prompts.isEmpty { ProgressView() } }
        .navigationTitle("Saved prompts")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                NavigationLink {
                    PromptEditor(original: nil) { await load() }
                } label: { Image(systemName: "plus") }
                .accessibilityLabel("New prompt")
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete /\(confirmDelete?.name ?? "")?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let p = confirmDelete { Task { await delete(p) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .libraryNote($note)
    }

    private func load() async {
        guard let server = state.server else { return }
        do { prompts = try await server.prompts() }
        catch { note = error.localizedDescription }
        loading = false
    }

    private func delete(_ p: SavedPrompt) async {
        guard let server = state.server else { return }
        do {
            try await server.deletePrompt(name: p.name)
            note = "Deleted /\(p.name)"
            Haptics.success()
            SlashCatalog.shared.invalidate()
        } catch { note = error.localizedDescription }
        await load()
    }
}

struct PromptEditor: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let original: SavedPrompt?
    var onSaved: () async -> Void

    @State private var name = ""
    @State private var desc = ""
    @State private var text = ""
    @State private var saving = false
    @State private var note: String?

    private var cleanName: String {
        var n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if n.hasPrefix("/") { n.removeFirst() }
        return n
    }

    var body: some View {
        Form {
            Section {
                HStack(spacing: 2) {
                    Text("/").foregroundStyle(.secondary)
                    TextField("review", text: $name)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                TextField("Description, e.g. critique a result", text: $desc)
            } header: {
                Text("Command")
            }
            Section {
                LibraryTextEditor(placeholder: "The prompt put in the message box when you type the command.",
                                  text: $text)
            } header: {
                Text("Prompt")
            } footer: {
                Text("$ARGUMENTS becomes the words after the command; $1, $2… each word, "
                     + "with \"quotes\" keeping a phrase together.")
            }
            if original?.builtin == true {
                Section {
                    Text("A built-in prompt. Saving keeps your version under the same name; "
                         + "delete yours later to get the built-in one back.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle(original == nil ? "New prompt" : "/" + (original?.name ?? ""))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }
                        .disabled(cleanName.isEmpty || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .onAppear {
            guard let o = original, name.isEmpty else { return }
            name = o.name; desc = o.desc; text = o.text
        }
        .libraryNote($note)
    }

    private func save() async {
        guard let server = state.server else { return }
        saving = true
        defer { saving = false }
        do {
            // renaming saves under the new name and removes the old one
            try await server.savePrompt(name: cleanName, desc: desc, text: text)
            if let o = original, o.name != cleanName, !o.builtin {
                try await server.deletePrompt(name: o.name)
            }
            Haptics.success()
            SlashCatalog.shared.invalidate()
            await onSaved()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}
