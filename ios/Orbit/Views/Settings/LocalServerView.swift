import SwiftUI

/// Settings → Local server: how the model server on the Mac runs. None of it
/// applies until the server restarts, so saving offers to restart it too —
/// the web page's "Save & restart server".
struct LocalServerView: View {
    @EnvironmentObject var state: AppState
    /// The Mac's whole `server` block, so fields this screen does not show are
    /// posted back unchanged.
    @State private var saved: [String: JSONValue] = [:]
    @State private var server: [String: JSONValue] = [:]
    @State private var idleMin = 20
    @State private var savedIdle = 20
    @State private var loaded = false
    @State private var error: String?
    @State private var note: String?
    @State private var busy = false
    @State private var confirmRestart = false

    private var changed: Bool { server != saved || idleMin != savedIdle }

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            if loaded {
                Section {
                    IntField(title: "Context window", value: int("context_window", 131072), suffix: "tokens")
                    Picker("KV quantization", selection: string("kv_quant", "off")) {
                        ForEach(["off", "q8", "q4"], id: \.self) { Text($0).tag($0) }
                    }
                } footer: {
                    Text("Bigger allows longer chats; KV cache grows with it. q8 halves KV memory at "
                         + "near-zero quality cost.")
                }

                Section {
                    Picker("Fan mode", selection: string("fan_mode", "default")) {
                        ForEach(["default", "smart", "max"], id: \.self) { Text($0).tag($0) }
                    }
                    Toggle("Thermal polling", isOn: Binding(
                        get: { server["thermal_poll"]?.bool ?? false },
                        set: { server["thermal_poll"] = .bool($0) }))
                    Stepper(value: Binding(get: { server["depth"]?.int ?? 1 },
                                           set: { server["depth"] = .number(Double(max(1, min(3, $0)))) }),
                            in: 1...3) {
                        LabeledContent("Draft depth (MTP)", value: "\(server["depth"]?.int ?? 1)")
                    }
                    IntField(title: "Prefill chunk tokens", value: int("prefill_chunk_tokens", 2048))
                } footer: {
                    Text("Prefill chunk: lower means a smaller memory spike on long prompts.")
                }

                Section {
                    Picker("Server reasoning default", selection: string("reasoning", "auto")) {
                        ForEach(["off", "auto", "on"], id: \.self) { Text($0).tag($0) }
                    }
                    Picker("Scheduler", selection: string("scheduler_mode", "serial")) {
                        ForEach(["serial", "cooperative"], id: \.self) { Text($0).tag($0) }
                    }
                    IntField(title: "Idle shutdown", value: $idleMin, suffix: "min")
                } footer: {
                    Text("Reasoning default is for clients that don't ask (OpenCode); Orbit always asks "
                         + "explicitly. Idle shutdown: the watchdog stops the server after this long with no "
                         + "activity. 0 disables.")
                }

                Section {
                    Button("Save") { Task { await save(restart: false) } }
                        .disabled(!changed || busy)
                    Button("Save & restart server") { confirmRestart = true }
                        .disabled(busy)
                } footer: {
                    Text("These need a restart of the model server on the Mac. A restart reloads the "
                         + "weights, which takes a few seconds; an answer running on the local model stops.")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Local server")
        .navigationBarTitleDisplayMode(.inline)
        .task { if !loaded { await load() } }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Restart the model server?", isPresented: $confirmRestart, titleVisibility: .visible) {
            Button("Save & restart") { Task { await save(restart: true) } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The local model reloads with these settings. Anything it is answering right now stops.")
        }
    }

    // MARK: bindings

    private func string(_ key: String, _ def: String) -> Binding<String> {
        Binding(get: { server[key]?.string ?? def }, set: { server[key] = .string($0) })
    }

    private func int(_ key: String, _ def: Int) -> Binding<Int> {
        Binding(get: { server[key]?.int ?? def }, set: { server[key] = .number(Double(max(0, $0))) })
    }

    // MARK: I/O

    private func load() async {
        do {
            let s = try await state.requireServer().settings()
            saved = s["server"]?.object ?? [:]
            server = saved
            savedIdle = s["idle_min"]?.int ?? 20
            idleMin = savedIdle
            loaded = true
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func save(restart: Bool) async {
        busy = true
        defer { busy = false }
        do {
            let s = try state.requireServer()
            if changed {
                let r = try await s.saveSettings(["server": server.mapValues(\.foundation),
                                                  "idle_min": max(0, idleMin)])
                saved = r.settings["server"]?.object ?? server
                server = saved
                savedIdle = r.settings["idle_min"]?.int ?? idleMin
                idleMin = savedIdle
            }
            if restart {
                note = "restarting the model server…"
                note = try await s.serverAction(.restart)
                await state.refreshServer()
            } else {
                note = "saved — restart the server to apply"
            }
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
