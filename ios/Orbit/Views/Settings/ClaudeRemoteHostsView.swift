import SwiftUI

/// Settings → Claude Code → Machines over SSH: the hosts in the Mac's ssh
/// config, whether each has Claude Code, the folder new chats there start in,
/// and how long Claude Code keeps running there between messages.
struct ClaudeRemoteHostsView: View {
    @EnvironmentObject var state: AppState
    @State private var keepAlive = 30
    @State private var savedKeepAlive = 30
    @State private var dirs: [String: String] = [:]
    @State private var loaded = false
    @State private var error: String?
    @State private var note: String?

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            Section {
                IntField(title: "Keep running between messages", value: $keepAlive, suffix: "min")
                if keepAlive != savedKeepAlive {
                    Button("Save") { Task { await saveKeepAlive() } }
                }
            } footer: {
                Text("Minutes idle; 0 starts it for every message. Kept running, the next message on another "
                     + "machine starts in about a second instead of reconnecting.")
            }

            Section {
                if loaded && state.remoteHosts.isEmpty {
                    Text("No hosts in the Mac's SSH config yet.").foregroundStyle(.secondary)
                }
                ForEach(state.remoteHosts) { h in hostRow(h) }
                if !loaded { LoadingRow() }
            } header: {
                Text("Machines")
            } footer: {
                Text("A chat can run Claude Code on another machine: choose it under Where when you pick a chat's "
                     + "folder, or in New chat with…. Claude Code runs there — editing files and running commands "
                     + "on that machine — in its own process group, ended whenever the answer stops or the "
                     + "connection drops. Models come from the Mac through an SSH tunnel to Orbit's gateway; keys "
                     + "stay on the Mac. Hosts are those in the Mac's ssh config, with key-based login.")
            }
        }
        .navigationTitle("Machines over SSH")
        .navigationBarTitleDisplayMode(.inline)
        .task { if !loaded { await load() } }
        .refreshable { await load() }
        .settingsNote($note)
    }

    @ViewBuilder private func hostRow(_ h: RemoteHost) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(h.host).font(.body.weight(.medium))
                Spacer()
                if state.probing.contains(h.host) {
                    ProgressView().controlSize(.mini)
                } else {
                    Button("Check") { Task { await state.probe(host: h.host, refresh: true) } }
                        .buttonStyle(.bordered).controlSize(.small)
                }
            }
            probeLine(h)
            HStack {
                TextField("~ (home folder)", text: Binding(get: { dirs[h.host] ?? "" },
                                                           set: { dirs[h.host] = $0 }))
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                    .font(.callout)
                if (dirs[h.host] ?? "") != (h.defaultDir ?? "") {
                    Button("Save") { Task { await saveDir(h.host) } }
                        .buttonStyle(.borderless)
                }
            }
            Text("new chats there start in this folder").font(.caption2).foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder private func probeLine(_ h: RemoteHost) -> some View {
        if let e = state.probeErrors[h.host] {
            Text("not reachable: \(e)").font(.caption).foregroundStyle(.red)
        } else if let p = state.hostProbes[h.host] ?? h.probe {
            if !p.ok {
                Text("not reachable: \(p.error ?? "")").font(.caption).foregroundStyle(.red)
            } else if !p.hasClaude {
                Text("\(p.hostname ?? h.host): no Claude Code found — install it there (or open a Claude Code "
                     + "SSH session to it once)")
                    .font(.caption).foregroundStyle(.orange)
            } else {
                let procs = p.procs.map { "\($0)/\(p.procLimit.map(String.init) ?? "?") processes" }
                Text((["✓ " + (p.hostname ?? h.host), "Claude Code " + (p.claudeVersion ?? ""), procs]
                        .compactMap { $0 }.joined(separator: " · "))
                     + (p.nearProcessLimit ? " — near the limit" : ""))
                    .font(.caption).foregroundStyle(p.nearProcessLimit ? .orange : .secondary)
            }
        } else {
            Text("not checked yet").font(.caption).foregroundStyle(.secondary)
        }
    }

    // MARK: I/O

    private func load() async {
        do {
            let s = try state.requireServer()
            let info = try await s.claudeInfo()
            savedKeepAlive = info.settings["remote_keep_alive_min"]?.int ?? 30
            keepAlive = savedKeepAlive
            await state.loadHosts()
            for h in state.remoteHosts { dirs[h.host] = h.defaultDir ?? "" }
            loaded = true
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func saveKeepAlive() async {
        do {
            let out = try await state.requireServer().saveClaudeOptions(["remote_keep_alive_min": max(0, keepAlive)])
            savedKeepAlive = out["remote_keep_alive_min"]?.int ?? keepAlive
            keepAlive = savedKeepAlive
            note = "saved — the next message on another machine starts in about a second"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func saveDir(_ host: String) async {
        do {
            try await state.requireServer().saveRemoteHost(host, defaultDir:
                (dirs[host] ?? "").trimmingCharacters(in: .whitespaces))
            note = "saved"
            await state.loadHosts()
        } catch { note = error.localizedDescription }
    }
}
