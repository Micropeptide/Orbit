import SwiftUI

/// The disk: your quotas and the lab's shared disk as bars, and from each a way into its biggest folders.
/// The quota numbers are slow to read, so the Mac keeps the last reading; "Read the numbers again" connects.
struct ClusterDiskView: View {
    @EnvironmentObject var state: AppState
    @ObservedObject var store: ClusterStore
    @State private var note: String?

    private var snap: ClusterSnapshot? { store.snapshot }
    private var projectDir: String { store.look?.config.projectDir ?? "" }

    var body: some View {
        List {
            Section {
                ForEach(snap?.storage ?? []) { s in storageRow(s) }
                ForEach(snap?.shared ?? []) { d in sharedRow(d) }
                if (snap?.storage.isEmpty ?? true) && (snap?.shared.isEmpty ?? true) {
                    Text("No disk readings yet. Read the numbers to get the sizes.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Button {
                    Task { await store.refresh(state, slow: true); note = store.error }
                } label: {
                    HStack {
                        Label("Read the numbers again", systemImage: "arrow.clockwise")
                        if store.loading { Spacer(); ProgressView().controlSize(.small) }
                    }
                }
                .disabled(store.loading || state.server == nil)
            } header: {
                Text("Disk")
            } footer: {
                Text("Quota numbers read \(store.look?.ago(snap?.slowAt) ?? "never"). They are slow to read, so the Mac keeps "
                     + "the last reading; reading again connects to the cluster.")
            }

            Section {
                if !projectDir.isEmpty {
                    NavigationLink { ClusterFolderView(which: "mine", title: "My project folder") } label: {
                        Label("My project folder", systemImage: "folder.badge.person.crop")
                    }
                    NavigationLink { ClusterFolderView(which: "lab", title: "Who uses the lab disk") } label: {
                        Label("Who uses the lab disk", systemImage: "person.2")
                    }
                }
                NavigationLink { ClusterFolderView(which: "home", title: "Home") } label: {
                    Label("Largest folders in home", systemImage: "house")
                }
                NavigationLink { ClusterFolderView(which: "scratch", title: "Scratch") } label: {
                    Label("Largest folders in scratch", systemImage: "internaldrive")
                }
            } header: {
                Text("Biggest folders")
            } footer: {
                Text("Counted by a small batch job on a compute node, never on the login node. Nothing is measured until you start it.")
            }
        }
        .navigationTitle("Disk")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
    }

    private func storageRow(_ s: ClusterStorage) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(s.label).font(.callout.weight(.medium))
                Spacer()
                if let p = s.pct { pctText(p) }
            }
            if s.pct != nil {
                ClusterBar(pct: s.pct)
                Text("\(ClusterFormat.size(kb: s.usedKB)) of \(ClusterFormat.size(kb: s.limitKB))"
                     + (s.filesPct.map { " · files \($0)%" } ?? ""))
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Text("\(ClusterFormat.size(kb: s.usedKB)) used, no quota").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    private func sharedRow(_ d: ClusterShared) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text("Lab project disk").font(.callout.weight(.medium))
                Spacer()
                if let p = d.pct { pctText(p) }
            }
            ClusterBar(pct: d.pct)
            Text("\(d.used ?? "?") of \(d.size ?? "?") · \(d.avail ?? "?") free")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    private func pctText(_ p: Int) -> some View {
        Text("\(p)%").font(.callout.monospacedDigit())
            .foregroundStyle(p >= 90 ? Color.red : p >= 85 ? .orange : .secondary)
    }
}

/// What is directly inside a place or a folder: the biggest entries, the kinds of file, the biggest
/// files, and (for the lab disk) who uses it. The Mac keeps the last measurement, with when it was made.
struct ClusterFolderView: View {
    @EnvironmentObject var state: AppState
    /// `home`, `scratch`, `mine`, `lab`, or a folder path under one of them.
    let which: String
    let title: String
    @State private var folder: ClusterFolder?
    @State private var loading = false
    @State private var confirmStart = false
    @State private var note: String?
    @State private var failed: String?

    private var isLab: Bool { which == "lab" }

    var body: some View {
        List {
            if let failed { Section { ErrorRow(message: failed) } }
            statusSection
            if let f = folder {
                if isLab, !f.people.isEmpty { peopleSection(f) }
                else if !f.rows.isEmpty { rowsSection(f) }
                if !isLab { detailSections(f) }
            } else if loading {
                Section { LoadingRow(text: "Reading the measurement") }
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .refreshable { await read(refresh: true) }
        .task { await read(refresh: false) }
        // while the measuring job runs the list fills in; look again every 15 seconds
        .task(id: folder?.running == true) {
            while folder?.running == true, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                if Task.isCancelled { break }
                await read(refresh: true)
            }
        }
        .confirmationDialog(isLab ? "Count every file on the lab disk?" : "Measure this place?",
                            isPresented: $confirmStart, titleVisibility: .visible) {
            Button("Start the measuring job") { Task { await start() } }
            Button("Not now", role: .cancel) {}
        } message: {
            Text(isLab
                 ? "This submits a batch job that can take an hour or more and loads the shared disk. Better at a quiet time."
                 : "This submits a small batch job (4 CPUs, 2 GB) that counts what is directly inside it.")
        }
    }

    // ------------------------------------------------------------ sections

    private var statusSection: some View {
        Section {
            if let f = folder {
                Text(f.path).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                if f.running {
                    Label("Measuring on a compute node: \(f.entries) of \(f.totalEntries > 0 ? String(f.totalEntries) : "?") entries done."
                          + " The list fills in as it goes.", systemImage: "hourglass")
                        .font(.footnote)
                } else if f.done {
                    Text("Measured \(ago(f.measuredAt)).").font(.footnote)
                } else if f.rows.isEmpty {
                    Text("Not measured yet.").font(.footnote)
                }
            }
            Button {
                confirmStart = true
            } label: {
                Label(folder?.done == true ? "Measure again" : "Start measuring", systemImage: "ruler")
            }
            .disabled(folder?.running == true || loading || state.server == nil)
            Button {
                Task { await read(refresh: true) }
            } label: {
                HStack {
                    Label("Read the saved numbers", systemImage: "arrow.clockwise")
                    if loading { Spacer(); ProgressView().controlSize(.small) }
                }
            }
            .disabled(loading || state.server == nil)
        } footer: {
            Text("The measuring job runs on a compute node, never on the login node. Reading the saved numbers connects to the cluster.")
        }
    }

    private func peopleSection(_ f: ClusterFolder) -> some View {
        let base = max(1, f.totalKB)
        return Section {
            ForEach(Array(f.people.enumerated()), id: \.element.id) { i, p in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("\(i + 1). \(p.owner)").font(.callout.weight(.medium))
                        Spacer()
                        Text(ClusterFormat.size(kb: p.kb)).font(.callout.monospacedDigit())
                    }
                    ClusterBar(pct: Int((100 * p.kb / base).rounded()))
                    Text(String(format: "%.1f%% of the disk · ", 100 * p.kb / base)
                         + p.folders.prefix(3).map { $0.split(separator: "/").last.map(String.init) ?? $0 }.joined(separator: ", "))
                        .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
            }
        } header: {
            Text("Who uses it")
        }
    }

    private func rowsSection(_ f: ClusterFolder) -> some View {
        let base = max(1, f.totalKB)
        return Section {
            ForEach(f.rows.prefix(40)) { r in
                if r.isFolder && r.kb > 1_048_576 {
                    NavigationLink { ClusterFolderView(which: r.path, title: r.name) } label: { entryRow(r, base) }
                } else {
                    entryRow(r, base)
                }
            }
        } header: {
            Text("Inside — \(ClusterFormat.size(kb: f.totalKB))")
        } footer: {
            Text("A folder over 1 GB opens to what is inside it.")
        }
    }

    private func entryRow(_ r: ClusterFolder.Row, _ base: Double) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: r.isFolder ? "folder" : "doc").foregroundStyle(.secondary)
                Text(r.name).font(.callout).lineLimit(1)
                Spacer()
                Text(ClusterFormat.size(kb: r.kb)).font(.callout.monospacedDigit())
            }
            ClusterBar(pct: Int((100 * r.kb / base).rounded()))
        }
    }

    @ViewBuilder private func detailSections(_ f: ClusterFolder) -> some View {
        if let n = f.fileCount, let kb = f.summaryKB {
            Section {
                Text("\(n.formatted()) files, \(ClusterFormat.size(kb: kb))"
                     + ((f.oldFiles ?? 0) > 0
                        ? "; \(ClusterFormat.size(kb: f.oldKB)) in \((f.oldFiles ?? 0).formatted()) files not changed for over a year (the first place to look for room)."
                        : "."))
                    .font(.footnote)
            }
        }
        if !f.kinds.isEmpty {
            Section("What kinds of file") {
                ForEach(f.kinds.prefix(12)) { k in
                    HStack {
                        Text(k.ext).font(.callout.weight(.medium))
                        Spacer()
                        Text("\(k.count.formatted()) · \(ClusterFormat.size(kb: k.kb))")
                            .font(.footnote.monospacedDigit()).foregroundStyle(.secondary)
                    }
                }
            }
        }
        if !f.files.isEmpty {
            Section("Biggest files") {
                ForEach(f.files.prefix(15)) { file in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(file.name).font(.callout).lineLimit(1)
                            Spacer()
                            Text(ClusterFormat.size(kb: file.kb)).font(.callout.monospacedDigit())
                        }
                        Text(file.path).font(.caption2).foregroundStyle(.secondary).lineLimit(1).truncationMode(.head)
                        if let m = file.mtime {
                            Text("last changed " + Date(timeIntervalSince1970: m).formatted(date: .abbreviated, time: .omitted))
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------ actions

    private func ago(_ t: Double?) -> String {
        guard let t else { return "never" }
        return ClusterFormat.ago(t, now: Date.now.timeIntervalSince1970)
    }

    private func read(refresh: Bool) async {
        guard let server = state.server else { return }
        loading = true
        defer { loading = false }
        do {
            folder = try await server.clusterFolder(which, refresh: refresh)
            failed = nil
        } catch { failed = error.localizedDescription }
    }

    private func start() async {
        guard let server = state.server else { return }
        do {
            try await server.clusterMeasure(which)
            note = "Measuring started"
            await read(refresh: true)
        } catch { note = error.localizedDescription }
    }
}
