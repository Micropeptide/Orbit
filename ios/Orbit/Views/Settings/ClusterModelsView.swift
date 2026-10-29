import SwiftUI

/// What the models-on-the-cluster screens share: the Mac's list of servers (read without touching
/// the cluster, so it can be kept current every few seconds) and which Orbit provider reaches each.
@MainActor
final class ClusterModelsStore: ObservableObject {
    @Published var data: ModelServers?
    @Published var error: String?
    /// Local port -> the Orbit provider that tunnels to it, from the Mac's model list.
    private var ports: [Int: String] = [:]
    private var portsRead = false

    func server(_ id: String) -> ModelServer? { data?.servers.first { $0.id == id } }

    func load(_ state: AppState) async {
        guard let server = state.server else { return }
        do {
            data = try await server.modelServers()
            error = nil
            if !portsRead {
                ports = (try? await server.clusterProviderPorts()) ?? [:]
                portsRead = true
            }
        } catch { self.error = error.localizedDescription }
    }

    /// Keeps the list current while a screen is on show.
    func keepCurrent(_ state: AppState, every seconds: UInt64 = 5) async {
        while !Task.isCancelled {
            await load(state)
            try? await Task.sleep(nanoseconds: seconds * 1_000_000_000)
        }
    }

    /// The Orbit provider that reaches this server, so its model can be chosen for chats.
    func provider(for s: ModelServer) -> String? {
        s.provider ?? s.port.flatMap { ports[$0] }
    }

    /// The ways chats can use this server's model, from the Mac's model list: Orbit's own chat,
    /// Claude Code, Codex. Empty if no model of that provider is set up.
    func chatModels(for s: ModelServer, in models: [ModelInfo]) -> [ModelInfo] {
        guard let p = provider(for: s) else { return [] }
        return models.filter { $0.isReady && (($0.provider == p && $0.model == s.model) || $0.model == "\(p)/\(s.model)") }
    }

    static func engineName(_ m: ModelInfo) -> String {
        if m.id.hasPrefix("harness-direct:") { return "Claude Code, direct" }
        if m.id.hasPrefix("harness:") { return "Claude Code" }
        if m.id.hasPrefix("codex:") { return "Codex" }
        return "Orbit"
    }
}

/// Settings → Cluster models: the models served from the cluster's GPUs. Whether each is ready,
/// loading or waiting for a GPU, and on which node; start, stop and restart; which of them chats
/// use; and whether a chat on one waits for it or moves to another model when it drops.
struct ClusterModelsView: View {
    @EnvironmentObject var state: AppState
    @StateObject private var store = ClusterModelsStore()
    @State private var note: String?
    @State private var confirmClose = false
    @State private var alsoChats = false

    var body: some View {
        List {
            if let e = store.error { Section { ErrorRow(message: e) } }
            if let data = store.data {
                serversSection(data)
                StayOnModelSection()
                loginsSection(data)
            } else if store.error == nil {
                Section { LoadingRow() }
            }
        }
        .navigationTitle("Cluster models")
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.keepCurrent(state) }
        .task { if state.models.isEmpty { await state.loadModels() } }
        .refreshable { await store.load(state) }
        .settingsNote($note)
        .confirmationDialog("Close Orbit's logins to the cluster?", isPresented: $confirmClose,
                            titleVisibility: .visible) {
            Button("Close them", role: .destructive) { Task { await closeLogins() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The next look opens a fresh one, and a model that is running keeps running."
                 + (alsoChats ? " Chats running on the cluster are cut off mid-answer." : ""))
        }
    }

    private func serversSection(_ data: ModelServers) -> some View {
        Section {
            ForEach(data.servers) { s in
                NavigationLink {
                    ClusterModelDetail(store: store, id: s.id)
                } label: { row(s, data) }
            }
        } header: {
            Text("Models")
        } footer: {
            Text("Each is a model Orbit starts as a job on a cluster GPU and reaches through a tunnel. "
                 + "Starting one submits a job; stopping cancels it.")
        }
    }

    private func row(_ s: ModelServer, _ data: ModelServers) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(s.label).font(.callout.weight(.medium)).lineLimit(1)
                Spacer()
                ClusterStatePill(server: s.status.state, label: s.status.stateLabel)
            }
            Text(summary(s, now: data.now)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
    }

    private func summary(_ s: ModelServer, now: Double?) -> String {
        let st = s.status
        var parts: [String] = []
        switch st.state {
        case "queued": parts.append(st.reason.map { "waiting: \(ClusterFormat.shortReason($0))" } ?? "waiting for a free GPU")
        case "loading":
            parts.append("loading, about 5–10 minutes")
            if let t = st.submitted, let now { parts.append("asked \(ClusterFormat.duration(now - t)) ago") }
        case "ready":
            if let t = st.ready, let now { parts.append("up for \(ClusterFormat.duration(now - t))") }
            if let l = st.left { parts.append("\(ClusterFormat.duration(l)) left on the job") }
        default: break
        }
        if let n = st.node { parts.append(n) }
        if let e = st.error { parts.append(e) }
        if let me = chatNote(s) { parts.append(me) }
        return parts.joined(separator: " · ")
    }

    /// "new chats start here" when this server's model is the default.
    private func chatNote(_ s: ModelServer) -> String? {
        let ids = Set(store.chatModels(for: s, in: state.models).map(\.id))
        guard let d = state.catalogueID(for: state.defaultModel), ids.contains(d) else { return nil }
        return "new chats start here"
    }

    private func loginsSection(_ data: ModelServers) -> some View {
        Section {
            if data.connections.isEmpty { Text("None open from this Mac.").font(.footnote).foregroundStyle(.secondary) }
            ForEach(data.connections) { c in
                LabeledContent {
                    Text("open " + c.age).font(.caption.monospacedDigit())
                } label: {
                    Text(c.what).font(.footnote).foregroundStyle(c.mine ? Color.primary : .secondary)
                }
            }
            if let first = data.servers.first {
                Toggle("Also the chats running there", isOn: $alsoChats)
                Button("Close Orbit's logins", role: .destructive) { confirmClose = true }
                    .disabled(first.id.isEmpty)
            }
        } header: {
            Text("Logins to the cluster")
        } footer: {
            Text("Orbit looks at the cluster through one shared login, so a status check is not a new login. "
                 + "Closing is safe; logins of other programs are listed but never touched.")
        }
    }

    private func closeLogins() async {
        guard let server = state.server, let id = store.data?.servers.first?.id else { return }
        do {
            let n = try await server.closeClusterLogins(id: id, chats: alsoChats)
            note = n > 0 ? "closed \(n)" : "nothing of Orbit's was open"
            await store.load(state)
        } catch { note = error.localizedDescription }
    }
}

/// "Stay on the model": when its connection drops, wait and ask again instead of moving to another
/// model. The same setting as Fallback, here because a model on a cluster GPU is the one that
/// disappears for ten minutes while it loads.
struct StayOnModelSection: View {
    @EnvironmentObject var state: AppState
    @State private var loaded = false
    @State private var stay = false
    @State private var hours = 12
    @State private var note: String?

    var body: some View {
        Section {
            Toggle("Stay on the model", isOn: Binding(get: { stay }, set: { stay = $0; save() }))
            if stay {
                Stepper(value: Binding(get: { hours }, set: { hours = max(1, min(168, $0)); save() }), in: 1...168) {
                    LabeledContent("Give up after", value: "\(hours) hour\(hours == 1 ? "" : "s")")
                }
            }
        } header: {
            Text("When a model drops")
        } footer: {
            Text(note ?? "On: a chat never switches to another model. It waits for this one to come back and asks "
                 + "again. Off: after repeated failures it moves on to the fallback models. A chat can still choose "
                 + "its own from the model sheet.")
        }
        .task { await load() }
    }

    private func load() async {
        guard !loaded, let s = try? await state.requireServer().settings() else { return }
        stay = s["no_fallback"]?.bool ?? false
        hours = max(1, s["hold_max_hours"]?.int ?? 12)
        loaded = true
    }

    private func save() {
        guard loaded else { return }
        Task {
            do {
                try await state.requireServer().saveSettings(["no_fallback": stay, "hold_max_hours": hours])
                note = "saved"
            } catch { note = error.localizedDescription }
        }
    }
}
