import SwiftUI

/// The cluster's GPUs: which kinds exist, how many are free, node by node, and where a job asking for
/// so much would start now. All of it is from the last look; nothing here connects to the cluster
/// except the Refresh on the main screen.
struct ClusterGPUsView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterStore
    @State private var gpus = 1
    @State private var memGB = 32
    @State private var cpus = 8
    @State private var model = ""
    @State private var fit: ClusterFit?
    @State private var checking = false
    @State private var note: String?

    private var g: ClusterGpus? { store.snapshot?.gpus }
    private var limit: Int? { store.snapshot?.account?.gpuLimit }

    var body: some View {
        List {
            summarySection
            if let g, !g.models.isEmpty {
                Section("Kinds") {
                    ForEach(g.models) { m in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(m.name).font(.callout.weight(.medium))
                                Text([m.vram, m.nodes.map { "\($0) node\($0 == 1 ? "" : "s")" }]
                                    .compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("\(m.free ?? 0) of \(m.gpus ?? 0) free")
                                .font(.callout.monospacedDigit())
                                .foregroundStyle((m.free ?? 0) > 0 ? Color.green : .secondary)
                        }
                    }
                }
            }
            if let g, !g.nodes.isEmpty {
                Section {
                    ForEach(g.nodes) { n in nodeRow(n) }
                } header: {
                    Text("By node (\(g.nodes.count))")
                } footer: {
                    Text("Free GPUs, idle CPUs and free memory on each node, and the partitions that reach it.")
                }
            }
            whereSection
        }
        .navigationTitle("GPUs")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
    }

    private var summarySection: some View {
        Section {
            if let g, let free = g.free, let total = g.total {
                HStack(spacing: 16) {
                    ClusterStat(value: "\(free) of \(total)", caption: "GPUs free")
                    if let limit {
                        ClusterStat(value: "\(store.snapshot?.gpusInUse ?? 0) of \(limit)",
                                    caption: "yours in use, of what you may")
                    }
                }
            } else {
                Text(store.look == nil ? "Nothing read yet." : "The last look had no GPU readings.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    private func nodeRow(_ n: ClusterGpus.Node) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(n.name).font(.callout.weight(.medium))
                Text(n.model ?? "").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text("\(n.free ?? 0) of \(n.total ?? 0) free")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle((n.free ?? 0) > 0 ? Color.green : .secondary)
            }
            Text([n.state, n.idleCPUs.map { "\($0) CPUs idle" }, n.freeMem.map { "\($0) free" }]
                .compactMap { $0 }.joined(separator: " · "))
                .font(.caption).foregroundStyle(.secondary)
            if let p = n.partitions {
                Text(p).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
            }
        }
    }

    private var whereSection: some View {
        Section {
            Stepper(value: $gpus, in: 1...8) { LabeledContent("GPUs", value: "\(gpus)") }
            Stepper(value: $memGB, in: 0...2048, step: 8) { LabeledContent("Memory", value: "\(memGB) GB") }
            Stepper(value: $cpus, in: 0...128, step: 4) { LabeledContent("CPUs", value: "\(cpus)") }
            TextField("GPU model (optional)", text: $model)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
            Button {
                Task { await check() }
            } label: {
                HStack {
                    Label("Check", systemImage: "scope")
                    if checking { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(checking || g == nil)
            if let fit {
                if fit.overLimit {
                    Label("You may use only \(fit.gpuLimit ?? 0) GPUs at once: this would wait for ever.",
                          systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.orange)
                } else if fit.nodes.isEmpty {
                    Text("Nothing has that free right now: it would wait. Ask for less memory or fewer CPUs, or try again later.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    ForEach(fit.nodes) { n in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(n.name).font(.callout.weight(.medium))
                            Text([n.model, n.freeGPUs.map { "\($0) free" }, n.freeMem.map { "\($0) memory" }]
                                .compactMap { $0 }.joined(separator: " · "))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } header: {
            Text("Where would my job start now?")
        } footer: {
            Text("Answered from the last look at the cluster; it submits nothing.")
        }
    }

    private func check() async {
        guard let server = state.server else { return }
        checking = true
        defer { checking = false }
        do {
            fit = try await server.clusterWhere(gpus: gpus, memGB: memGB, cpus: cpus, model: model)
        } catch { note = error.localizedDescription }
    }
}
