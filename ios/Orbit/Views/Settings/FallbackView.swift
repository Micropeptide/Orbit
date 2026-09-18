import SwiftUI

/// When a model keeps failing: carry on with another model instead of stopping,
/// and which ones to try, in order. Every change is saved as it is made.
struct FallbackView: View {
    @EnvironmentObject var state: AppState
    @State private var loaded = false
    @State private var enabled = true
    @State private var after = 3
    @State private var sameModel = true
    /// Carry on by itself once a plan's allowance resets. The Mac treats unset as on.
    @State private var resumeAfterLimit = true
    @State private var list: [String] = []
    @State private var adding = ""
    @State private var error: String?
    @State private var note: String?

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if loaded {
                Section {
                    Toggle("Fall back", isOn: Binding(get: { enabled },
                                                     set: { enabled = $0; save() }))
                    Stepper(value: Binding(get: { after }, set: { after = max(1, min(10, $0)); save() }),
                            in: 1...10) {
                        LabeledContent("After", value: "\(after) failed attempt\(after == 1 ? "" : "s")")
                    }
                    Toggle("Same model first", isOn: Binding(get: { sameModel },
                                                            set: { sameModel = $0; save() }))
                } footer: {
                    Text("Same model first tries that model from another provider before moving on "
                         + "(for example DeepSeek on OpenCode Zen when OpenCode Go is down). Claude Code "
                         + "and Codex retry on their own first.")
                }

                Section {
                    Toggle(isOn: Binding(get: { resumeAfterLimit },
                                         set: { resumeAfterLimit = $0; save() })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Plan limit reached")
                            Text("carry on by itself when the allowance resets")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                } footer: {
                    Text("When Claude's 5-hour or weekly limit, a ChatGPT limit or an OpenCode Go allowance "
                         + "stops an answer or a scheduled task, the chat continues a minute after the reset "
                         + "(read from the limit message or the account). It shows in Scheduled, where you "
                         + "can move or cancel it.")
                }

                Section {
                    if list.isEmpty {
                        Text("None — only the same model elsewhere").foregroundStyle(.secondary)
                    }
                    ForEach(Array(list.enumerated()), id: \.element) { i, id in
                        HStack {
                            Text("\(i + 1).").foregroundStyle(.secondary).monospacedDigit()
                            VStack(alignment: .leading, spacing: 1) {
                                Text(name(id))
                                if name(id) != id {
                                    Text(id).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                                }
                            }
                        }
                    }
                    .onMove { from, to in list.move(fromOffsets: from, toOffset: to); save() }
                    .onDelete { list.remove(atOffsets: $0); save() }

                    Picker("Add a model", selection: $adding) {
                        Text("Choose…").tag("")
                        ForEach(groups, id: \.0) { g, models in
                            Section(g) {
                                ForEach(models) { Text($0.display).tag($0.id) }
                            }
                        }
                    }
                    .pickerStyle(.navigationLink)
                    .onChange(of: adding) { _, v in
                        guard !v.isEmpty else { return }
                        if !list.contains(v) { list.append(v); save() }
                        adding = ""
                    }
                } header: {
                    HStack {
                        Text("Then, in order")
                        Spacer()
                        EditButton().font(.caption).textCase(nil)
                    }
                } footer: {
                    Text("Each chat stays in its own harness: a Claude Code chat uses the Claude Code "
                         + "version of a model, a Codex chat the Codex one, an Orbit chat Orbit's. The "
                         + "answer says when it moves; the chat keeps its own model for the next message.")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("When a model keeps failing")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
    }

    private var groups: [(String, [ModelInfo])] {
        let ready = state.models.filter { $0.isReady && !list.contains($0.id) }
        return Dictionary(grouping: ready, by: \.group).sorted { $0.key < $1.key }.map { ($0.key, $0.value) }
    }

    private func name(_ id: String) -> String {
        state.models.first { $0.id == id }?.display ?? id
    }

    private func load() async {
        do {
            let s = try await state.requireServer().settings()
            enabled = s["fallback_enabled"]?.bool ?? true
            after = s["fallback_after"]?.int ?? 3
            if after < 1 { after = 3 }
            sameModel = s["fallback_same_model"]?.bool ?? true
            resumeAfterLimit = s["resume_after_limit"]?.bool ?? true
            list = s["fallback_models"]?.strings ?? []
            loaded = true
            error = nil
            if state.models.isEmpty { await state.loadModels() }
        } catch { self.error = error.localizedDescription }
    }

    private func save() {
        let body: [String: Any] = ["fallback_enabled": enabled, "fallback_after": after,
                                   "fallback_same_model": sameModel, "fallback_models": list,
                                   "resume_after_limit": resumeAfterLimit]
        Task {
            do { try await state.requireServer().saveSettings(body); note = "saved" }
            catch { note = error.localizedDescription }
        }
    }
}
