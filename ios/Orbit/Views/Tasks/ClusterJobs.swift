import SwiftUI

/// Your jobs on the cluster, live from its queue. Every look is an SSH
/// connection and the cluster limits how often it may be reached, so nothing
/// is checked until you ask — not on opening the tab, not on pull to refresh.
struct ClusterJobsSection: View {
    @EnvironmentObject var state: AppState
    @State private var result: ClusterJobs?
    @State private var loading = false
    @State private var failed: String?
    @State private var checkedAt: Date?

    var body: some View {
        Section {
            if loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Checking the cluster…").font(.footnote).foregroundStyle(.secondary)
                }
            } else if let failed {
                Label(failed, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.orange)
            } else if let e = result?.error {
                Label(String(e.prefix(140)), systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundStyle(.red)
            } else if let r = result, r.jobs.isEmpty {
                Text("No jobs queued or running.").font(.footnote).foregroundStyle(.secondary)
            }
            if let jobs = result?.jobs {
                ForEach(jobs) { j in
                    NavigationLink {
                        ClusterJobDetail(job: j)
                    } label: { row(j) }
                }
            }
            Button {
                Task { await check() }
            } label: {
                Label(result == nil ? "Check cluster jobs" : "Check again", systemImage: "arrow.clockwise")
            }
            .disabled(loading || state.server == nil)
        } header: {
            Text("Cluster jobs")
        } footer: {
            if let checkedAt {
                Text("Live from qstat, checked " + checkedAt.formatted(date: .omitted, time: .shortened) + ".")
            } else {
                Text("Live from qstat. Checked only when you ask: each look connects to the cluster over SSH.")
            }
        }
    }

    private func row(_ j: ClusterJob) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(j.name).font(.callout.weight(.medium)).lineLimit(1)
                Text("#\(j.id)").font(.caption.monospaced()).foregroundStyle(.secondary)
            }
            HStack(spacing: 6) {
                Text(j.stateLabel)
                    .foregroundStyle(j.state == "r" ? Color.green : j.state.hasPrefix("E") ? .red : .secondary)
                if let s = j.since, !s.isEmpty { Text("· \(s)") }
                Text("· \(j.slots?.isEmpty == false ? j.slots! : "?") slots")
            }
            .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func check() async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        do {
            result = try await server.clusterJobs()
            failed = nil
            checkedAt = .now
        } catch {
            failed = "Couldn't reach the cluster: " + error.localizedDescription
        }
    }
}

/// One job: the end of its log, and how long jobs like it took before.
struct ClusterJobDetail: View {
    @EnvironmentObject var state: AppState
    let job: ClusterJob
    @State private var log: String?
    @State private var lines = 80
    @State private var loadingLog = false
    @State private var estimate: String?
    @State private var estimating = false
    @State private var failed: String?

    var body: some View {
        List {
            Section {
                LabeledContent("Job", value: "#\(job.id)")
                LabeledContent("State", value: job.stateLabel)
                if let s = job.since, !s.isEmpty { LabeledContent("Since", value: s) }
                LabeledContent("Slots", value: job.slots?.isEmpty == false ? job.slots! : "?")
                if let p = job.prio, !p.isEmpty { LabeledContent("Priority", value: p) }
            }

            Section {
                Button {
                    Task { await estimateRuntime() }
                } label: {
                    HStack {
                        Label("Estimate", systemImage: "timer")
                        if estimating { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(estimating)
                if let estimate { Text(estimate).font(.callout).foregroundStyle(.secondary) }
            } footer: {
                Text("From past runs of jobs whose name starts the same way.")
            }

            Section {
                if loadingLog {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Reading the log…").font(.footnote).foregroundStyle(.secondary)
                    }
                } else if let log {
                    ScrollView(.horizontal) {
                        Text(log.isEmpty ? "(no log found)" : log)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Button {
                        UIPasteboard.general.string = log
                        state.toast("Log copied")
                    } label: { Label("Copy log", systemImage: "doc.on.doc") }
                    .disabled(log.isEmpty)
                    if lines < 400 {
                        Button { lines = 400; Task { await tail() } } label: {
                            Label("Show more lines", systemImage: "text.append")
                        }
                    }
                }
                Button {
                    Task { await tail() }
                } label: {
                    Label(log == nil ? "Tail log" : "Read again", systemImage: "doc.text.magnifyingglass")
                }
                .disabled(loadingLog)
            } header: {
                Text("Log")
            } footer: {
                Text("The last \(lines) lines of its output log. Each read connects to the cluster.")
            }

            if let failed {
                Section { Label(failed, systemImage: "exclamationmark.triangle").foregroundStyle(.orange) }
            }
        }
        .navigationTitle(job.name)
        .navigationBarTitleDisplayMode(.inline)
        .modifier(ToastOverlay())
    }

    private func tail() async {
        guard let server = state.server else { return }
        loadingLog = true
        defer { loadingLog = false }
        do {
            log = try await server.clusterLog(id: job.id, lines: lines)
            failed = nil
        } catch { failed = error.localizedDescription }
    }

    private func estimateRuntime() async {
        guard let server = state.server else { return }
        estimating = true
        defer { estimating = false }
        do {
            let e = try await server.clusterEstimate(name: String(job.name.prefix(8)))
            if let runs = e.runs, runs > 0, let m = e.median_min {
                estimate = "Median \(Self.minutes(m)) over \(runs) past run\(runs == 1 ? "" : "s")"
                    + (e.max_min.map { ", longest \(Self.minutes($0))" } ?? "") + "."
            } else {
                estimate = "No history for this job name."
            }
            failed = nil
        } catch { failed = error.localizedDescription }
    }

    private static func minutes(_ m: Double) -> String {
        m == m.rounded() ? "\(Int(m)) min" : String(format: "%.1f min", m)
    }
}
