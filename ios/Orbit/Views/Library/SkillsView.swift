import SwiftUI

/// Skills: saved procedures the model loads when a task calls for one.
struct SkillsView: View {
    @EnvironmentObject var state: AppState
    @State private var skills: [SkillInfo] = []
    @State private var loading = true
    @State private var note: String?
    @State private var confirmDelete: SkillInfo?

    var body: some View {
        List {
            if skills.isEmpty && !loading {
                ContentUnavailableView("No skills yet", systemImage: "list.bullet.clipboard",
                                       description: Text("A skill is a procedure written down once — "
                                                         + "Orbit follows it whenever the task needs it."))
            }
            ForEach(skills) { k in
                NavigationLink {
                    SkillEditor(original: k) { await load() }
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(k.name).font(.body.weight(.medium))
                        // a skill that opens with front matter has "---" for a title
                        if let t = k.title, !t.isEmpty, t.contains(where: { $0 != "-" }) {
                            Text(t).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                    }
                }
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) { confirmDelete = k } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
            }
        }
        .overlay { if loading && skills.isEmpty { ProgressView() } }
        .navigationTitle("Skills")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                NavigationLink {
                    SkillEditor(original: nil) { await load() }
                } label: { Image(systemName: "plus") }
                .accessibilityLabel("New skill")
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete the skill \(confirmDelete?.name ?? "")?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let k = confirmDelete { Task { await delete(k) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .libraryNote($note)
    }

    private func load() async {
        guard let server = state.server else { return }
        do { skills = try await server.skills() }
        catch { note = error.localizedDescription }
        loading = false
    }

    private func delete(_ k: SkillInfo) async {
        guard let server = state.server else { return }
        do {
            try await server.deleteSkill(name: k.name)
            note = "Deleted \(k.name)"
            Haptics.success()
        } catch { note = error.localizedDescription }
        await load()
    }
}

struct SkillEditor: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let original: SkillInfo?
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
                TextField("Name, e.g. wgbs-qc", text: $name)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            } footer: {
                Text("Letters, digits, - and _.")
            }
            Section("Procedure") {
                if loading {
                    ProgressView()
                } else {
                    LibraryTextEditor(placeholder: "# WGBS QC\n\n1. Check the conversion rate…",
                                      text: $text, minHeight: 260, monospaced: true)
                }
            }
        }
        .navigationTitle(original?.name ?? "New skill")
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
            do { text = try await server.skillText(name: o.name) }
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
            let saved = try await server.saveSkill(name: LibraryNames.safe(name), text: text)
            if let o = original, o.name != saved {
                try await server.deleteSkill(name: o.name)
            }
            Haptics.success()
            await onSaved()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}
