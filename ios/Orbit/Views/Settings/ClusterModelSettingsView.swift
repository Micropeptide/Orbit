import SwiftUI

/// A model server's settings: what it is served with and what its job asks of the cluster. They apply
/// the next time it starts; only the ones changed are sent.
struct ClusterModelSettingsView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterModelsStore
    let id: String
    @State private var draft: [String: JSONValue] = [:]
    @State private var name = ""
    @State private var loaded = false
    @State private var busy = false
    @State private var note: String?

    private var saved: ModelServer? { store.server(id) }

    private var changedSettings: [String: JSONValue] {
        draft.filter { saved?.settings[$0.key] != $0.value }
    }
    private var changed: Bool { !changedSettings.isEmpty || (loaded && name != saved?.label) }

    var body: some View {
        Form {
            if loaded {
                Section("Name") { TextField("Name", text: $name) }
                resources
                placementSection
                keep
                privacy
                tuning
                Section {
                    Button(busy ? "Saving…" : "Save") { Task { await save() } }.disabled(!changed || busy)
                } footer: {
                    Text("Used the next time it starts. Restart it to apply them to a running one.")
                }
            } else {
                LoadingRow()
            }
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .task { if !loaded, let s = saved { draft = s.settings; name = s.label; loaded = true } }
    }

    // ------------------------------------------------------------ sections

    private var resources: some View {
        Section {
            IntField(title: "GPUs", value: int("gpus", 1))
            IntField(title: "CPU cores", value: int("cpus", 16))
            IntField(title: "Memory", value: int("mem_gb", 128), suffix: "GB")
            IntField(title: "Job time limit", value: int("time_limit_h", 24), suffix: "h")
            IntField(title: "Context length", value: int("max_model_len", 262_144), suffix: "tokens")
            IntField(title: "Requests at once", value: int("max_num_seqs", 32))
        } header: {
            Text("What it asks for")
        } footer: {
            Text("The job ends by itself after the time limit. A longer context needs more GPU memory and leaves "
                 + "room for fewer parallel requests.")
        }
    }

    private var placementSection: some View {
        Section {
            Picker("Where it runs", selection: string("placement", "auto")) {
                Text("Automatic").tag("auto")
                Text("Ask a model to choose").tag("ask")
                Text("Fixed").tag("fixed")
            }
            if draft["placement"]?.string == "ask" {
                TextField("Model for 'ask' (empty: helper model)", text: string("placement_model", ""))
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
            }
            IntField(title: "GPU memory it needs", value: int("min_vram_gb", 60), suffix: "GB")
            IntField(title: "Least host memory", value: int("min_mem_gb", 48), suffix: "GB")
            TextField("Partition (empty: the cluster's default)", text: string("partition", ""))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            TextField("Avoid nodes, e.g. g33, g34", text: string("exclude_nodes", ""))
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            IntField(title: "Move off a stuck node after", value: int("load_timeout_min", 25), suffix: "min")
        } header: {
            Text("Where it runs")
        } footer: {
            Text("Automatic asks the scheduler where each choice would start and takes the soonest; nothing is "
                 + "submitted for the estimates. Only nodes whose GPUs have the memory set here are used (0: no limit). "
                 + "Fixed uses exactly the partition set here. A node that did not finish loading is avoided for 6 hours by itself.")
        }
    }

    private var keep: some View {
        Section {
            Toggle("Keep it running", isOn: bool("keep_alive"))
            IntField(title: "Stop when idle for", value: int("idle_stop_min", 0), suffix: "min")
            Toggle("Renew after the time limit", isOn: bool("renew"))
        } header: {
            Text("Keeping it up")
        } footer: {
            Text("Keep it running starts it again if it fails or stops answering, at most twice a day and never after "
                 + "you stopped it. Idle stop frees the GPU after that long without a request (0: never). Renew starts "
                 + "it again when its time limit ends it, until you switch this off.")
        }
    }

    private var privacy: some View {
        Section {
            Picker("Logs on the cluster", selection: bool("keep_log")) {
                Text("Private: keep nothing").tag(false)
                Text("Keep the server and request log").tag(true)
            }
            Toggle("Keep server messages", isOn: bool("error_log"))
        } header: {
            Text("Privacy")
        } footer: {
            Text("A kept log has the text of your chats, in a folder only your cluster account can read; logs older than "
                 + "14 days are deleted. Server messages are the model's own start-up messages only. They stop the moment "
                 + "it answers, before any chat reaches it, so no chat text can be in them.")
        }
    }

    private var tuning: some View {
        Section {
            Toggle("Quick start", isOn: bool("eager"))
            Picker("Context memory", selection: string("kv_cache_dtype", "auto")) {
                Text("Normal").tag("auto")
                Text("Half size (fp8)").tag("fp8")
            }
            Stepper(value: double("gpu_mem_util", 0.9), in: 0.3...0.98, step: 0.01) {
                LabeledContent("GPU memory share", value: String(format: "%.2f", draft["gpu_mem_util"]?.double ?? 0.9))
            }
            Stepper(value: Binding(get: { Double(int("mtp_tokens", 2).wrappedValue) },
                                   set: { int("mtp_tokens", 2).wrappedValue = Int($0) }), in: 0...8) {
                LabeledContent("Speculative tokens", value: "\(draft["mtp_tokens"]?.int ?? 2)")
            }
            IntField(title: "Prompt reading", value: int("batched_tokens", 16384), suffix: "tokens")
            Toggle("Async scheduling", isOn: bool("async_scheduling"))
            Stepper(value: double("temperature", 0.6), in: 0...2, step: 0.05) {
                LabeledContent("Temperature", value: String(format: "%.2f", draft["temperature"]?.double ?? 0.6))
            }
            Stepper(value: double("top_p", 0.95), in: 0.05...1, step: 0.05) {
                LabeledContent("Top-p", value: String(format: "%.2f", draft["top_p"]?.double ?? 0.95))
            }
            IntField(title: "Top-k", value: int("top_k", 20))
        } header: {
            Text("Speed tuning")
        } footer: {
            Text("Quick start skips compiling: it starts in about 2 minutes instead of 8–10 and answers more slowly, for testing. "
                 + "Half-size context memory has room for twice the context, a little less exact. Speculative tokens are the "
                 + "model's own look-ahead (0 turns it off; 1–3 is usually faster). Sampling applies to requests that do not set it.")
        }
    }

    // ------------------------------------------------------------ bindings

    private func int(_ key: String, _ def: Int) -> Binding<Int> {
        Binding(get: { draft[key]?.int ?? def }, set: { draft[key] = .number(Double($0)) })
    }

    private func double(_ key: String, _ def: Double) -> Binding<Double> {
        Binding(get: { draft[key]?.double ?? def }, set: { draft[key] = .number(($0 * 100).rounded() / 100) })
    }

    private func bool(_ key: String) -> Binding<Bool> {
        Binding(get: { draft[key]?.bool ?? false }, set: { draft[key] = .bool($0) })
    }

    private func string(_ key: String, _ def: String) -> Binding<String> {
        Binding(get: { draft[key]?.string ?? def }, set: { draft[key] = .string($0) })
    }

    private func save() async {
        guard let api = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            let settings = changedSettings.mapValues(\.foundation)
            store.data = try await api.saveModelServer(
                id: id, label: name != saved?.label ? name : nil, settings: settings.isEmpty ? nil : settings)
            if let s = store.server(id) { draft = s.settings; name = s.label }
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
