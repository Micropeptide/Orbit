import SwiftUI

/// Agent presets: standing instructions plus a restricted tool set. A chat
/// picks one from its menu.
struct AgentsView: View {
    @EnvironmentObject var state: AppState
    @State private var agents: [AgentPreset] = []
    @State private var loading = true
    @State private var note: String?
    @State private var confirmDelete: AgentPreset?

    var body: some View {
        List {
            if agents.isEmpty && !loading {
                ContentUnavailableView("No agents yet", systemImage: "person.crop.rectangle.stack",
                                       description: Text("An agent is a set of instructions and the tools it may use. "
                                                         + "Pick one for a chat from the chat's menu."))
            }
            ForEach(agents) { a in
                NavigationLink {
                    AgentEditor(original: a) { await load() }
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(a.name).font(.body.weight(.medium))
                        Text([a.desc, toolsText(a)].filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) { confirmDelete = a } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
            }
        }
        .overlay { if loading && agents.isEmpty { ProgressView() } }
        .navigationTitle("Agents")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                NavigationLink {
                    AgentEditor(original: nil) { await load() }
                } label: { Image(systemName: "plus") }
                .accessibilityLabel("New agent")
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog("Delete the agent \(confirmDelete?.name ?? "")?",
                            isPresented: Binding(get: { confirmDelete != nil },
                                                 set: { if !$0 { confirmDelete = nil } }),
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) {
                if let a = confirmDelete { Task { await delete(a) } }
            }
            Button("Cancel", role: .cancel) {}
        }
        .libraryNote($note)
    }

    private func toolsText(_ a: AgentPreset) -> String {
        let n = a.tools?.count ?? 0
        return n == 0 ? "all tools" : "\(n) tool\(n == 1 ? "" : "s")"
    }

    private func load() async {
        guard let server = state.server else { return }
        do { agents = try await server.agents().agents }
        catch { note = error.localizedDescription }
        loading = false
    }

    private func delete(_ a: AgentPreset) async {
        guard let server = state.server else { return }
        do {
            try await server.deleteAgent(name: a.name)
            note = "Deleted \(a.name)"
            Haptics.success()
        } catch { note = error.localizedDescription }
        await load()
    }
}

struct AgentEditor: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let original: AgentPreset?
    var onSaved: () async -> Void

    @State private var name = ""
    @State private var desc = ""
    @State private var instructions = ""
    @State private var tools: Set<String> = []
    @State private var allTools: [String] = []
    @State private var toolFilter = ""
    @State private var saving = false
    @State private var note: String?
    @State private var filled = false

    private var shownTools: [String] {
        let q = toolFilter.trimmingCharacters(in: .whitespaces).lowercased()
        // chosen tools the Mac no longer has still show, so they can be unticked
        let all = Array(Set(allTools).union(tools)).sorted()
        return q.isEmpty ? all : all.filter { $0.lowercased().contains(q) }
    }

    var body: some View {
        Form {
            Section {
                TextField("Name, e.g. paper-reviewer", text: $name)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Description, e.g. critiques methods and stats", text: $desc)
            }
            Section("Instructions") {
                LibraryTextEditor(placeholder: "Instructions this agent always follows.",
                                  text: $instructions, minHeight: 140)
            }
            Section {
                if allTools.isEmpty {
                    HStack { ProgressView().controlSize(.small); Text("Loading tools").foregroundStyle(.secondary) }
                } else {
                    TextField("Filter tools", text: $toolFilter)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    ForEach(shownTools, id: \.self) { t in
                        Button {
                            if tools.contains(t) { tools.remove(t) } else { tools.insert(t) }
                        } label: {
                            HStack {
                                Text(t).font(.callout.monospaced()).foregroundStyle(.primary)
                                Spacer()
                                if tools.contains(t) {
                                    Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
                                }
                            }
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                    }
                }
            } header: {
                HStack {
                    Text("Tools it may use")
                    Spacer()
                    if !tools.isEmpty {
                        Button("Clear") { tools = [] }.font(.caption)
                    }
                }
            } footer: {
                Text(tools.isEmpty ? "None ticked: it may use every tool."
                                   : "\(tools.count) ticked: it may use only these.")
            }
        }
        .navigationTitle(original?.name ?? "New agent")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if saving { ProgressView() } else {
                    Button("Save") { Task { await save() } }
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .task {
            if !filled, let o = original {
                name = o.name; desc = o.desc; instructions = o.instructions
                tools = Set(o.tools ?? [])
            }
            filled = true
            if allTools.isEmpty, let server = state.server {
                do { allTools = try await server.allTools() }
                catch { note = error.localizedDescription }
            }
        }
        .libraryNote($note)
    }

    private func save() async {
        guard let server = state.server else { return }
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        saving = true
        defer { saving = false }
        do {
            try await server.saveAgent(name: clean, desc: desc, instructions: instructions,
                                       tools: tools.sorted())
            if let o = original, o.name != clean {
                try await server.deleteAgent(name: o.name)
            }
            Haptics.success()
            await onSaved()
            dismiss()
        } catch { note = error.localizedDescription }
    }
}
