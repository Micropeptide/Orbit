import SwiftUI

/// What you may use and how busy the queue is: your account's limits and fair-share, the partition
/// jobs run on, every partition's idle CPUs, and the login node with your processes on it.
struct ClusterLimitsView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterStore
    @State private var processes: [ClusterProcess]?
    @State private var loadingProcesses = false
    @State private var stopping: ClusterProcess?
    @State private var note: String?

    private var snap: ClusterSnapshot? { store.snapshot }
    private var account: ClusterAccount? { snap?.account }

    var body: some View {
        List {
            accountSection
            if let host = snap?.host { loginSection(host) }
            if let parts = snap?.partitions, !parts.isEmpty { partitionsSection(parts) }
        }
        .navigationTitle("Limits and the queue")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .confirmationDialog("Stop process \(stopping.map { String($0.pid) } ?? "")?", isPresented: Binding(
            get: { stopping != nil }, set: { if !$0 { stopping = nil } }),
            titleVisibility: .visible, presenting: stopping) { p in
            Button("Stop it", role: .destructive) { Task { await stop(p) } }
            Button("Keep it", role: .cancel) {}
        } message: { p in Text(p.cmd) }
    }

    @ViewBuilder private var accountSection: some View {
        Section {
            if let a = account {
                LabeledContent("Account", value: a.account ?? "—")
                if let f = a.fairshare { LabeledContent("Fair-share", value: String(format: "%.2f", f)) }
                if let lim = a.runningJobLimit {
                    LabeledContent("Running jobs", value: "\(snap?.running.count ?? 0) of \(lim)")
                }
                if let lim = a.gpuLimit { LabeledContent("GPUs in use", value: "\(snap?.gpusInUse ?? 0) of \(lim)") }
                if let lim = a.cpuLimit { LabeledContent("CPUs you may use", value: "\(lim)") }
                if let p = a.partitionName {
                    LabeledContent("Jobs run on", value: p)
                    if let idle = a.idleCPUs, let total = a.partitionCPUs {
                        LabeledContent("Idle CPUs there", value: "\(idle.formatted()) of \(total.formatted())")
                    }
                    if let t = a.maxTime { LabeledContent("Longest job", value: t) }
                }
            } else {
                Text(store.look == nil ? "Nothing read yet." : "The last look had no account readings.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        } header: {
            Text("Your account")
        } footer: {
            Text("A higher fair-share starts your jobs sooner. The limits are what the cluster lets one person use at once.")
        }
    }

    private func loginSection(_ h: ClusterHost) -> some View {
        Section {
            if let p = h.processes, let lim = h.processLimit, lim > 0 {
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(p) of your processes, of \(lim) allowed here").font(.callout)
                    ClusterBar(pct: Int((100.0 * Double(p) / Double(lim)).rounded()))
                }
            }
            if let l = h.load { LabeledContent("Load", value: l) }
            Button {
                Task { await loadProcesses() }
            } label: {
                HStack {
                    Label(processes == nil ? "Show my processes" : "Read again", systemImage: "list.bullet")
                    if loadingProcesses { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(loadingProcesses || state.server == nil)
            if let processes {
                if processes.isEmpty { Text("None.").font(.footnote).foregroundStyle(.secondary) }
                ForEach(processes) { p in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(p.cmd).font(.caption.monospaced()).lineLimit(3)
                        HStack {
                            Text("pid \(p.pid) · \(ClusterFormat.duration(p.age))")
                                .font(.caption2).foregroundStyle(.secondary)
                            Spacer()
                            if p.system {
                                Text("keeps your login").font(.caption2).foregroundStyle(.secondary)
                            } else {
                                Button("Stop") { stopping = p }
                                    .font(.caption).buttonStyle(.borderless).foregroundStyle(.red)
                            }
                        }
                    }
                }
            }
        } header: {
            Text("Login node" + (h.node.map { " — \($0)" } ?? ""))
        } footer: {
            Text("A login node with too many of your processes cannot start a new shell. Each read connects to the cluster.")
        }
    }

    private func partitionsSection(_ parts: [ClusterPartition]) -> some View {
        Section {
            ForEach(parts) { p in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.name).font(.callout.weight(.medium))
                        Text([p.up ? nil : "down", p.maxTime.map { "up to \($0)" }].compactMap { $0 }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let idle = p.cpusIdle, let total = p.cpusTotal {
                        Text("\(idle.formatted()) of \(total.formatted()) idle")
                            .font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Partitions")
        }
    }

    private func loadProcesses() async {
        guard let server = state.server else { return }
        loadingProcesses = true
        defer { loadingProcesses = false }
        do { processes = try await server.clusterProcesses() } catch { note = error.localizedDescription }
    }

    private func stop(_ p: ClusterProcess) async {
        guard let server = state.server else { return }
        do { processes = try await server.clusterStopProcess(pid: p.pid) } catch { note = error.localizedDescription }
    }
}
