import SwiftUI

/// Settings → Status & health: what Orbit on the Mac is, whether its code is
/// current, the model server's numbers, the health check (the web page's
/// doctor), and the two maintenance buttons — restart Orbit, purge the bin.
struct StatusHealthView: View {
    @EnvironmentObject var state: AppState
    @State private var about: AboutMac?
    @State private var detail: ServerDetail?
    @State private var code: CodeStatus?
    @State private var health: [HealthRow]?
    @State private var error: String?
    @State private var note: String?
    @State private var checking = false
    @State private var confirmRestart = false
    @State private var confirmPurge = false
    @State private var busy = false

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            orbit
            server
            healthSection
            maintenance
        }
        .navigationTitle("Status & health")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Restart Orbit on the Mac?", isPresented: $confirmRestart, titleVisibility: .visible) {
            Button("Restart Orbit") { Task { await restart() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The interface restarts on its current code. If answers are running it waits for them to "
                 + "finish first. The phone reconnects by itself a few seconds later.")
        }
        .confirmationDialog("Purge the bin now?", isPresented: $confirmPurge, titleVisibility: .visible) {
            Button("Delete expired items permanently", role: .destructive) { Task { await purge() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Chats and files that have been in the bin longer than the Mac keeps them are deleted for "
                 + "good. Newer ones stay restorable. This can't be undone.")
        }
    }

    // MARK: sections

    private var orbit: some View {
        Section {
            if let a = about {
                LabeledContent("Version", value: a.version ?? "—")
                if let tools = a.tools { LabeledContent("Tools ready", value: "\(tools.count)") }
                if let c = a.counts {
                    ForEach(["sessions", "memories", "skills", "knowledge", "projects", "files"], id: \.self) { k in
                        if let n = c[k] {
                            LabeledContent(k == "sessions" ? "Chats" : k.capitalized,
                                           value: n >= 5000 && k == "files" ? "5000+" : "\(n)")
                        }
                    }
                }
            } else if error == nil {
                LoadingRow()
            }
            if let c = code {
                if c.stale == true {
                    VStack(alignment: .leading, spacing: 3) {
                        Label("Code changed on disk", systemImage: "arrow.triangle.2.circlepath")
                            .foregroundStyle(.orange)
                        Text((c.files ?? []).joined(separator: ", ") + " — the running interface is out of date.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    LabeledContent("Code", value: "up to date")
                }
            }
            Button("Restart Orbit…") { confirmRestart = true }.disabled(busy)
        } header: {
            Text("Orbit on the Mac")
        }
    }

    @ViewBuilder private var server: some View {
        if let d = detail {
            Section {
                LabeledContent("Server", value: d.running ? "running" : "stopped")
                if let m = d.model { LabeledContent("Model") { Text(m).font(.caption).lineLimit(2) } }
                if let g = d.memoryGB { LabeledContent("Model memory", value: String(format: "%.1f GB", g)) }
                if let t = d.last?.decode_tok_s, t > 0 {
                    LabeledContent("Decode", value: String(format: "%.0f tok/s", t))
                }
                if let used = d.contextUsed {
                    LabeledContent("Context used", value: "\(used)" + (d.contextMax.map { " of \($0)" } ?? ""))
                }
                if !d.flags.isEmpty {
                    DisclosureGroup("Launch flags") {
                        ForEach(d.flags.keys.sorted(), id: \.self) { k in
                            LabeledContent(k) { Text(d.flags[k] ?? "").font(.caption.monospaced()) }
                                .font(.caption)
                        }
                    }
                }
            } header: {
                Text("Local model server")
            } footer: {
                Text("Start, stop and switch model from the Local model section on the main Settings screen.")
            }
        }
    }

    private var healthSection: some View {
        Section {
            if let rows = health {
                ForEach(rows) { r in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: r.info == true ? "info.circle" : (r.ok ? "checkmark.circle.fill" : "xmark.circle.fill"))
                            .foregroundStyle(r.info == true ? Color.secondary : (r.ok ? Color.green : Color.red))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.name).font(.callout.weight(.medium))
                            if let d = r.detail, !d.isEmpty {
                                Text(d).font(.caption).foregroundStyle(.secondary)
                            }
                            if !r.ok, r.info != true, let fix = r.fix, !fix.isEmpty {
                                Text(fix).font(.caption).foregroundStyle(.orange)
                            }
                        }
                    }
                }
            } else if checking {
                LoadingRow(text: "Running the checks")
            }
            Button(health == nil ? "Run health check" : "Run again") { Task { await runHealth() } }
                .disabled(checking)
        } header: {
            Text("Health check")
        } footer: {
            Text("Disk space, the model server, tools, keys and the rest — each with a fix when it fails.")
        }
    }

    private var maintenance: some View {
        Section {
            Button("Purge expired items from the bin…", role: .destructive) { confirmPurge = true }
                .disabled(busy)
        } header: {
            Text("Bin")
        } footer: {
            Text("The Mac does this on its own schedule; this only brings it forward.")
        }
    }

    // MARK: I/O

    private func load() async {
        do {
            let s = try state.requireServer()
            async let a = s.aboutMac()
            async let d = s.serverDetail()
            async let c = s.codeStatus()
            about = try await a
            detail = try? await d
            code = try? await c
            error = nil
            if health == nil { await runHealth() }
        } catch { self.error = error.localizedDescription }
    }

    private func runHealth() async {
        checking = true
        defer { checking = false }
        do { health = try await state.requireServer().healthCheck() }
        catch { note = error.localizedDescription }
    }

    private func restart() async {
        busy = true
        defer { busy = false }
        do {
            note = try await state.requireServer().restartOrbit()
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            await state.checkReachable()
            await load()
        } catch { note = error.localizedDescription }
    }

    private func purge() async {
        busy = true
        defer { busy = false }
        do {
            let n = try await state.requireServer().purgeExpiredTrash()
            note = n == 0 ? "nothing had expired" : "deleted \(n) item\(n == 1 ? "" : "s")"
        } catch { note = error.localizedDescription }
    }
}
