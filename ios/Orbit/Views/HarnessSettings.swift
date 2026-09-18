import SwiftUI

/// Settings → which harness new chats use, and the SSH hosts chats can run on.
struct HarnessSection: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Section {
            Picker("New chats use", selection: Binding(
                get: { state.harnessMode },
                set: { kind in Task { await state.setHarnessMode(kind) } })) {
                ForEach(HarnessKind.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .disabled(state.harnessBusy)
            LabeledContent("Now") {
                HStack(spacing: 6) {
                    if state.harnessBusy { ProgressView().controlSize(.mini) }
                    Text(state.harnessMode.label
                         + (state.catalogueID(for: state.defaultModel).flatMap { id in
                               state.models.first { $0.id == id }?.display
                           }.map { " · \($0)" } ?? ""))
                        .lineLimit(1)
                }
            }
        } header: {
            Text("Harness")
        } footer: {
            Text(footer)
        }

        Section {
            if state.remoteHosts.isEmpty {
                Text("No SSH hosts in the Mac's ssh config.").foregroundStyle(.secondary)
            }
            ForEach(state.remoteHosts) { h in
                NavigationLink {
                    HostDetailView(host: h.host)
                } label: {
                    HostRow(host: h.host)
                }
            }
        } header: {
            Text("SSH hosts")
        } footer: {
            Text("Claude Code and Codex chats can work on these machines. Checking a host "
                 + "connects to it over SSH; clusters may block an address that connects "
                 + "too often, so it only happens when you ask.")
        }
        .task { await state.loadHosts() }
    }

    private var footer: String {
        switch state.harnessMode {
        case .orbit: return "Orbit's own agent answers new chats. Each harness remembers the model you last used in it."
        case .claude: return "New chats run through Claude Code. Each harness remembers the model you last used in it."
        case .codex: return "New chats run through Codex. Each harness remembers the model you last used in it."
        }
    }
}

private struct HostRow: View {
    @EnvironmentObject var state: AppState
    let host: String

    var body: some View {
        HStack {
            Label(host, systemImage: "server.rack")
            Spacer()
            if state.probing.contains(host) {
                ProgressView().controlSize(.mini)
            } else if let p = state.hostProbes[host] {
                Image(systemName: p.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(p.ok ? .green : .red)
                    .accessibilityLabel(p.ok ? "reachable" : "not reachable")
            }
        }
    }
}

/// One host: its last check, a way to check it, and its bookmarked folders.
struct HostDetailView: View {
    @EnvironmentObject var state: AppState
    let host: String
    @State private var places: FolderPlaces = .empty
    @State private var adding = ""
    @State private var note: String?

    var body: some View {
        List {
            Section {
                ProbeStatus(host: host, harness: state.harnessMode == .codex ? .codex : .claude)
                if let p = state.hostProbes[host], p.ok {
                    if let home = p.home { LabeledContent("Home", value: home).font(.callout) }
                    if let login = p.codexLogin, !login.isEmpty {
                        LabeledContent("Codex sign-in") { Text(login).font(.caption).lineLimit(2) }
                    }
                    if let s = p.secs { LabeledContent("Check took", value: String(format: "%.1f s", s)) }
                }
            } header: {
                Text("Status")
            }

            Section {
                ForEach(places.bookmarks, id: \.self) { path in
                    Text(path).font(.callout.monospaced()).lineLimit(2).textSelection(.enabled)
                }
                .onDelete { idx in
                    let gone = idx.map { places.bookmarks[$0] }
                    Task { for p in gone { await setMark(p, on: false) } }
                }
                HStack {
                    TextField("Add a folder, e.g. ~/project", text: $adding)
                        .font(.callout.monospaced())
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onSubmit { add() }
                    Button("Add", action: add)
                        .disabled(adding.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                NavigationLink {
                    RemoteFolderBrowser(host: host, start: "~") { path in
                        Task { await setMark(path, on: true) }
                    }
                } label: {
                    Label("Browse \(host) to add…", systemImage: "folder.badge.plus")
                }
                if let note { Text(note).font(.caption).foregroundStyle(.secondary) }
            } header: {
                Text("Bookmarked folders")
            } footer: {
                Text("Offered first when a chat starts on \(host). Swipe to remove one.")
            }

            if !places.recent.isEmpty {
                Section("Recently used") {
                    ForEach(places.recent, id: \.self) { path in
                        Text(path).font(.callout.monospaced()).lineLimit(2)
                            .swipeActions {
                                Button { Task { await setMark(path, on: true) } } label: {
                                    Label("Bookmark", systemImage: "star")
                                }
                                .tint(.yellow)
                            }
                    }
                }
            }
        }
        .navigationTitle(host)
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadPlaces() }
        .refreshable { await loadPlaces() }
    }

    private func add() {
        let p = adding.trimmingCharacters(in: .whitespaces)
        guard !p.isEmpty else { return }
        adding = ""
        Task { await setMark(p, on: true) }
    }

    private func loadPlaces() async {
        guard let server = state.server else { return }
        if let p = try? await server.folderPlaces(host: host) { places = p }
    }

    private func setMark(_ path: String, on: Bool) async {
        guard let server = state.server else { return }
        do {
            places.bookmarks = try await server.bookmark(host: host, path: path, on: on)
            places.recent.removeAll { places.bookmarks.contains($0) }
            note = nil
        } catch { note = error.localizedDescription }
    }
}
