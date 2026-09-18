import SwiftUI

/// The pieces the new-chat sheet and a chat's "where it works" sheet share:
/// which machine, which folder, and the permission mode.

/// "Where" and "Folder", as two form sections.
struct WorkPlaceSections: View {
    @EnvironmentObject var state: AppState
    @Binding var host: String
    @Binding var folder: String
    var harness: HarnessKind
    /// Once a chat's first answer has started, its machine is fixed.
    var hostLocked = false
    var lockedNote: String? = nil
    @State private var places: FolderPlaces = .empty
    @State private var starring = false
    @State private var note: String?

    private var trimmed: String { folder.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var starred: Bool { !trimmed.isEmpty && places.bookmarks.contains(trimmed) }

    var body: some View {
        Section {
            Picker("Machine", selection: Binding(get: { host }, set: { pick(host: $0) })) {
                Label("This Mac", systemImage: "laptopcomputer").tag("")
                ForEach(state.remoteHosts) { h in
                    Label(h.host, systemImage: "server.rack").tag(h.host)
                }
                // a chat already on a host the ssh config no longer lists
                if !host.isEmpty, !state.remoteHosts.contains(where: { $0.host == host }) {
                    Label(host, systemImage: "server.rack").tag(host)
                }
            }
            .disabled(hostLocked)
            if !host.isEmpty { ProbeStatus(host: host, harness: harness) }
        } header: {
            Text("Where")
        } footer: {
            if hostLocked {
                Text(lockedNote ?? "The machine is fixed once a chat has answered.")
            } else if host.isEmpty {
                Text("\(harness.label) works in a folder on your Mac. On an SSH host it edits files "
                     + "and runs commands on that machine instead; the models still come through "
                     + "your Mac. The machine can't change after the first answer.")
            } else {
                Text("\(harness.label) runs on \(host) over SSH, in the folder below. The machine "
                     + "can't change after the first answer.")
            }
        }
        .task(id: host) { await loadPlaces() }

        Section {
            HStack(spacing: 10) {
                TextField(host.isEmpty ? "Orbit workspace, or a path on the Mac"
                                       : "a folder on \(host), e.g. ~/project",
                          text: $folder)
                    .font(.callout.monospaced())
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                Button {
                    Task { await toggleStar() }
                } label: {
                    Image(systemName: starred ? "star.fill" : "star")
                        .foregroundStyle(starred ? .yellow : .secondary)
                }
                .buttonStyle(.plain)
                .disabled(trimmed.isEmpty || starring)
                .accessibilityLabel(starred ? "Remove bookmark" : "Bookmark this folder")
            }
            if !host.isEmpty {
                NavigationLink {
                    RemoteFolderBrowser(host: host, start: trimmed.isEmpty ? "~" : trimmed) { folder = $0 }
                } label: {
                    Label("Browse \(host)…", systemImage: "folder.badge.questionmark")
                }
            }
            if let note { Text(note).font(.caption).foregroundStyle(.secondary) }
        } header: {
            Text("Folder")
        } footer: {
            if host.isEmpty {
                Text("The phone can't browse the Mac's folders: type a path, or pick one below. "
                     + "Empty means the Orbit workspace. The Mac checks that it exists.")
            }
        }

        if !places.bookmarks.isEmpty {
            Section("Bookmarks") {
                ForEach(places.bookmarks, id: \.self) { p in placeRow(p, symbol: "star.fill", tint: .yellow) }
            }
        }
        if !places.recent.isEmpty {
            Section("Recent") {
                ForEach(places.recent.prefix(8), id: \.self) { p in placeRow(p, symbol: "clock", tint: .secondary) }
            }
        }
        if host.isEmpty, !places.folders.isEmpty {
            Section("On this Mac") {
                ForEach(places.folders.prefix(10), id: \.self) { f in
                    placeRow(f.path, symbol: "folder", tint: .secondary, why: f.why)
                }
            }
        }
    }

    private func placeRow(_ path: String, symbol: String, tint: Color, why: String? = nil) -> some View {
        Button {
            folder = path
        } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol).foregroundStyle(tint).frame(width: 18)
                VStack(alignment: .leading, spacing: 1) {
                    Text(PathText.short(path, keep: 3))
                        .font(.callout.monospaced()).foregroundStyle(.primary)
                        .lineLimit(1).truncationMode(.middle)
                    if let why, !why.isEmpty {
                        Text(why).font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
                if path == trimmed { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
            }
        }
        .tint(.primary)
        .accessibilityLabel(path)
    }

    /// Picking a machine: its folders, a sensible starting folder, and one
    /// check of the host — never more than one without being asked.
    private func pick(host new: String) {
        guard new != host else { return }
        host = new
        note = nil
        places = .empty
        if new.isEmpty {
            if trimmed.hasPrefix("~") || !trimmed.hasPrefix("/Users/") { folder = "" }
            return
        }
        let saved = state.remoteHosts.first { $0.host == new }?.defaultDir
        folder = saved ?? "~"
        Task {
            await loadPlaces()
            if saved == nil, let first = places.bookmarks.first, host == new, folder == "~" { folder = first }
            if state.hostProbes[new] == nil { await state.probe(host: new) }
        }
    }

    private func loadPlaces() async {
        guard let server = state.server else { return }
        let h = host
        if let p = try? await server.folderPlaces(host: h), h == host { places = p }
    }

    private func toggleStar() async {
        guard let server = state.server, !trimmed.isEmpty else { return }
        starring = true
        defer { starring = false }
        let on = !starred
        do {
            places.bookmarks = try await server.bookmark(host: host, path: trimmed, on: on)
            note = on ? "Bookmarked." : "Bookmark removed."
            Haptics.tap()
        } catch { note = error.localizedDescription }
    }
}

/// One line on what checking a host found, with a way to check again.
struct ProbeStatus: View {
    @EnvironmentObject var state: AppState
    let host: String
    var harness: HarnessKind = .claude

    var body: some View {
        if state.probing.contains(host) {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Checking \(host)…").font(.callout)
                    Text("Connecting over SSH can take up to a minute.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        } else if let p = state.hostProbes[host] {
            VStack(alignment: .leading, spacing: 4) {
                if p.ok {
                    Label(p.hostname.map { "Reachable · \($0)" } ?? "Reachable", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    HStack(spacing: 12) {
                        tool("Claude Code", version: p.claudeVersion, present: p.hasClaude,
                             wanted: harness == .claude)
                        tool("Codex", version: p.codexVersion, present: p.hasCodex,
                             wanted: harness == .codex)
                    }
                    if let n = p.procs, let l = p.procLimit, l > 0 {
                        Text("\(n) of \(l) processes" + (p.nearProcessLimit ? " — near the limit" : ""))
                            .font(.caption)
                            .foregroundStyle(p.nearProcessLimit ? .orange : .secondary)
                    }
                } else {
                    Label("Not reachable", systemImage: "xmark.circle.fill").foregroundStyle(.red)
                    if let e = p.error { Text(e).font(.caption).foregroundStyle(.secondary) }
                }
                checkButton("Check again", refresh: true, when: p.checkedAt)
            }
            .font(.callout)
        } else if let e = state.probeErrors[host] {
            VStack(alignment: .leading, spacing: 4) {
                Label("Couldn't check \(host)", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Text(e).font(.caption).foregroundStyle(.secondary)
                checkButton("Try again", refresh: true, when: nil)
            }
            .font(.callout)
        } else {
            checkButton("Check \(host)", refresh: false, when: nil)
        }
    }

    private func tool(_ name: String, version: String?, present: Bool, wanted: Bool) -> some View {
        HStack(spacing: 4) {
            Image(systemName: present ? "checkmark" : "minus")
                .foregroundStyle(present ? Color.secondary : (wanted ? .orange : .secondary))
            Text(present ? "\(name) \(version ?? "")" : "no \(name)")
                .foregroundStyle(!present && wanted ? .orange : .secondary)
        }
        .font(.caption)
    }

    private func checkButton(_ title: String, refresh: Bool, when: Date?) -> some View {
        HStack {
            Button(title) { Task { await state.probe(host: host, refresh: refresh) } }
                .font(.caption.weight(.semibold))
                .buttonStyle(.borderless)
            if let when {
                Spacer()
                Text("checked " + when.formatted(.relative(presentation: .named)))
                    .font(.caption2).foregroundStyle(.tertiary)
            }
        }
    }
}

/// Folders on a host, one level at a time. Every step is one SSH listing, so
/// nothing is listed until you go there.
struct RemoteFolderBrowser: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let host: String
    let start: String
    let onPick: (String) -> Void
    @State private var listing: RemoteListing?
    @State private var loading = false
    @State private var error: String?
    @State private var showHidden = false

    private var dirs: [String] {
        (listing?.dirs ?? []).filter { showHidden || !$0.hasPrefix(".") }
            .sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }

    var body: some View {
        List {
            if let path = listing?.path {
                Section {
                    Text(path)
                        .font(.callout.monospaced())
                        .textSelection(.enabled)
                    Button {
                        onPick(path); dismiss()
                    } label: {
                        Label("Use this folder", systemImage: "checkmark.circle.fill")
                    }
                    if path != "/" {
                        Button {
                            Task { await go((path as NSString).deletingLastPathComponent) }
                        } label: {
                            Label("Up", systemImage: "arrow.up")
                        }
                        .disabled(loading)
                    }
                }
                Section {
                    ForEach(dirs, id: \.self) { d in
                        Button {
                            Task { await go(path == "/" ? "/\(d)" : "\(path)/\(d)") }
                        } label: {
                            HStack {
                                Label(d, systemImage: "folder").foregroundStyle(.primary)
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                            }
                        }
                        .disabled(loading)
                    }
                    if dirs.isEmpty { Text("No folders here").foregroundStyle(.secondary) }
                } header: {
                    HStack {
                        Text("Folders")
                        Spacer()
                        Toggle("Hidden", isOn: $showHidden).toggleStyle(.button).font(.caption)
                            .textCase(nil)
                    }
                } footer: {
                    let n = listing?.files?.count ?? 0
                    if n > 0 { Text("\(n) file\(n == 1 ? "" : "s") here too.") }
                }
            } else if let error {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Button("Try again") { Task { await go(start) } }
                }
            }
        }
        .overlay {
            if loading {
                VStack(spacing: 8) {
                    ProgressView()
                    Text("Listing on \(host)…").font(.caption).foregroundStyle(.secondary)
                }
                .padding(16)
                .background(.regularMaterial, in: .rect(cornerRadius: 12))
            }
        }
        .navigationTitle(listing?.path.map { ($0 as NSString).lastPathComponent } ?? host)
        .navigationBarTitleDisplayMode(.inline)
        .task { if listing == nil && error == nil { await go(start) } }
    }

    private func go(_ path: String) async {
        guard let server = state.server, !loading else { return }
        loading = true
        defer { loading = false }
        do {
            listing = try await server.listRemote(host: host, path: path)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// The permission mode, with Bypass behind a confirmation.
struct PermissionModeSection: View {
    @Binding var mode: PermissionMode
    var harness: HarnessKind
    @State private var confirmBypass = false

    var body: some View {
        Section {
            Picker("Permission mode", selection: Binding(
                get: { mode },
                set: { picked in
                    if picked == .bypass && mode != .bypass { confirmBypass = true } else { mode = picked }
                })) {
                ForEach(PermissionMode.allCases) { m in
                    Label(m.label, systemImage: m.symbol).tag(m)
                }
            }
            // a menu, not a pushed list: the Bypass confirmation must be able to show
            .pickerStyle(.menu)
        } header: {
            Text("Permission mode")
        } footer: {
            Text(mode.detail + (mode == .bypass ? " Use it only in a folder you can afford to lose." : ""))
                .foregroundStyle(mode == .bypass ? .orange : .secondary)
        }
        .confirmationDialog("Switch to Bypass?", isPresented: $confirmBypass, titleVisibility: .visible) {
            Button("Use Bypass", role: .destructive) { mode = .bypass }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("\(harness.label) will run every tool — shell commands, edits, deletions — without "
                 + "asking you first. Use it only in a folder you can afford to lose.")
        }
    }
}
