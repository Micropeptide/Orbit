import SwiftUI

/// One thing the cluster can tell about a job: its output, why it waits, what went wrong,
/// how much of what it asked for it used. Each answer is one read over SSH, made when asked.
private struct JobQuestion: View {
    @EnvironmentObject var state: AppState
    let title: String
    let icon: String
    var footer: String?
    /// Reads the answer from the cluster.
    let ask: (OrbitServer) async throws -> String
    @State private var text: String?
    @State private var busy = false
    @State private var failed: String?

    var body: some View {
        Section {
            Button {
                Task { await run() }
            } label: {
                HStack {
                    Label(text == nil ? title : "\(title) — read again", systemImage: icon)
                    if busy { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(busy || state.server == nil)
            if let failed { ErrorRow(message: failed) }
            if let text { ClusterTextBlock(text: text, empty: "(the cluster had nothing to say)") }
        } footer: {
            if let footer { Text(footer) }
        }
    }

    private func run() async {
        guard let server = state.server else { return }
        busy = true
        defer { busy = false }
        do {
            text = try await ask(server)
            failed = nil
        } catch { failed = error.localizedDescription }
    }
}

/// A job in the queue: how it is running or what it waits for, and the questions to ask the cluster about it.
struct ClusterJobDetail: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let job: ClusterJobFull
    let isServer: Bool
    /// The fresh look a cancel answers with.
    let onChange: (ClusterLook) -> Void
    @State private var confirmCancel = false
    @State private var note: String?
    @State private var copying = false

    var body: some View {
        List {
            Section {
                LabeledContent("Job", value: "#\(job.id)")
                LabeledContent("State", value: job.stateLabel)
                if let n = job.node { LabeledContent("Node", value: n) }
                if let p = job.partition { LabeledContent("Partition", value: p) }
                if job.isRunning {
                    LabeledContent("Running for", value: ClusterFormat.duration(job.elapsed))
                    LabeledContent("Time left", value: ClusterFormat.duration(job.left))
                } else if let e = job.startEstimate {
                    LabeledContent("Expected start", value: ClusterFormat.shortTime(e))
                }
                if let g = job.gpus, g > 0 { LabeledContent("GPUs", value: "\(g)") }
                LabeledContent("CPUs · memory", value: "\(job.cpus ?? 0) · \(job.mem ?? "?")")
                if let r = job.reason {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Waiting on").font(.caption).foregroundStyle(.secondary)
                        Text(r).font(.footnote.monospaced()).textSelection(.enabled)
                    }
                }
            } footer: {
                if isServer { Text("This is a model server. Start and stop it in Cluster models.") }
            }

            if job.isPending {
                JobQuestion(title: "Why is it waiting?", icon: "questionmark.circle",
                            footer: "The cluster's own explanation (h2 why-pending).") { server in
                    try await server.clusterExplain(id: job.id, kind: "why")
                }
            } else {
                JobQuestion(title: "Its output", icon: "doc.text.magnifyingglass",
                            footer: "The last lines of the job's output file.") { server in
                    try await server.clusterOutput(id: job.id)
                }
            }
            JobQuestion(title: "How much it uses", icon: "gauge.with.needle") { server in
                try await server.clusterEfficiency(id: job.id).summary
            }

            Section {
                Button {
                    Task { await copyForChat() }
                } label: {
                    HStack {
                        Label("Copy for a chat", systemImage: "doc.on.doc")
                        if copying { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(copying)
            } footer: {
                Text("The job's record, the cluster's diagnosis and the end of its output, ready to paste into a chat.")
            }

            Section {
                Button(role: .destructive) { confirmCancel = true } label: {
                    Label("Cancel this job", systemImage: "xmark.circle")
                }
            }
        }
        .navigationTitle(job.name)
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .modifier(ToastOverlay())
        .confirmationDialog("Cancel \(job.name)?", isPresented: $confirmCancel, titleVisibility: .visible) {
            Button("Cancel job", role: .destructive) { Task { await cancel() } }
            Button("Keep it", role: .cancel) {}
        } message: {
            Text(isServer ? "This is a model server. Chats using it stop getting answers." : "It stops now and cannot be resumed.")
        }
    }

    private func cancel() async {
        guard let server = state.server else { return }
        do {
            onChange(try await server.clusterCancelJob(id: job.id))
            dismiss()
        } catch { note = error.localizedDescription }
    }

    private func copyForChat() async {
        guard let server = state.server else { return }
        copying = true
        defer { copying = false }
        do {
            UIPasteboard.general.string = try await server.clusterAskText(id: job.id)
            note = "Copied — paste it into a chat"
        } catch { note = error.localizedDescription }
    }
}

/// A job from the last days: how it ended, with the cluster's diagnosis when it went wrong.
struct ClusterRecentDetail: View {
    let job: ClusterRecentJob

    var body: some View {
        List {
            Section {
                LabeledContent("Job", value: "#\(job.id)")
                LabeledContent("Result", value: job.stateLabel)
                LabeledContent("Ran for", value: ClusterFormat.duration(job.elapsed))
                if let e = job.exit { LabeledContent("Exit code", value: e) }
                if let s = job.start { LabeledContent("Started", value: ClusterFormat.shortTime(s)) }
                if let n = job.node { LabeledContent("Node", value: n) }
                if let p = job.partition { LabeledContent("Partition", value: p) }
                if let g = job.gpus, g > 0 { LabeledContent("GPUs", value: "\(g)") }
            }
            if job.wentWrong {
                JobQuestion(title: "What went wrong", icon: "stethoscope",
                            footer: "The cluster's own diagnosis (h2 diagnose).") { server in
                    try await server.clusterExplain(id: job.id, kind: "diagnose")
                }
            }
            JobQuestion(title: "How much it used", icon: "gauge.with.needle") { server in
                try await server.clusterEfficiency(id: job.id).summary
            }
            JobQuestion(title: "Its output", icon: "doc.text.magnifyingglass",
                        footer: "Only while the scheduler still remembers the job.") { server in
                try await server.clusterOutput(id: job.id)
            }
        }
        .navigationTitle(job.name)
        .navigationBarTitleDisplayMode(.inline)
        .modifier(ToastOverlay())
    }
}
