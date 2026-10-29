import SwiftUI

/// Settings → Helpers: other agents (Claude Science, Claude Code, Codex, any app that speaks MCP) can
/// hand Orbit work to do on cheaper models, have it watch cluster jobs and hold a conversation with an
/// Orbit chat. What they send shows up in the inbox here, and anything that changes files waits for
/// your yes, which is the part worth having on a phone. Connecting an app (its token, the address,
/// installing its skill) stays on the Mac.
struct HelpersView: View {
    @EnvironmentObject var state: AppState
    @State private var status: HelperStatus?
    @State private var inbox: HelperInbox?
    @State private var error: String?
    @State private var note: String?
    @State private var expanded: Set<String> = []
    @State private var confirmEnd: HelperThread?
    @State private var confirmClear = false

    var body: some View {
        List {
            if let error { Section { ErrorRow(message: error) } }
            if let status {
                Section {
                    Toggle("Turn it on", isOn: Binding(get: { status.enabled }, set: { on in Task { await setEnabled(on) } }))
                } footer: {
                    Text(status.enabled
                         ? (status.running ? "Running on the Mac. It answers only there, and only with an app's own token."
                                           : "On, but not running. Look at Settings → Status on the Mac.")
                         : "Off. Apps cannot hand Orbit anything until it is on.")
                }
                if status.enabled {
                    if let inbox {
                        waitingSection(inbox)
                        threadsSection(inbox)
                        jobsSection(inbox)
                    } else { Section { LoadingRow() } }
                    appsSection(status)
                }
            } else if error == nil {
                Section { LoadingRow() }
            }
        }
        .navigationTitle("Helpers")
        .navigationBarTitleDisplayMode(.inline)
        .task { await keepCurrent() }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("End this conversation?", isPresented: Binding(
            get: { confirmEnd != nil }, set: { if !$0 { confirmEnd = nil } }),
            titleVisibility: .visible, presenting: confirmEnd) { t in
            Button("End it", role: .destructive) { Task { await act { try await $0.helperEnd(thread: t.id) } } }
            Button("Cancel", role: .cancel) {}
        } message: { _ in Text("The chat stays in Orbit, archived.") }
        .confirmationDialog("Clear finished jobs?", isPresented: $confirmClear, titleVisibility: .visible) {
            Button("Clear them", role: .destructive) { Task { await act { try await $0.helperForget() } } }
            Button("Cancel", role: .cancel) {}
        }
    }

    // ------------------------------------------------------------ inbox

    @ViewBuilder private func waitingSection(_ inbox: HelperInbox) -> some View {
        let waiting = inbox.jobs.filter { $0.state == "waiting" }
        if !waiting.isEmpty {
            Section {
                ForEach(waiting) { j in
                    VStack(alignment: .leading, spacing: 6) {
                        Text("\(j.app) wants a helper to change files" + (j.workdir.map { " in \($0)" } ?? ""))
                            .font(.callout.weight(.medium))
                        Text(j.task).font(.footnote).lineLimit(8)
                        HStack(spacing: 12) {
                            Button("Allow") { Task { await act { try await $0.helperDecide(job: j.id, approve: true) } } }
                                .buttonStyle(.borderedProminent)
                            Button("Don't allow", role: .destructive) {
                                Task { await act { try await $0.helperDecide(job: j.id, approve: false) } }
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    .padding(.vertical, 3)
                }
            } header: {
                Text("Waiting for your yes (\(waiting.count))").foregroundStyle(.red)
            }
        }
    }

    @ViewBuilder private func threadsSection(_ inbox: HelperInbox) -> some View {
        if !inbox.threads.isEmpty {
            Section("Conversations") {
                ForEach(inbox.threads) { t in
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(t.app) · \(t.name)").font(.callout.weight(.medium))
                        Text("\(t.role) · \(t.model) · \(t.rounds)/\(t.maxRounds) messages"
                             + (t.unread > 0 ? " · \(t.unread) unread" : ""))
                            .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 14) {
                            if let sid = t.sid { Button("Open the chat") { open(sid) } }
                            if t.rounds >= t.maxRounds {
                                Button("Allow 30 more") { Task { await act { try await $0.helperMoreRounds(thread: t.id) } } }
                            }
                            Button("End", role: .destructive) { confirmEnd = t }
                        }
                        .font(.caption).buttonStyle(.borderless)
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    @ViewBuilder private func jobsSection(_ inbox: HelperInbox) -> some View {
        let rest = inbox.jobs.filter { $0.state != "waiting" }
        Section {
            if rest.isEmpty {
                Text("Nothing yet. When an app hands Orbit work, it appears here.").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(rest.prefix(40)) { j in jobRow(j) }
            if !rest.isEmpty {
                Button("Clear finished", role: .destructive) { confirmClear = true }
            }
        } header: {
            Text("Jobs")
        } footer: {
            if !inbox.stats.isEmpty {
                let n = inbox.stats.reduce(0) { $0 + $1.jobs }, tok = inbox.stats.reduce(0) { $0 + $1.tokens }
                Text("Last 7 days: \(n) handled by Orbit's models, \(tok.formatted()) tokens (" +
                     inbox.stats.map { "\($0.model) \($0.jobs)" }.joined(separator: ", ") + ").")
            }
        }
    }

    private func jobRow(_ j: HelperJob) -> some View {
        let open = expanded.contains(j.id)
        return VStack(alignment: .leading, spacing: 5) {
            Button {
                if open { expanded.remove(j.id) } else { expanded.insert(j.id) }
            } label: {
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        ClusterStatePill(text: j.state, tint: tint(j.state))
                        Text(j.app).font(.callout.weight(.medium))
                        Spacer()
                        Image(systemName: open ? "chevron.up" : "chevron.down").font(.caption).foregroundStyle(.secondary)
                    }
                    Text(j.title).font(.footnote).foregroundStyle(Color.primary).lineLimit(open ? nil : 2)
                    Text([j.model, j.seconds.map { "\($0) s" }, j.tokens > 0 ? "\(j.tokens.formatted()) tokens" : nil,
                          j.confidence.isEmpty ? nil : "confidence \(j.confidence)"].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.plain)
            if open {
                if j.title != j.task { Text(j.task).font(.caption).foregroundStyle(.secondary) }
                if !j.answer.isEmpty { ClusterTextBlock(text: j.answer) }
                if !j.note.isEmpty { Text(j.note).font(.caption).foregroundStyle(.secondary) }
                HStack(spacing: 14) {
                    if j.state == "running" {
                        Button("Stop", role: .destructive) { Task { await act { try await $0.helperCancel(job: j.id) } } }
                    }
                    if let sid = j.sid { Button("Open the chat") { self.open(sid) } }
                }
                .font(.caption).buttonStyle(.borderless)
            }
        }
        .padding(.vertical, 2)
    }

    private func tint(_ state: String) -> Color {
        switch state {
        case "done": return .green
        case "running": return .accentColor
        case "failed", "denied": return .red
        default: return .secondary
        }
    }

    // ------------------------------------------------------------ apps

    private func appsSection(_ status: HelperStatus) -> some View {
        Section {
            ForEach(status.clients) { c in
                NavigationLink {
                    HelperAppView(client: c, canRemove: status.clients.count > 1) { s in self.status = s }
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(c.name).font(.callout.weight(.medium))
                        Text((c.lastSeen.map { "last heard \(ClusterFormat.ago($0, now: Date.now.timeIntervalSince1970))" }
                              ?? "not connected yet") + " · \(c.jobs) jobs")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Apps")
        } footer: {
            Text("Each app has its own limits and its own token. To connect a new app, add it on the Mac (Settings → Helpers): "
                 + "its token and address are not shown on the phone.")
        }
    }

    // ------------------------------------------------------------ I/O

    private func open(_ sid: String) {
        state.tab = "chats"
        state.deepLink = sid
    }

    private func load() async {
        guard let server = state.server else { return }
        do {
            let s = try await server.helperStatus()
            status = s
            inbox = s.enabled ? try await server.helperInbox() : nil
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    /// The inbox is current while this screen is on show: a request waiting for a yes should not need a pull.
    private func keepCurrent() async {
        while !Task.isCancelled {
            await load()
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }

    private func act(_ call: (OrbitServer) async throws -> Void) async {
        guard let server = state.server else { return }
        do {
            try await call(server)
            Haptics.success()
            await load()
        } catch { note = error.localizedDescription }
    }

    private func setEnabled(_ on: Bool) async {
        guard let server = state.server else { return }
        do { status = try await server.helperSetEnabled(on); await load() } catch { note = error.localizedDescription }
    }
}

/// One app's limits: when it must ask, whether to tell you, which folders its helpers may work in, how much it may do.
struct HelperAppView: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State var client: HelperClient
    let canRemove: Bool
    /// The status the Mac answers a change with.
    let onChange: (HelperStatus) -> Void
    @State private var folders = ""
    @State private var original: HelperClient?
    @State private var busy = false
    @State private var note: String?
    @State private var confirmRemove = false

    private var changed: Bool {
        guard let o = original else { return false }
        var c = client
        c.workdirs = folderList
        return c != o
    }

    private var folderList: [String] {
        folders.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    var body: some View {
        Form {
            Section("Name") { TextField("Name", text: $client.name) }
            Section {
                Picker("Changes", selection: $client.approval) {
                    Text("Ask before anything that changes files").tag("writes")
                    Text("Ask before every job").tag("all")
                    Text("Never ask (only in the folders below)").tag("none")
                }
                Picker("Orbit actions", selection: $client.actions) {
                    Text("Off: keep it out of my chats, Crew, shared projects and cluster models").tag("off")
                    Text("On: it may ask, and nothing happens until I say yes").tag("ask")
                }
                Picker("Tell me", selection: $client.notify) {
                    Text("When a long job finishes").tag("long")
                    Text("When every job finishes").tag("always")
                    Text("Never").tag("never")
                }
            }
            Section {
                TextEditor(text: $folders).font(.callout.monospaced()).frame(minHeight: 70)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
            } header: {
                Text("Folders")
            } footer: {
                Text("One per line: where its helpers may work.")
            }
            Section {
                limit("Running at once", $client.maxRunning)
                limit("Jobs a day", $client.maxPerDay)
                limit("Conversation messages a day", $client.maxThreadMessagesPerDay)
                Stepper(value: $client.threadRounds, in: 1...500) {
                    LabeledContent("Messages in one conversation", value: "\(client.threadRounds)")
                }
                TextField("Conversation model (empty: a standard one)", text: $client.threadModel)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
            } header: {
                Text("Limits")
            } footer: {
                Text("Past the messages in one conversation you are asked before it goes on.")
            }
            Section {
                Button(busy ? "Saving…" : "Save") { Task { await save() } }.disabled(!changed || busy)
                if canRemove {
                    Button("Remove this app", role: .destructive) { confirmRemove = true }
                }
            }
        }
        .navigationTitle(client.name)
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .task {
            if original == nil { original = client; folders = client.workdirs.joined(separator: "\n") }
        }
        .confirmationDialog("Remove \(client.name)?", isPresented: $confirmRemove, titleVisibility: .visible) {
            Button("Remove", role: .destructive) { Task { await remove() } }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Its token stops working. Its past jobs stay in the inbox.") }
    }

    /// 0 means no limit.
    private func limit(_ title: String, _ value: Binding<Int>) -> some View {
        VStack(alignment: .leading) {
            Toggle("\(title): no limit", isOn: Binding(get: { value.wrappedValue == 0 },
                                                       set: { value.wrappedValue = $0 ? 0 : 10 }))
            if value.wrappedValue != 0 {
                Stepper(value: value, in: 1...100_000) { LabeledContent(title, value: "\(value.wrappedValue)") }
            }
        }
    }

    private func save() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        client.workdirs = folderList
        do {
            onChange(try await server.helperSaveApp(client))
            original = client
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func remove() async {
        guard let server = state.server else { return }
        do { onChange(try await server.helperRemoveApp(id: client.id)); dismiss() } catch { note = error.localizedDescription }
    }
}
