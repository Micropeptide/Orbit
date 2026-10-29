import SwiftUI

/// The cluster, the way the Mac's cluster page shows it: what needs a look, your
/// jobs, and a link to each of the other views (GPUs, limits and queue, usage
/// history, disk, what happened, settings) and to the models served from its GPUs.
///
/// It opens on the Mac's last reading. Refresh connects to the cluster over SSH, and
/// the cluster limits how often it may be reached, so nothing refreshes by itself.
struct ClusterScreen: View {
    @EnvironmentObject var state: AppState
    @StateObject private var store = ClusterStore()
    @State private var note: String?
    @State private var busyKey: String?
    @State private var showAway = false
    @State private var confirmCancel: ClusterJobFull?

    private var look: ClusterLook? { store.look }
    private var snap: ClusterSnapshot? { store.snapshot }
    private var problems: [ClusterProblem] { (snap?.problems ?? []).filter { !$0.dismissed } }
    private var away: [ClusterProblem] { (snap?.problems ?? []).filter(\.dismissed) }

    var body: some View {
        List {
            headSection
            if snap != nil {
                problemsSection
                jobsSection
                recentSection
                moreSection
            } else if store.loading {
                Section { LoadingRow(text: "Reading the cluster") }
            }
        }
        .navigationTitle("Cluster")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: "\(state.pairing?.url ?? "")|\(state.reachable == true)") { await store.open(state) }
        .refreshable { await store.refresh(state) }
        .settingsNote($note)
        .confirmationDialog("Cancel \(confirmCancel?.name ?? "this job")?", isPresented: Binding(
            get: { confirmCancel != nil }, set: { if !$0 { confirmCancel = nil } }),
            titleVisibility: .visible, presenting: confirmCancel) { j in
            Button("Cancel job", role: .destructive) { Task { await cancel(j) } }
            Button("Keep it", role: .cancel) {}
        } message: { j in
            Text(isServer(j) ? "This is a model server. Chats using it stop getting answers." : "It stops now and cannot be resumed.")
        }
    }

    private func isServer(_ j: ClusterJobFull) -> Bool { look?.modelServerJobs.contains(j.name) ?? false }

    // ------------------------------------------------------------ sections

    private var headSection: some View {
        Section {
            if let snap {
                LabeledContent(look?.config.host ?? "Cluster",
                               value: (snap.host?.node).map { "\($0) · looked \(look?.ago(look?.at) ?? "")" }
                                   ?? "looked \(look?.ago(look?.at) ?? "")")
                    .font(.footnote)
            }
            if let e = look?.error ?? store.error {
                Label(e, systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundStyle(.orange)
            }
            if look == nil && store.error == nil && !store.loading {
                Text("Nothing read yet.").font(.footnote).foregroundStyle(.secondary)
            }
            Button {
                Task { await store.refresh(state) }
            } label: {
                HStack {
                    Label(snap == nil ? "Look at the cluster" : "Refresh", systemImage: "arrow.clockwise")
                    if store.loading { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(store.loading || state.server == nil)
        } footer: {
            Text("Refresh connects to the cluster over SSH, which limits how often it may be reached, "
                 + "so nothing refreshes by itself. The Mac keeps watching on its own and tells you.")
        }
    }

    private var problemsSection: some View {
        Section {
            if problems.isEmpty {
                Text("Nothing: no disk filling up, nothing failing, nothing stuck.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(problems) { problemRow($0, dismissed: false) }
            if !away.isEmpty {
                DisclosureGroup("\(away.count) put away", isExpanded: $showAway) {
                    ForEach(away) { problemRow($0, dismissed: true) }
                }
                .font(.footnote)
            }
        } header: {
            HStack(spacing: 6) {
                Text("Needs a look")
                if !problems.isEmpty {
                    Text("\(problems.count)")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(Color.red.opacity(0.15), in: Capsule())
                        .foregroundStyle(.red)
                }
            }
        }
    }

    private func problemRow(_ p: ClusterProblem, dismissed: Bool) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: p.level == "bad" ? "exclamationmark.octagon.fill"
                        : p.level == "warn" ? "exclamationmark.triangle.fill" : "info.circle.fill")
                    .foregroundStyle(p.level == "bad" ? Color.red : p.level == "warn" ? .orange : .blue)
                Text(p.text).font(.callout)
            }
            HStack(spacing: 12) {
                Button {
                    Task { await putAway(p, back: dismissed) }
                } label: {
                    if busyKey == p.key { ProgressView().controlSize(.small) }
                    else { Text(dismissed ? "Show again" : "Put away").font(.caption) }
                }
                .buttonStyle(.borderless)
                .disabled(busyKey != nil)
                if !p.ids.isEmpty {
                    Text("jobs " + p.ids.prefix(4).joined(separator: ", ")).font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
        .opacity(dismissed ? 0.6 : 1)
    }

    private var jobsSection: some View {
        let jobs = snap?.jobs ?? []
        return Section {
            if jobs.isEmpty {
                Text("None in the queue.").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(jobs) { j in
                NavigationLink {
                    ClusterJobDetail(job: j, isServer: isServer(j)) { updated in store.look = updated }
                } label: { jobRow(j) }
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) { confirmCancel = j } label: {
                        Label("Cancel", systemImage: "xmark.circle")
                    }
                }
            }
        } header: {
            Text("Your jobs")
        } footer: {
            if let s = snap, !s.jobs.isEmpty {
                Text("\(s.running.count) running, \(s.waiting.count) waiting. Swipe a job to cancel it.")
            }
        }
    }

    private func jobRow(_ j: ClusterJobFull) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(j.name).font(.callout.weight(.medium)).lineLimit(1)
                Text("#\(j.id)").font(.caption.monospaced()).foregroundStyle(.secondary)
                Spacer()
                ClusterStatePill(job: j.state)
            }
            Text(jobLine(j)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
    }

    private func jobLine(_ j: ClusterJobFull) -> String {
        var parts: [String] = []
        if j.isRunning {
            if let n = j.node { parts.append(n) }
            parts.append("\(ClusterFormat.duration(j.elapsed)) of \(ClusterFormat.duration(j.limit))")
        } else if let r = j.reason {
            parts.append(ClusterFormat.shortReason(r))
        } else {
            parts.append("queued")
        }
        if let g = j.gpus, g > 0 { parts.append("\(g) GPU") }
        if isServer(j) { parts.append("a model server") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private var recentSection: some View {
        let rec = Array((snap?.recent ?? []).prefix(8))
        Section {
            if rec.isEmpty {
                Text("No jobs in the last three days.").font(.footnote).foregroundStyle(.secondary)
            }
            ForEach(rec) { r in
                NavigationLink {
                    ClusterRecentDetail(job: r)
                } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(r.name).font(.callout.weight(.medium)).lineLimit(1)
                            Text("#\(r.id)").font(.caption.monospaced()).foregroundStyle(.secondary)
                            Spacer()
                            ClusterStatePill(job: r.state)
                        }
                        Text([ClusterFormat.duration(r.elapsed), ClusterFormat.shortTime(r.start), r.node ?? ""]
                            .filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("Last three days")
        }
    }

    private var moreSection: some View {
        Section {
            NavigationLink { ClusterModelsView() } label: {
                Label("Cluster models", systemImage: "server.rack")
            }
            NavigationLink { ClusterGPUsView(store: store) } label: {
                row("GPUs", "cpu", detail: gpuDetail)
            }
            NavigationLink { ClusterLimitsView(store: store) } label: {
                row("Limits and the queue", "gauge.with.dots.needle.50percent", detail: limitDetail)
            }
            NavigationLink { ClusterHistoryView(store: store) } label: {
                row("Usage history", "chart.bar", detail: nil)
            }
            NavigationLink { ClusterDiskView(store: store) } label: {
                row("Disk and biggest folders", "internaldrive", detail: diskDetail)
            }
            NavigationLink { ClusterEventsView(store: store) } label: {
                row("What happened", "list.bullet.rectangle", detail: eventDetail)
            }
            NavigationLink { ClusterSettingsView(store: store) } label: {
                row("Watching and settings", "slider.horizontal.3", detail: nil)
            }
        }
    }

    private func row(_ title: String, _ icon: String, detail: String?) -> some View {
        HStack {
            Label(title, systemImage: icon)
            if let detail {
                Spacer()
                Text(detail).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }

    private var gpuDetail: String? {
        guard let g = snap?.gpus, let free = g.free, let total = g.total else { return nil }
        return "\(free) of \(total) free"
    }

    private var limitDetail: String? {
        guard let s = snap, let lim = s.account?.gpuLimit else { return nil }
        return "\(s.gpusInUse) of \(lim) GPUs"
    }

    private var diskDetail: String? {
        guard let s = snap else { return nil }
        let top = (s.shared.compactMap(\.pct) + s.storage.compactMap(\.pct)).max()
        return top.map { "\($0)% full" }
    }

    private var eventDetail: String? {
        let n = look?.events.filter(\.isTrouble).count ?? 0
        return n > 0 ? "\(n) to read" : nil
    }

    // ------------------------------------------------------------ actions

    private func putAway(_ p: ClusterProblem, back: Bool) async {
        guard let server = state.server else { return }
        busyKey = p.key
        defer { busyKey = nil }
        do {
            store.look = back ? try await server.clusterRestore(key: p.key) : try await server.clusterDismiss(key: p.key)
        } catch { note = error.localizedDescription }
    }

    private func cancel(_ j: ClusterJobFull) async {
        await store.apply(state) { try await $0.clusterCancelJob(id: j.id) }
        note = store.error ?? "Cancelled \(j.name)"
    }
}
