import SwiftUI

/// Settings → Codex: the counterpart of Claude Code's. Codex on the Mac and its
/// limits, defaults for new Codex chats, AGENTS.md, machines over SSH, and
/// Codex's own skills, plugins and MCP servers.
struct CodexSettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var cfg: CodexConfig?
    @State private var hosts: [SSHHostProbe] = []
    @State private var error: String?
    @State private var note: String?
    @State private var busyHost: String?
    @State private var confirmInstall: String?
    @State private var confirmCopy: String?

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let cfg {
                mac(cfg)
                Section {
                    NavigationLink("Defaults for new Codex chats") {
                        CodexOptionsView(saved: cfg.settings, hosts: hosts.map(\.host)) { self.cfg?.settings = $0 }
                    }
                    NavigationLink("AGENTS.md") {
                        CodexAgentsView(text: cfg.agentsMD, path: cfg.agentsMDPath) { self.cfg?.agentsMD = $0 }
                    }
                    NavigationLink("Models & keys") { ModelsKeysView() }
                } footer: {
                    Text("Your ChatGPT account's models come from Codex's sign-in. Every other provider, key "
                         + "and account is shared with Orbit and Claude Code.")
                }
                machines(cfg)
                Section {
                    NavigationLink("Skills (\(cfg.skills.count))") { CodexSkillsView(skills: cfg.skills) { await load() } }
                    NavigationLink("Plugins (\(cfg.plugins.count))") { CodexPluginsView(cfg: cfg) { await load() } }
                    NavigationLink("MCP servers (\(cfg.mcp.count))") { CodexMCPView(cfg: cfg) { await load() } }
                } footer: {
                    Text("These are Codex's own, so the Codex CLI and app on the Mac see the same.")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Codex")
        .navigationBarTitleDisplayMode(.inline)
        .task { if cfg == nil { await load() } }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Install or check Codex on this machine?", isPresented: Binding(
            get: { confirmInstall != nil }, set: { if !$0 { confirmInstall = nil } }), titleVisibility: .visible) {
            if let h = confirmInstall {
                Button("Install or check on \(h)") { Task { await install(h) } }
            }
            Button("Cancel", role: .cancel) { confirmInstall = nil }
        } message: {
            Text("The Mac connects over SSH and installs the official Linux build of its own Codex version "
                 + "into ~/.local/bin there, or reports the copy already installed. It can take a minute.")
        }
        .confirmationDialog("Copy this Mac's Codex sign-in?", isPresented: Binding(
            get: { confirmCopy != nil }, set: { if !$0 { confirmCopy = nil } }), titleVisibility: .visible) {
            if let h = confirmCopy {
                Button("Copy sign-in to \(h)", role: .destructive) { Task { await copyLogin(h) } }
            }
            Button("Cancel", role: .cancel) { confirmCopy = nil }
        } message: {
            Text("Copies the Mac's Codex sign-in file (~/.codex/auth.json) to that machine, readable only by "
                 + "your account there. Administrators of that machine could still read it. Only needed "
                 + "for your ChatGPT account's models.")
        }
    }

    // MARK: sections

    @ViewBuilder private func mac(_ cfg: CodexConfig) -> some View {
        let i = cfg.info
        Section {
            LabeledContent("Installed", value: (i?.installed ?? false) ? (i?.version ?? "yes") : "no — brew install codex")
            LabeledContent("Account", value: i?.loginLine ?? "unknown")
            if let rl = i?.rateLimits {
                if let p = rl.primary { limitRow("5 hours", p) }
                if let s = rl.secondary { limitRow("Week", s) }
            }
            if cfg.tomlModel != nil || cfg.tomlEffort != nil {
                LabeledContent("Codex's own defaults",
                               value: [cfg.tomlModel.map { "model \($0)" }, cfg.tomlEffort.map { "effort \($0)" }]
                                .compactMap { $0 }.joined(separator: " · "))
            }
            LabeledContent("Running", value: (i?.running ?? false)
                           ? "yes · \(i?.chatsAnswering ?? 0) answering" : "starts with the first Codex message")
        } header: {
            Text("Codex on the Mac")
        } footer: {
            Text("To sign in or switch account, use Settings → Codex on the Mac itself, or run codex login "
                 + "in a terminal there — signing in opens a browser on the Mac, so it can't start from "
                 + "this phone. Codex's own defaults in ~/.codex/config.toml are for the Codex CLI; Orbit "
                 + "chats use the model you pick.")
        }
    }

    private func limitRow(_ name: String, _ l: CodexInfo.Limit) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(name)
                Spacer()
                Text("\(l.left)% left").monospacedDigit().foregroundStyle(.secondary)
            }
            ProgressView(value: Double(l.left), total: 100).tint(l.left < 15 ? .orange : .accentColor)
            if let r = l.resetsAt {
                Text(resetText(Date(timeIntervalSince1970: r))).font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private func machines(_ cfg: CodexConfig) -> some View {
        let running = cfg.info?.hosts ?? [:]
        let names = Array(Set(hosts.map(\.host) + running.keys)).sorted()
        Section {
            if names.isEmpty { Text("No hosts in the Mac's SSH config.").foregroundStyle(.secondary) }
            ForEach(names, id: \.self) { h in
                let probe = hosts.first { $0.host == h }
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(h).font(.body.weight(.medium))
                        Spacer()
                        if busyHost == h { ProgressView().controlSize(.mini) }
                    }
                    Text([probe?.codexLine ?? "not checked yet",
                          running[h].map { ($0.running ?? false) ? "Codex running there" : "" } ?? ""]
                            .filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        Button("Install or check") { confirmInstall = h }
                        Button("Copy sign-in") { confirmCopy = h }
                    }
                    .buttonStyle(.bordered).controlSize(.small)
                    .disabled(busyHost != nil)
                }
                .padding(.vertical, 2)
            }
        } header: {
            Text("Machines over SSH")
        } footer: {
            Text("Codex chats can run on these too.")
        }
    }

    // MARK: I/O

    private func load() async {
        do {
            let s = try state.requireServer()
            cfg = try await s.codexConfig()
            hosts = (try? await s.sshHosts()) ?? hosts
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func install(_ h: String) async {
        confirmInstall = nil
        busyHost = h
        defer { busyHost = nil }
        do {
            let r = try await state.requireServer().codexInstall(host: h)
            note = "Codex \(r.version ?? "") on \(h)" + (r.path.map { ": \($0)" } ?? "")
            await load()
        } catch { note = error.localizedDescription }
    }

    private func copyLogin(_ h: String) async {
        confirmCopy = nil
        busyHost = h
        defer { busyHost = nil }
        do {
            try await state.requireServer().codexCopyLogin(host: h)
            note = "signed in on \(h)"
            await load()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - Defaults for new Codex chats

struct CodexOptionsView: View {
    @EnvironmentObject var state: AppState
    @State var saved: JSONValue
    let hosts: [String]
    let onSaved: (JSONValue) -> Void
    @State private var draft: [String: JSONValue] = [:]
    @State private var note: String?
    @State private var saving = false
    /// The model new Codex chats start with while Codex mode is off (`codex_default`).
    @State private var codexDefault: String?

    /// In Codex mode the Mac's own default is the Codex one.
    private var defaultModelID: String? {
        state.harnessMode == .codex ? state.defaultModel : codexDefault
    }

    var body: some View {
        Form {
            Section {
                NavigationLink {
                    ModelPickerView(only: { $0.id.hasPrefix("codex:") },
                                    selected: defaultModelID,
                                    title: "Default Codex model",
                                    onPick: { m in Task { await setDefaultModel(m.id) } },
                                    embedded: true)
                } label: {
                    LabeledContent("Model", value: defaultModelID.map { id in
                        state.models.first { $0.id == id }?.display ?? id
                    } ?? "Codex mode's last model")
                }
                Picker("Permission mode", selection: string("permission_mode", "auto")) {
                    ForEach(PermissionModes.labels, id: \.id) { Text($0.label).tag($0.id) }
                }
                Picker("Reasoning effort", selection: string("default_effort", "")) {
                    Text("Codex's own").tag("")
                    ForEach(["minimal", "low", "medium", "high", "xhigh"], id: \.self) { Text($0).tag($0) }
                }
                Picker("Runs on", selection: string("default_host", "")) {
                    Text("This Mac").tag("")
                    ForEach(hostChoices, id: \.self) { Text($0).tag($0) }
                }
                TextField("Folder on the Mac (blank: Orbit workspace)", text: string("default_dir", ""))
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Picker("Scheduled runs", selection: string("unattended", "auto")) {
                    Text("Auto — Orbit's safety check decides").tag("auto")
                    Text("Refuse anything that needs approval").tag("deny")
                    Text("Allow everything (careful)").tag("allow")
                }
            } header: {
                Text("New Codex chats")
            } footer: {
                Text("Each chat can still change its own. Auto: everyday commands and edits inside the chat's "
                     + "folder run; anything risky is put to you and the unrecoverable is refused. Accept "
                     + "edits: commands ask. Plan: read-only. Bypass: no sandbox, no questions.")
            }
            Section {
                Toggle("Orbit's context", isOn: bool("orbit_context", true))
                VStack(alignment: .leading) {
                    Text("Extra instructions").font(.caption).foregroundStyle(.secondary)
                    TextEditor(text: string("developer_instructions", "")).frame(minHeight: 80)
                }
            } header: {
                Text("Instructions")
            } footer: {
                Text("Orbit's context: the project's rules and your standing instructions, as Codex developer "
                     + "instructions. Extra instructions go to every Codex chat Orbit starts.")
            }
            Section {
                Toggle("Install on a machine when needed", isOn: bool("remote_install", true))
                IntField(title: "Keep running there", value: Binding(
                    get: { value("remote_keep_alive_min")?.int ?? 30 },
                    set: { set("remote_keep_alive_min", .number(Double(max(1, min(1440, $0))))) }), suffix: "min")
            } header: {
                Text("Machines over SSH")
            } footer: {
                Text("Installs or upgrades Codex on a machine when a chat needs it. Idle Codex there is closed "
                     + "after that many minutes — login nodes limit processes.")
            }
        }
        .navigationTitle("Codex defaults")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") { Task { await save() } }.disabled(draft.isEmpty || saving)
            }
        }
        .task {
            if let s = try? await state.requireServer().settings() {
                codexDefault = s["codex_default"]?.string.flatMap { $0.isEmpty ? nil : $0 }
            }
        }
        .settingsNote($note)
    }

    /// Saved at once. In Codex mode it is the Mac's default model; otherwise
    /// the model Codex chats start with when Codex mode is turned on.
    private func setDefaultModel(_ id: String) async {
        do {
            let s = try state.requireServer()
            if state.harnessMode == .codex {
                try await s.setDefaultModel(id)
                await state.loadModels()
            } else {
                try await s.saveSettings(["codex_default": id])
                codexDefault = id
            }
            note = "default model saved"
        } catch { note = error.localizedDescription }
    }

    private var hostChoices: [String] {
        let cur = value("default_host")?.string ?? ""
        return cur.isEmpty || hosts.contains(cur) ? hosts : [cur] + hosts
    }

    private func value(_ key: String) -> JSONValue? { draft[key] ?? saved[key] }
    private func set(_ key: String, _ v: JSONValue) { if saved[key] == v { draft[key] = nil } else { draft[key] = v } }
    private func string(_ key: String, _ def: String) -> Binding<String> {
        Binding(get: { value(key)?.string ?? def }, set: { set(key, .string($0)) })
    }
    private func bool(_ key: String, _ def: Bool) -> Binding<Bool> {
        Binding(get: { value(key)?.bool ?? def }, set: { set(key, .bool($0)) })
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let out = try await state.requireServer().saveCodexOptions(draft.mapValues(\.foundation))
            saved = out
            draft = [:]
            onSaved(out)
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - AGENTS.md

struct CodexAgentsView: View {
    @EnvironmentObject var state: AppState
    @State var text: String
    let path: String?
    let onSaved: (String) -> Void
    @State private var original = ""
    @State private var confirm = false
    @State private var note: String?

    var body: some View {
        Form {
            Section {
                TextEditor(text: $text)
                    .font(.caption.monospaced())
                    .frame(minHeight: 360)
                    .autocorrectionDisabled()
            } footer: {
                Text("Read by Codex everywhere on the Mac; a folder's own AGENTS.md adds to it. "
                     + "The previous version is backed up when you save.")
            }
        }
        .navigationTitle("AGENTS.md")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { original = text }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button("Save") { confirm = true }.disabled(text == original)
            }
        }
        .confirmationDialog("Replace AGENTS.md on the Mac?", isPresented: $confirm, titleVisibility: .visible) {
            Button("Save") {
                Task {
                    do {
                        try await state.requireServer().saveCodexAgentsMD(text)
                        original = text
                        onSaved(text)
                        note = "saved (the previous version is backed up)"
                    } catch { note = error.localizedDescription }
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every Codex chat and the Codex CLI read it from the next message on.")
        }
        .settingsNote($note)
    }
}

// MARK: - Skills, plugins, MCP

struct CodexSkillsView: View {
    @EnvironmentObject var state: AppState
    @State var skills: [CodexConfig.Skill]
    let reload: () async -> Void
    @State private var source = ""
    @State private var confirmInstall = false
    @State private var removing: CodexConfig.Skill?
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        List {
            Section {
                TextField("Git URL, owner/repo or folder on the Mac", text: $source)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Button(busy ? "Installing…" : "Install") { confirmInstall = true }
                    .disabled(busy || source.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Install skills")
            }
            Section {
                if skills.isEmpty { Text("No skills in Codex's skills folder.").foregroundStyle(.secondary) }
                ForEach(skills) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.name)
                        if let d = s.description, !d.isEmpty {
                            Text(d).font(.caption2).foregroundStyle(.secondary).lineLimit(3)
                        }
                    }
                    .swipeActions { Button("Remove", role: .destructive) { removing = s } }
                }
            } footer: {
                Text("Swipe a skill to move it to the Trash on the Mac.")
            }
        }
        .navigationTitle("Codex skills")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .confirmationDialog("Install skills from this source?", isPresented: $confirmInstall, titleVisibility: .visible) {
            Button("Install") { Task { await install() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The Mac downloads it and adds its skills to Codex. Skills can run code — install only from "
                 + "sources you trust.")
        }
        .confirmationDialog("Move this Codex skill to the Trash?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            if let s = removing {
                Button("Remove \(s.name)", role: .destructive) {
                    Task {
                        do {
                            _ = try await state.requireServer().codexManage(kind: "skills", op: "remove", name: s.dir ?? s.name)
                            skills.removeAll { $0.id == s.id }
                            note = "moved to the Trash"
                            await reload()
                        } catch { note = error.localizedDescription }
                    }
                    removing = nil
                }
            }
            Button("Cancel", role: .cancel) { removing = nil }
        }
    }

    private func install() async {
        busy = true
        defer { busy = false }
        do {
            let r = try await state.requireServer().codexManage(kind: "skills", op: "install",
                                                                source: source.trimmingCharacters(in: .whitespaces))
            note = "installed: " + (r.installed ?? []).joined(separator: ", ")
            source = ""
            if let fresh = try? await state.requireServer().codexConfig() { skills = fresh.skills }
            await reload()
        } catch { note = error.localizedDescription }
    }
}

struct CodexPluginsView: View {
    @EnvironmentObject var state: AppState
    let cfg: CodexConfig
    let reload: () async -> Void
    @State private var removed: Set<String> = []
    @State private var name = ""
    @State private var marketplace = ""
    @State private var confirm: (title: String, op: String, name: String)?
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        List {
            Section {
                if let e = cfg.pluginsError { ErrorRow(message: e) }
                else if cfg.plugins.isEmpty { Text("No plugins installed.").foregroundStyle(.secondary) }
                ForEach(cfg.plugins.filter { !removed.contains($0.id) }) { p in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.id)
                        Text([(p.enabled ?? false) ? "on" : "off", p.version ?? ""].filter { !$0.isEmpty }
                                .joined(separator: " · "))
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    .swipeActions {
                        Button("Remove", role: .destructive) { confirm = ("Remove the Codex plugin \(p.id)?", "remove", p.id) }
                    }
                }
            } header: {
                Text("Installed")
            }
            Section("Install") {
                TextField("plugin@marketplace", text: $name)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Button("Install plugin") {
                    let n = name.trimmingCharacters(in: .whitespaces)
                    confirm = ("Install \(n)?", "add", n)
                }
                .disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty)
                TextField("Add a marketplace (URL or owner/repo)", text: $marketplace)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Button("Add marketplace") {
                    let n = marketplace.trimmingCharacters(in: .whitespaces)
                    confirm = ("Add the marketplace \(n)?", "marketplace", n)
                }
                .disabled(busy || marketplace.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .navigationTitle("Codex plugins")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .confirmationDialog(confirm?.title ?? "", isPresented: Binding(
            get: { confirm != nil }, set: { if !$0 { confirm = nil } }), titleVisibility: .visible) {
            if let c = confirm {
                Button(c.op == "remove" ? "Remove" : "Go ahead", role: c.op == "remove" ? .destructive : nil) {
                    Task { await act(c.op, c.name) }
                    confirm = nil
                }
            }
            Button("Cancel", role: .cancel) { confirm = nil }
        } message: {
            Text("Plugins can bring tools and MCP servers that run on the Mac.")
        }
    }

    private func act(_ op: String, _ n: String) async {
        busy = true
        defer { busy = false }
        do {
            _ = try await state.requireServer().codexManage(kind: "plugins", op: op, name: n)
            switch op {
            case "remove": removed.insert(n); note = "removed"
            case "add": name = ""; note = "installed — pull to refresh Codex to see it"
            default: marketplace = ""; note = "marketplace added"
            }
            await reload()
        } catch { note = error.localizedDescription }
    }
}

struct CodexMCPView: View {
    @EnvironmentObject var state: AppState
    let cfg: CodexConfig
    let reload: () async -> Void
    @State private var removed: Set<String> = []
    @State private var name = ""
    @State private var command = ""
    @State private var removing: CodexConfig.MCP?
    @State private var confirmAdd = false
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        List {
            Section {
                if let e = cfg.mcpError { ErrorRow(message: e) }
                else if cfg.mcp.isEmpty { Text("No MCP servers.").foregroundStyle(.secondary) }
                ForEach(cfg.mcp.filter { !removed.contains($0.name) }) { m in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(m.name)
                            if m.enabled == false { Text("off").font(.caption2).foregroundStyle(.orange) }
                        }
                        Text(m.target).font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(2)
                        if let why = m.disabled_reason { Text(why).font(.caption2).foregroundStyle(.secondary) }
                    }
                    .swipeActions { Button("Remove", role: .destructive) { removing = m } }
                }
            }
            Section {
                TextField("Name", text: $name)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                TextField("Command and arguments", text: $command, axis: .vertical)
                    .font(.callout.monospaced())
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Button("Add server") { confirmAdd = true }
                    .disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty
                              || splitCommand(command).isEmpty)
            } header: {
                Text("Add a server")
            } footer: {
                Text("For example: npx -y @modelcontextprotocol/server-filesystem ~/data. Use double quotes "
                     + "around an argument with spaces.")
            }
        }
        .navigationTitle("Codex MCP servers")
        .navigationBarTitleDisplayMode(.inline)
        .settingsNote($note)
        .confirmationDialog("Add this MCP server to Codex?", isPresented: $confirmAdd, titleVisibility: .visible) {
            Button("Add") { Task { await add() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Codex will start \(splitCommand(command).first ?? "it") on the Mac whenever a Codex chat runs.")
        }
        .confirmationDialog("Remove this MCP server from Codex?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            if let m = removing {
                Button("Remove \(m.name)", role: .destructive) {
                    Task {
                        do {
                            _ = try await state.requireServer().codexManage(kind: "mcp", op: "remove", name: m.name)
                            removed.insert(m.name)
                            note = "removed"
                            await reload()
                        } catch { note = error.localizedDescription }
                    }
                    removing = nil
                }
            }
            Button("Cancel", role: .cancel) { removing = nil }
        }
    }

    private func add() async {
        busy = true
        defer { busy = false }
        do {
            _ = try await state.requireServer().codexManage(kind: "mcp", op: "add",
                                                            name: name.trimmingCharacters(in: .whitespaces),
                                                            command: splitCommand(command))
            note = "added — pull to refresh Codex to see it"
            name = ""; command = ""
            await reload()
        } catch { note = error.localizedDescription }
    }
}
