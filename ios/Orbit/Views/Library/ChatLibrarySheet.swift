import SwiftUI

/// One chat's Library options: which agent answers, the chat's own instructions,
/// and memories worth keeping from it.
struct ChatLibrarySheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let sid: String

    @State private var agents: [AgentPreset] = []
    @State private var active: String?
    @State private var instructions = ""
    @State private var savedInstructions = ""
    @State private var loading = true
    @State private var busy = false
    @State private var suggestions: [SuggestedMemory]?
    @State private var suggesting = false
    @State private var savedSuggestions: Set<String> = []
    @State private var note: String?

    /// Chats on Claude Code get their instructions and memory from Claude's files.
    private var isClaude: Bool { SlashCatalog.isClaudeChat(state) }

    var body: some View {
        NavigationStack {
            List {
                if loading {
                    HStack { Spacer(); ProgressView(); Spacer() }
                } else {
                    agentSection
                    instructionsSection
                    memorySection
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("Library for this chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
            }
            .task { await load() }
            .libraryNote($note)
        }
    }

    private var agentSection: some View {
        Section {
            agentRow(nil)
            ForEach(agents) { a in agentRow(a) }
            NavigationLink { AgentsView() } label: {
                Text("Edit agents").foregroundStyle(.secondary)
            }
        } header: {
            Text("Agent")
        } footer: {
            Text(isClaude ? "Agents shape Orbit's own chats; a Claude Code chat follows Claude's settings."
                          : "An agent adds its instructions and limits the tools this chat may use.")
        }
    }

    private func agentRow(_ a: AgentPreset?) -> some View {
        Button {
            Task { await select(a?.name) }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(a?.name ?? "No agent").foregroundStyle(.primary)
                    if let d = a?.desc, !d.isEmpty {
                        Text(d).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer()
                if active == a?.name {
                    Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
                }
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(busy)
    }

    @ViewBuilder private var instructionsSection: some View {
        Section {
            LibraryTextEditor(placeholder: "e.g. Answer in Chinese in this chat.",
                              text: $instructions, minHeight: 90)
            if instructions != savedInstructions {
                Button(instructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                       ? "Clear this chat's instructions" : "Save for this chat") {
                    Task { await saveInstructions() }
                }
                .disabled(busy)
            }
        } header: {
            Text("This chat's instructions")
        } footer: {
            Text("Added to the system prompt for this chat only.")
        }
    }

    @ViewBuilder private var memorySection: some View {
        Section {
            if isClaude {
                NavigationLink { ClaudeMemoryView(sid: sid) } label: {
                    Label("Claude Code memory", systemImage: "sparkles")
                }
            }
            if let suggestions {
                if suggestions.isEmpty {
                    Text("Nothing worth remembering from this chat.").foregroundStyle(.secondary)
                }
                ForEach(suggestions) { s in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(s.name).font(.subheadline.weight(.semibold))
                        Text(s.content).font(.callout).foregroundStyle(.secondary)
                        HStack {
                            if savedSuggestions.contains(s.id) {
                                Label("Saved", systemImage: "checkmark").font(.caption)
                                    .foregroundStyle(.green)
                            } else {
                                Button("Save") { Task { await keep(s) } }
                                    .buttonStyle(.bordered).controlSize(.small)
                                Button("Skip") { self.suggestions?.removeAll { $0.id == s.id } }
                                    .buttonStyle(.borderless).controlSize(.small)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            } else {
                Button {
                    Task { await suggest() }
                } label: {
                    HStack {
                        Label("Suggest memories from this chat", systemImage: "star")
                        if suggesting { Spacer(); ProgressView() }
                    }
                }
                .disabled(suggesting)
            }
            NavigationLink { MemoryView() } label: {
                Text("All of Orbit's memory").foregroundStyle(.secondary)
            }
        } header: {
            Text("Memory")
        } footer: {
            Text("Suggestions are read from this chat by the model, so they take a moment. "
                 + "Nothing is saved until you tap Save.")
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            agents = try await server.agents().agents
            if isClaude {
                let c = try await server.claudeMemory(sid: sid, cwd: nil)
                instructions = c.chat_instructions ?? ""
                active = try await server.chatLibraryState(sid: sid).agent
            } else {
                let st = try await server.chatLibraryState(sid: sid)
                active = st.agent
                instructions = st.sys_override ?? ""
            }
            savedInstructions = instructions
        } catch { note = error.localizedDescription }
        loading = false
    }

    private func select(_ name: String?) async {
        guard let server = state.server, name != active else { return }
        busy = true
        defer { busy = false }
        do {
            let tools = try await server.selectAgent(name, sid: sid)
            active = name
            note = name.map { "Agent: \($0) · \(tools.count) tools" } ?? "Agent cleared"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func saveInstructions() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            if isClaude {
                try await server.setClaudeChatInstructions(sid: sid, text: instructions)
            } else {
                try await server.setChatInstructions(instructions, sid: sid)
            }
            savedInstructions = instructions
            note = instructions.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "Chat instructions cleared" : "Chat instructions saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func suggest() async {
        guard let server = state.server else { return }
        suggesting = true
        defer { suggesting = false }
        do { suggestions = try await server.suggestMemories(sid: sid) }
        catch { note = error.localizedDescription }
    }

    private func keep(_ s: SuggestedMemory) async {
        guard let server = state.server else { return }
        do {
            try await server.saveMemory(name: s.name, text: s.content)
            savedSuggestions.insert(s.id)
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
