import SwiftUI

/// One model on a cluster GPU: what it is doing now, start / stop / restart, which chats use it, its
/// speed and load, and a way into its settings and schedule. Starting and stopping change a real job
/// on the cluster, so each asks first.
struct ClusterModelDetail: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterModelsStore
    let id: String
    @State private var pending: Action?
    @State private var busy: String?
    @State private var note: String?
    @State private var log: (name: String, text: String)?

    enum Action: String, Identifiable {
        case start, stop, restart
        var id: String { rawValue }
    }

    private var server: ModelServer? { store.server(id) }

    var body: some View {
        List {
            if let s = server {
                liveSection(s)
                actionSection(s)
                chatSection(s)
                if s.status.isReady { speedSection(s.status) }
                Section {
                    NavigationLink { ClusterModelSettingsView(store: store, id: id) } label: {
                        Label("Settings", systemImage: "slider.horizontal.3")
                    }
                    NavigationLink { ClusterModelScheduleView(store: store, id: id) } label: {
                        Label("Schedule and notices", systemImage: "calendar.badge.clock")
                    }
                } footer: {
                    Text("Settings are used the next time it starts.")
                }
                logSection(s)
            } else {
                Section { LoadingRow() }
            }
        }
        .navigationTitle(server?.label ?? "Cluster model")
        .navigationBarTitleDisplayMode(.inline)
        .task { await store.keepCurrent(state) }
        .settingsNote($note)
        .modifier(ToastOverlay())
        .confirmationDialog(title(pending), isPresented: Binding(
            get: { pending != nil }, set: { if !$0 { pending = nil } }),
            titleVisibility: .visible, presenting: pending) { a in
            Button(buttonTitle(a), role: a == .start ? nil : .destructive) { Task { await perform(a) } }
            Button("Cancel", role: .cancel) {}
        } message: { a in Text(message(a)) }
    }

    // ------------------------------------------------------------ now

    private func liveSection(_ s: ModelServer) -> some View {
        let st = s.status
        return Section {
            HStack {
                ClusterStatePill(server: st.state, label: st.stateLabel)
                Spacer()
                if busy != nil { ProgressView().controlSize(.small) }
            }
            if let line = stateNote(st) { Text(line).font(.footnote).foregroundStyle(.secondary) }
            if let e = st.error { Label(e, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.red) }
            if let e = st.mailError {
                Label("e-mail failed: \(e)", systemImage: "envelope.badge").font(.footnote).foregroundStyle(.red)
            }
            LabeledContent("Job", value: st.jid.map { "#\($0)" + (st.node.map { " on \($0)" } ?? "") } ?? "—")
            LabeledContent("Context length",
                           value: (st.contextLength ?? s.settings["max_model_len"]?.int).map { $0.formatted() + " tokens" } ?? "—")
            if let l = st.left, st.state == "ready" || st.state == "loading" {
                LabeledContent("Time left on the job",
                               value: ClusterFormat.duration(l) + (st.renewOn ? " · then renewed" : ""))
            }
            if let n = st.next {
                LabeledContent("Next on the schedule",
                               value: "\(n.kind) " + Date(timeIntervalSince1970: n.at).formatted(date: .abbreviated, time: .shortened))
            }
            if let p = st.placement { Text(p).font(.footnote).foregroundStyle(.secondary) }
            if st.isReady, let ok = st.healthOK {
                if ok, let sec = st.healthSeconds {
                    Text("Answers a test request in \(sec.formatted()) s.").font(.footnote).foregroundStyle(.secondary)
                } else if !ok {
                    Label("Up, but a one-word test failed \(st.healthFails ?? 1) time(s)\(st.healthError.map { " (\($0))" } ?? "").",
                          systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.orange)
                }
            }
        } header: {
            Text("Now")
        }
    }

    private func stateNote(_ st: ServerStatus) -> String? {
        let now = store.data?.now ?? Date.now.timeIntervalSince1970
        switch st.state {
        case "queued": return st.reason.map { "Waiting: \(ClusterFormat.shortReason($0))." } ?? "Waiting for a free GPU."
        case "loading":
            let since = st.submitted.map { "\(ClusterFormat.duration(now - $0)) since it was asked for; " } ?? ""
            return since + "loading takes about 5–10 minutes."
        case "ready": return st.ready.map { "Up for \(ClusterFormat.duration(now - $0))." }
        case "stopping": return "Cancelling the job…"
        default: return nil
        }
    }

    // ------------------------------------------------------------ actions

    private func actionSection(_ s: ModelServer) -> some View {
        let st = s.status
        return Section {
            Button { pending = .start } label: { Label("Start", systemImage: "play.fill") }
                .disabled(st.isBusy || busy != nil)
            Button { pending = .restart } label: { Label("Restart", systemImage: "arrow.clockwise") }
                .disabled(!st.isBusy || st.state == "stopping" || busy != nil)
            Button(role: .destructive) { pending = .stop } label: { Label("Stop", systemImage: "stop.fill") }
                .disabled(!st.isBusy || st.state == "stopping" || busy != nil)
        } footer: {
            Text("Start asks the cluster for a GPU; it is ready some minutes after it gets one. "
                 + "Restart cuts chats off for those minutes.")
        }
    }

    private func title(_ a: Action?) -> String {
        guard let a, let s = server else { return "" }
        switch a {
        case .start: return "Start \(s.label)?"
        case .stop: return "Stop \(s.label)?"
        case .restart: return "Restart \(s.label)?"
        }
    }

    private func buttonTitle(_ a: Action) -> String {
        switch a { case .start: return "Start"; case .stop: return "Stop it"; case .restart: return "Restart" }
    }

    private func message(_ a: Action) -> String {
        guard let s = server else { return "" }
        let st = s.settings
        switch a {
        case .start:
            let gpus = st["gpus"]?.int ?? 1
            return "This submits a job on the cluster asking for \(gpus) GPU\(gpus == 1 ? "" : "s"), "
                + "\(st["cpus"]?.int ?? 0) CPUs and \(st["mem_gb"]?.int ?? 0) GB of memory, for up to \(st["time_limit_h"]?.int ?? 24) hours."
        case .stop: return "Chats using it will stop getting answers."
        case .restart: return "Chats using it are cut off for the 5–10 minutes it takes to come back."
        }
    }

    private func perform(_ a: Action) async {
        guard let api = state.server else { return }
        busy = a.rawValue
        defer { busy = nil }
        do {
            store.data = try await api.modelServerAction(a.rawValue, id: id)
            note = a == .start ? "asked the cluster" : a == .stop ? "stopping" : "restarting"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    // ------------------------------------------------------------ chats

    private func chatSection(_ s: ModelServer) -> some View {
        let options = store.chatModels(for: s, in: state.models)
        let current = state.catalogueID(for: state.defaultModel)
        return Section {
            if options.isEmpty {
                Text(store.provider(for: s) == nil
                     ? "No Orbit provider reaches this server yet, so chats cannot use it. Add one in Models & keys."
                     : "No model of this server is set up for chats.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(options) { m in
                Button {
                    Task { await use(m) }
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 1) {
                            Text("New chats start in " + ClusterModelsStore.engineName(m))
                                .foregroundStyle(Color.primary)
                            Text(m.id).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        }
                        Spacer()
                        if m.id == current { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
                    }
                }
            }
        } header: {
            Text("Chats use it")
        } footer: {
            Text("Sets the model new chats start on. Each chat can still choose its own from the label above the message box.")
        }
    }

    private func use(_ m: ModelInfo) async {
        await state.setDefaultModel(m.id)
        note = "new chats start on " + m.display
        Haptics.success()
    }

    // ------------------------------------------------------------ speed and load

    private func speedSection(_ st: ServerStatus) -> some View {
        Section {
            if let x = st.stats {
                if x.off {
                    Text("This run has no statistics: it was started before they were switched on. Restart it to get them.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(x.rows, id: \.label) { r in LabeledContent(r.label, value: r.value).font(.callout) }
            } else {
                Text("Reading its statistics…").font(.footnote).foregroundStyle(.secondary)
            }
            if let b = st.bench {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Speed test, \(store.data.flatMap { d in b.at.map { ClusterFormat.ago($0, now: d.now ?? $0) } } ?? "")")
                        .font(.caption.weight(.semibold))
                    Text("Writes \(b.decodeTPS.map { $0.formatted() } ?? "?") tokens/s; reads a \(b.promptTokens?.formatted() ?? "?")-token prompt at \(b.prefillTPS.map { Int($0).formatted() } ?? "?") tokens/s (\(b.coldSeconds.map { $0.formatted() } ?? "?") s), and in \(b.warmSeconds.map { $0.formatted() } ?? "?") s when it has seen it before.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            Button {
                Task { await speedTest() }
            } label: {
                HStack {
                    Label("Run a speed test", systemImage: "speedometer")
                    if busy == "bench" { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(busy != nil)
        } header: {
            Text("Speed and load")
        } footer: {
            Text("From the model's own counters; no chat text is in them. The speed test sends three short requests (about 20 seconds).")
        }
    }

    private func speedTest() async {
        guard let api = state.server else { return }
        busy = "bench"
        defer { busy = nil }
        do { store.data = try await api.modelServerSpeedTest(id: id) } catch { note = error.localizedDescription }
    }

    // ------------------------------------------------------------ the server's own messages

    private func logSection(_ s: ModelServer) -> some View {
        Section {
            Button {
                Task { await readLog() }
            } label: {
                HStack {
                    Label(log == nil ? "Show server messages" : "Read again", systemImage: "text.alignleft")
                    if busy == "log" { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(busy != nil)
            if let log {
                if log.text.isEmpty {
                    Text("Nothing is kept yet. Start messages are kept from the next start (Settings → Server messages), unless the full log is on.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    Text(log.name).font(.caption).foregroundStyle(.secondary)
                    ClusterTextBlock(text: log.text)
                }
            }
        } header: {
            Text("Messages")
        } footer: {
            Text("The end of the newest log kept on the cluster, to see why a start failed. Folder: \(s.dir ?? "—")")
        }
    }

    private func readLog() async {
        guard let api = state.server else { return }
        busy = "log"
        defer { busy = nil }
        do { log = try await api.modelServerLog(id: id) } catch { note = error.localizedDescription }
    }
}
