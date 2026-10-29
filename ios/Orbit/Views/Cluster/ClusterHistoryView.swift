import SwiftUI

/// How you have used the cluster: jobs, GPU- and CPU-hours, how long they usually wait, per day and
/// per job name. From the scheduler's records. It opens on the last reading the Mac kept; a span
/// the Mac has not read yet, or Read again, asks the scheduler over SSH.
struct ClusterHistoryView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterStore
    @State private var days = 7
    @State private var shown: ClusterHistory?
    @State private var loading = false
    @State private var note: String?

    var body: some View {
        List {
            Section {
                Picker("Span", selection: $days) {
                    Text("Last day").tag(1)
                    Text("7 days").tag(7)
                    Text("30 days").tag(30)
                }
                .pickerStyle(.segmented)
                .onChange(of: days) { _, d in
                    shown = store.look?.history[d]
                }
            }
            if let h = shown {
                totals(h)
                if h.daily.count > 1 { dailySection(h) }
                if !h.byName.isEmpty { namesSection(h) }
            } else if loading {
                Section { LoadingRow(text: "Reading the accounting") }
            } else {
                Section {
                    Text("The Mac has not read this span yet.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                Button {
                    Task { await read(refresh: true) }
                } label: {
                    HStack {
                        Label(shown == nil ? "Read it" : "Read again", systemImage: "arrow.clockwise")
                        if loading { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(loading || state.server == nil)
            } footer: {
                Text(footer)
            }
        }
        .navigationTitle("Usage history")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .task {
            // the most recently read span the Mac kept; nothing is read until you ask
            if shown == nil, let kept = store.look?.history.values.max(by: { ($0.readAt ?? 0) < ($1.readAt ?? 0) }) {
                days = kept.days
                shown = kept
            }
        }
    }

    private var footer: String {
        if let t = shown?.readAt {
            return "Read \(store.look?.ago(t) ?? "") from the scheduler's records. Reading again connects to the cluster."
        }
        return "From the scheduler's records. Reading connects to the cluster."
    }

    private func totals(_ h: ClusterHistory) -> some View {
        Section {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 12) {
                GridRow {
                    ClusterStat(value: "\(h.ran)", caption: "jobs that ran")
                    ClusterStat(value: h.medianWait.map { ClusterFormat.duration($0) } ?? "—", caption: "typical wait")
                }
                GridRow {
                    ClusterStat(value: h.gpuHours.formatted(), caption: "GPU-hours")
                    ClusterStat(value: h.cpuHours.formatted(), caption: "CPU-hours")
                }
            }
            Text("\(h.completed) finished, \(h.failed) failed, \(h.cancelled) cancelled")
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func dailySection(_ h: ClusterHistory) -> some View {
        let top = max(1, h.daily.map { $0.gpuHours > 0 ? $0.gpuHours : $0.cpuHours / 50 }.max() ?? 1)
        return Section {
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(h.daily) { d in
                    let v = d.gpuHours > 0 ? d.gpuHours : d.cpuHours / 50
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.accentColor)
                        .frame(height: max(4, 52 * v / top))
                        .frame(maxWidth: .infinity)
                        .accessibilityLabel("\(d.day): \(d.jobs) jobs, \(d.gpuHours) GPU-hours")
                }
            }
            .frame(height: 56, alignment: .bottom)
        } header: {
            Text("Per day")
        } footer: {
            if let first = h.daily.first, let last = h.daily.last {
                Text("\(first.day) to \(last.day). Height is GPU-hours (CPU-hours when a day used no GPU).")
            }
        }
    }

    private func namesSection(_ h: ClusterHistory) -> some View {
        Section("By job name") {
            ForEach(h.byName) { r in
                VStack(alignment: .leading, spacing: 3) {
                    Text(r.name).font(.callout.weight(.medium))
                    Text("\(r.jobs) runs · \(r.ok) finished, \(r.failed) failed · \(r.gpuHours.formatted()) GPU-h")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("usually waits \(r.medianWait.map { ClusterFormat.duration($0) } ?? "—"), runs \(r.medianRun.map { ClusterFormat.duration($0) } ?? "—")")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func read(refresh: Bool) async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        do {
            let h = try await server.clusterHistory(days: days, refresh: refresh)
            shown = h
            // the Mac keeps it: remember it for this visit too
            if var l = store.look { l.history[days] = h; store.look = l }
        } catch { note = error.localizedDescription }
    }
}
