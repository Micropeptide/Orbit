import SwiftUI

/// Settings → Claude Code: Orbit's defaults for new Claude Code chats and its
/// launcher options, plus Claude's own permissions, skills, plugins and MCP
/// servers — changed in Claude itself, so the terminal sees them too.
struct ClaudeCodeSettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var info: ClaudeInfo?
    @State private var error: String?

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            Section {
                if let info {
                    LabeledContent("Claude Code", value: info.installed ? (info.version ?? "installed") : "not installed")
                } else if error == nil {
                    LoadingRow()
                }
                NavigationLink("Models & keys") { ModelsKeysView() }
            } footer: {
                Text("Providers, accounts and keys are shared with Orbit's own chat and Codex. Every model "
                     + "there runs through Claude Code in Claude Code mode.")
            }
            Section {
                NavigationLink("Defaults for new chats") { ClaudeOptionsView() }
                NavigationLink("Claude's permissions") { ClaudePermissionsView() }
                NavigationLink("Machines over SSH") { ClaudeRemoteHostsView() }
            }
            Section {
                NavigationLink("Skills") { ClaudeSkillsView() }
                NavigationLink("Plugins") { ClaudePluginsView() }
                NavigationLink("MCP servers") { ClaudeMCPView() }
            } footer: {
                Text("These are Claude's own — the same the claude command sees in a terminal on the Mac.")
            }
        }
        .navigationTitle("Claude Code")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        do { info = try await state.requireServer().claudeInfo(); error = nil }
        catch { self.error = error.localizedDescription }
    }
}

// MARK: - Orbit's options for Claude Code

struct ClaudeOptionsView: View {
    @EnvironmentObject var state: AppState
    @State private var info: ClaudeInfo?
    @State private var hosts: [String] = []
    @State private var draft: [String: JSONValue] = [:]
    @State private var error: String?
    @State private var note: String?
    @State private var saving = false

    private var c: JSONValue { info?.settings ?? .object([:]) }

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            if let info {
                Section {
                    // saved at once, like the web page's model menu: it is the Mac's
                    // default model, not one of these options
                    NavigationLink {
                        ModelPickerView(only: { $0.id.hasPrefix("harness:") || $0.id.hasPrefix("claude-qwen") },
                                        selected: state.defaultModel,
                                        title: "Default model",
                                        onPick: { m in Task { await setDefaultModel(m.id) } },
                                        embedded: true)
                    } label: {
                        LabeledContent("Model", value: state.models.first { $0.id == state.defaultModel }?.display
                                       ?? "choose")
                    }
                    Picker("Permission mode", selection: string("permission_mode")) {
                        Text("Claude's own").tag("")
                        ForEach(PermissionModes.labels, id: \.id) { Text($0.label).tag($0.id) }
                    }
                    Picker("Reasoning effort", selection: string("default_effort")) {
                        Text("Claude's own").tag("")
                        ForEach(["low", "medium", "high", "xhigh", "max"], id: \.self) { Text($0).tag($0) }
                    }
                    Picker("Runs on", selection: string("default_host")) {
                        Text("This Mac").tag("")
                        ForEach(hostChoices, id: \.self) { Text($0 + " (SSH)").tag($0) }
                    }
                    TextField("Folder on the Mac (blank: Orbit workspace)", text: string("default_dir"))
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                } header: {
                    Text("Defaults for new chats")
                } footer: {
                    Text("Each chat can still change its own. Auto: Claude decides which actions are safe "
                         + "to run without asking, and asks for the rest. The model is saved as soon as you "
                         + "pick it.")
                }

                Section {
                    Picker("Profile", selection: Binding(
                        get: { (value("profile")?.string ?? "standard") == "lean" ? "lean" : "standard" },
                        set: { set("profile", .string($0)) })) {
                        Text("Standard — Claude as set up").tag("standard")
                        Text("Lean — built-in tools and skills only").tag("lean")
                    }
                    mcpToggles(info)
                    TextField("Tools turned off, comma separated", text: list("disallowed_tools"), axis: .vertical)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                        .font(.callout)
                } header: {
                    Text("claude-qwen launcher")
                } footer: {
                    Text("Keep all MCP servers unless you need a short prompt: a shorter list also leaves out "
                         + "the servers plugins bring, while their hooks still run. WebSearch needs "
                         + "Anthropic's servers and cannot work on a local model.")
                }

                Section("In Orbit") {
                    Picker("Unattended runs", selection: string("unattended_mode")) {
                        Text("Same as the chat").tag("")
                        Text("Accept file edits").tag("acceptEdits")
                        Text("Don't ask (Claude's rules only)").tag("dontAsk")
                        Text("Bypass — allow everything").tag("bypassPermissions")
                    }
                    Picker("\"Don't ask again\" saves to", selection: Binding(
                        get: { value("rule_destination")?.string ?? "suggested" },
                        set: { set("rule_destination", .string($0)) })) {
                        Text("Where Claude suggests").tag("suggested")
                        Text("Folder's settings.local.json").tag("localSettings")
                        Text("Folder's settings.json").tag("projectSettings")
                        Text("User settings").tag("userSettings")
                        Text("This session only").tag("session")
                    }
                    Toggle("List terminal sessions", isOn: bool("history", true))
                    Toggle("…on any model", isOn: bool("history_all_models", false))
                }

                Section {
                    Toggle("Orbit's safety rules", isOn: bool("orbit_rules", false))
                    Toggle("Orbit's tools", isOn: bool("orbit_tools", false))
                    Toggle("Project tools", isOn: bool("project_tools", false))
                    Toggle("Skill routing", isOn: bool("skill_routing", false))
                    TextField("Always-offered skills, comma separated", text: list("core_skills"), axis: .vertical)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    Toggle("Skill hints", isOn: bool("skill_hint", false))
                    Toggle("Orbit's skills", isOn: bool("orbit_skills", false))
                    Toggle("Orbit's context", isOn: bool("orbit_context", false))
                    Toggle("Message times", isOn: bool("message_time", false))
                    VStack(alignment: .leading) {
                        Text("Extra instructions").font(.caption).foregroundStyle(.secondary)
                        TextEditor(text: string("append_system")).frame(minHeight: 80)
                    }
                } header: {
                    Text("Orbit extras")
                } footer: {
                    Text("Each adds something Claude itself would not do: Orbit's rules and autonomy on top of "
                         + "Claude's; memory, chat search and scheduling tools; a trusted project's own tools; "
                         + "offering only matching skills; Orbit's saved skills as a plugin; project rules in "
                         + "the prompt; when each message was sent.")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Claude Code defaults")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") { Task { await save() } }
                    .disabled(draft.isEmpty || saving)
            }
        }
        .task { if info == nil { await load() } }
        .settingsNote($note)
    }

    private var hostChoices: [String] {
        let cur = value("default_host")?.string ?? ""
        return cur.isEmpty || hosts.contains(cur) ? hosts : [cur] + hosts
    }

    @ViewBuilder private func mcpToggles(_ info: ClaudeInfo) -> some View {
        let chosen = Set(value("mcp_servers")?.strings ?? ["*"])
        Toggle("All MCP servers", isOn: Binding(
            get: { chosen.contains("*") },
            set: { on in
                var s = chosen
                if on { s.insert("*") } else { s.remove("*") }
                set("mcp_servers", .array(s.sorted().map { .string($0) }))
            }))
        if !chosen.contains("*") {
            ForEach(info.mcpKnown, id: \.self) { n in
                Toggle(n, isOn: Binding(
                    get: { chosen.contains(n) },
                    set: { on in
                        var s = chosen
                        if on { s.insert(n) } else { s.remove(n) }
                        set("mcp_servers", .array(s.sorted().map { .string($0) }))
                    }))
                .padding(.leading, 12)
            }
        }
    }

    // MARK: bindings

    private func value(_ key: String) -> JSONValue? { draft[key] ?? c[key] }

    private func set(_ key: String, _ v: JSONValue) {
        if c[key] == v { draft[key] = nil } else { draft[key] = v }
    }

    private func string(_ key: String) -> Binding<String> {
        Binding(get: { value(key)?.string ?? "" }, set: { set(key, .string($0)) })
    }

    private func bool(_ key: String, _ def: Bool) -> Binding<Bool> {
        Binding(get: { value(key)?.bool ?? def }, set: { set(key, .bool($0)) })
    }

    /// A list edited as comma-separated text.
    private func list(_ key: String) -> Binding<String> {
        Binding(get: { (value(key)?.strings ?? []).joined(separator: ", ") },
                set: { t in
                    let items = t.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                        .filter { !$0.isEmpty }
                    set(key, .array(items.map { .string($0) }))
                })
    }

    private func load() async {
        do {
            let s = try state.requireServer()
            info = try await s.claudeInfo()
            hosts = ((try? await s.sshHosts()) ?? []).map(\.host)
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func setDefaultModel(_ id: String) async {
        do {
            try await state.requireServer().setDefaultModel(id)
            await state.loadModels()
            note = "default model saved"
        } catch { note = error.localizedDescription }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        do {
            let out = try await state.requireServer().saveClaudeOptions(draft.mapValues(\.foundation))
            info?.settings = out
            draft = [:]
            note = "saved — applies from the next message"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - Claude's own permissions

struct ClaudePermissionsView: View {
    @EnvironmentObject var state: AppState
    @State private var loaded = false
    @State private var mode = ""
    @State private var allow = ""
    @State private var ask = ""
    @State private var deny = ""
    @State private var dirs = ""
    @State private var hooks = true
    @State private var error: String?
    @State private var note: String?
    @State private var saving = false

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            if loaded {
                Section {
                    Picker("Default mode", selection: $mode) {
                        Text("Default (ask)").tag("")
                        ForEach(PermissionModes.labels.filter { $0.id != "default" }, id: \.id) {
                            Text($0.label).tag($0.id)
                        }
                    }
                    Toggle("Run hooks", isOn: $hooks)
                } footer: {
                    Text("Run hooks: the hooks in Claude's settings run (disableAllHooks off).")
                }
                rules("Allow", $allow, "one rule per line, e.g. Bash(git diff:*)")
                rules("Ask", $ask, "one rule per line")
                rules("Deny", $deny, "one rule per line")
                rules("Extra folders", $dirs, "additionalDirectories, one per line")
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Claude's permissions")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") { Task { await save() } }.disabled(!loaded || saving)
            }
        }
        .task { if !loaded { await load() } }
        .settingsNote($note)
    }

    private func rules(_ title: String, _ text: Binding<String>, _ hint: String) -> some View {
        Section {
            TextEditor(text: text)
                .font(.caption.monospaced())
                .frame(minHeight: 70)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
        } header: {
            Text(title)
        } footer: {
            Text(hint)
        }
    }

    private func lines(_ v: JSONValue?) -> String { (v?.strings ?? []).joined(separator: "\n") }
    private func unlines(_ s: String) -> [String] {
        s.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private func load() async {
        do {
            let cfg = try await state.requireServer().claudeConfig()
            let perm = cfg.user["permissions"]
            let m = perm?["defaultMode"]?.string ?? ""
            mode = m == "default" ? "" : m
            allow = lines(perm?["allow"]); ask = lines(perm?["ask"]); deny = lines(perm?["deny"])
            dirs = lines(perm?["additionalDirectories"])
            hooks = !(cfg.user["disableAllHooks"]?.bool ?? false)
            loaded = true
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func save() async {
        saving = true
        defer { saving = false }
        let patch: [String: Any] = [
            "permissions": [
                "defaultMode": mode.isEmpty ? NSNull() : mode as Any,
                "allow": unlines(allow), "ask": unlines(ask), "deny": unlines(deny),
                "additionalDirectories": unlines(dirs),
            ],
            "disableAllHooks": hooks ? NSNull() : true as Any,
        ]
        do {
            try await state.requireServer().patchClaudeSettings(patch)
            note = "saved to Claude — applies to its next session"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - Skills

struct ClaudeSkillsView: View {
    @EnvironmentObject var state: AppState
    @State private var skills: [ClaudeSkill] = []
    @State private var loaded = false
    @State private var filter = ""
    @State private var source = ""
    @State private var confirmInstall = false
    @State private var removing: ClaudeSkill?
    @State private var busy = false
    @State private var error: String?
    @State private var note: String?

    private var shown: [ClaudeSkill] {
        filter.isEmpty ? skills : skills.filter {
            $0.name.localizedCaseInsensitiveContains(filter)
                || ($0.description ?? "").localizedCaseInsensitiveContains(filter)
        }
    }

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            Section {
                TextField("Git URL, owner/repo or folder on the Mac", text: $source)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                Button(busy ? "Installing…" : "Install") { confirmInstall = true }
                    .disabled(busy || source.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Install skills")
            } footer: {
                Text("Every folder with a SKILL.md becomes one skill in Claude's skills folder on the Mac.")
            }
            if loaded {
                Section {
                    ForEach(shown.prefix(400)) { s in
                        Toggle(isOn: Binding(get: { s.enabled }, set: { on in Task { await toggle(s, on) } })) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(s.name)
                                if let d = s.description, !d.isEmpty {
                                    Text(d).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                                }
                            }
                        }
                        .swipeActions { Button("Remove", role: .destructive) { removing = s } }
                    }
                    if shown.count > 400 {
                        Text("… \(shown.count - 400) more — filter to find them").foregroundStyle(.secondary)
                    }
                } header: {
                    Text("\(skills.count) skills · \(skills.filter { !$0.enabled }.count) turned off")
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Claude skills")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $filter, prompt: "Filter skills")
        .task { if !loaded { await load() } }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Install skills from this source?", isPresented: $confirmInstall,
                            titleVisibility: .visible) {
            Button("Install") { Task { await install() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The Mac downloads \(source) and adds its skills to Claude. Skills can run code — "
                 + "install only from sources you trust.")
        }
        .confirmationDialog("Move this skill to the Trash?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            if let s = removing {
                Button("Remove \(s.name)", role: .destructive) {
                    Task {
                        do {
                            _ = try await state.requireServer().claudeSkill(op: "remove", name: s.name)
                            skills.removeAll { $0.name == s.name }
                            note = "moved to the Trash"
                        } catch { note = error.localizedDescription }
                    }
                    removing = nil
                }
            }
            Button("Cancel", role: .cancel) { removing = nil }
        }
    }

    private func load() async {
        do { skills = try await state.requireServer().claudeConfig().skills; loaded = true; error = nil }
        catch { self.error = error.localizedDescription }
    }

    private func toggle(_ s: ClaudeSkill, _ on: Bool) async {
        do {
            _ = try await state.requireServer().claudeSkill(op: "toggle", name: s.name, on: on)
            if let i = skills.firstIndex(of: s) { skills[i].enabled = on }
        } catch { note = error.localizedDescription }
    }

    private func install() async {
        busy = true
        defer { busy = false }
        do {
            let r = try await state.requireServer().claudeSkill(op: "install", source: source.trimmingCharacters(in: .whitespaces))
            note = "installed: " + (r.installed ?? []).joined(separator: ", ")
                + ((r.skipped ?? []).isEmpty ? "" : " · already there: " + (r.skipped ?? []).joined(separator: ", "))
            source = ""
            await load()
        } catch { note = error.localizedDescription }
    }
}

// MARK: - Plugins

struct ClaudePluginsView: View {
    @EnvironmentObject var state: AppState
    @State private var data: ClaudePlugins?
    @State private var error: String?
    @State private var output: String?
    @State private var busy: String?
    @State private var pluginName = ""
    @State private var marketplace = ""
    @State private var confirm: (title: String, op: String, name: String)?

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let d = data {
                Section {
                    if d.plugins.isEmpty { Text(d.error ?? "No plugins installed").foregroundStyle(.secondary) }
                    ForEach(d.plugins) { p in
                        HStack {
                            Toggle(isOn: Binding(
                                get: { p.enabled ?? false },
                                set: { on in Task { await act(on ? "enable" : "disable", p.id) } })) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(p.id).lineLimit(1)
                                    Text([p.version ?? "", p.scope ?? ""].filter { !$0.isEmpty }.joined(separator: " · "))
                                        .font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .disabled(busy != nil)
                        .swipeActions {
                            Button("Uninstall", role: .destructive) {
                                confirm = ("Uninstall \(p.id)?", "uninstall", p.id)
                            }
                            Button("Update") { Task { await act("update", p.id) } }.tint(.blue)
                        }
                    }
                } header: {
                    Text("Installed")
                } footer: {
                    Text("Swipe a plugin to update or uninstall it.")
                }

                Section("Install a plugin") {
                    TextField("plugin@marketplace", text: $pluginName)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    Button("Install") {
                        let n = pluginName.trimmingCharacters(in: .whitespaces)
                        confirm = ("Install \(n)?", "install", n)
                    }
                    .disabled(busy != nil || pluginName.trimmingCharacters(in: .whitespaces).isEmpty)
                }

                Section {
                    ForEach(d.marketplaces) { m in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(m.name)
                            if let r = m.repo ?? m.source { Text(r).font(.caption2).foregroundStyle(.secondary) }
                        }
                    }
                    TextField("Add a marketplace (URL or owner/repo)", text: $marketplace)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                    Button("Add marketplace") {
                        let n = marketplace.trimmingCharacters(in: .whitespaces)
                        confirm = ("Add the marketplace \(n)?", "marketplace_add", n)
                    }
                    .disabled(busy != nil || marketplace.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Marketplaces")
                }

                if busy != nil || output != nil {
                    Section("Claude says") {
                        if let b = busy { LoadingRow(text: "\(b)…") }
                        if let o = output, !o.isEmpty {
                            Text(o).font(.caption.monospaced()).textSelection(.enabled)
                        }
                    }
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Claude plugins")
        .navigationBarTitleDisplayMode(.inline)
        .task { if data == nil { await load() } }
        .refreshable { await load() }
        .confirmationDialog(confirm?.title ?? "", isPresented: Binding(
            get: { confirm != nil }, set: { if !$0 { confirm = nil } }), titleVisibility: .visible) {
            if let c = confirm {
                Button(c.op == "uninstall" ? "Uninstall" : "Go ahead",
                       role: c.op == "uninstall" ? .destructive : nil) {
                    Task { await act(c.op, c.name) }
                    confirm = nil
                }
            }
            Button("Cancel", role: .cancel) { confirm = nil }
        } message: {
            Text("Plugins can bring hooks, tools and MCP servers that run on the Mac. "
                 + "Changes apply to Claude's next session.")
        }
    }

    private func load() async {
        do { data = try await state.requireServer().claudePlugins(); error = nil }
        catch { self.error = error.localizedDescription }
    }

    private func act(_ op: String, _ name: String) async {
        busy = op
        output = nil
        do {
            let r = try await state.requireServer().claudePlugin(op: op, name: name)
            output = r.output ?? (r.ok == true ? "\(op) done" : "\(op) failed")
            if op == "install" { pluginName = "" }
            if op == "marketplace_add" { marketplace = "" }
        } catch { output = error.localizedDescription }
        busy = nil
        await load()
    }
}

// MARK: - MCP servers

struct ClaudeMCPView: View {
    @EnvironmentObject var state: AppState
    @State private var list: ClaudeMCPList?
    @State private var error: String?
    @State private var note: String?
    @State private var removing: ClaudeMCPServer?

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let l = list {
                Section {
                    if (l.servers ?? []).isEmpty { Text(l.error ?? "None").foregroundStyle(.secondary) }
                    ForEach(l.servers ?? []) { m in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack {
                                Circle().fill(healthy(m) ? Color.green : Color.orange).frame(width: 8, height: 8)
                                Text(m.name)
                                Spacer()
                                Text(m.status ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                            if let t = m.target {
                                Text(t).font(.caption2.monospaced()).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        .swipeActions { Button("Remove", role: .destructive) { removing = m } }
                    }
                } footer: {
                    Text("Health as claude mcp list reports it. Add servers with claude mcp add in a "
                         + "terminal on the Mac, or ask Claude to.")
                }
            } else if error == nil {
                LoadingRow(text: "Checking each server")
            }
        }
        .navigationTitle("Claude MCP servers")
        .navigationBarTitleDisplayMode(.inline)
        .task { if list == nil { await load() } }
        .refreshable { await load() }
        .settingsNote($note)
        .confirmationDialog("Remove this MCP server from Claude?", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            if let m = removing {
                Button("Remove \(m.name)", role: .destructive) {
                    Task {
                        do {
                            let r = try await state.requireServer().removeClaudeMCP(name: m.name)
                            note = r.ok == true ? "removed" : (r.output ?? "Claude refused")
                            await load()
                        } catch { note = error.localizedDescription }
                    }
                    removing = nil
                }
            }
            Button("Cancel", role: .cancel) { removing = nil }
        }
    }

    private func healthy(_ m: ClaudeMCPServer) -> Bool {
        let s = (m.status ?? "").lowercased()
        return s.contains("connected") && !s.contains("fail") && !s.contains("not")
    }

    private func load() async {
        do { list = try await state.requireServer().claudeMCP(); error = nil }
        catch { self.error = error.localizedDescription }
    }
}
