import SwiftUI

/// Settings → Tools on the Mac: what the model may do (code, shell, writes, the
/// cluster), your own allow/deny rules, and which tools are switched on.
/// Autonomy and screen control sit on the main Settings screen.
struct ToolsRulesView: View {
    @EnvironmentObject var state: AppState
    @State private var info: ToolsInfo?
    @State private var settings: JSONValue = .object([:])
    @State private var rules = PermissionRules()
    @State private var error: String?
    @State private var note: String?
    @State private var filter = ""
    @State private var ruleKind = "deny"
    @State private var ruleTool = ""
    @State private var rulePattern = ""
    @State private var ruleNote = ""

    private var full: Bool { settings["autonomy_mode"]?.string == "full" }

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if let info {
                permissions
                rulesSection
                addRule
                if !info.toolErrors.isEmpty {
                    Section("Tools that failed to load") {
                        ForEach(info.toolErrors.keys.sorted(), id: \.self) { k in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(k).font(.callout.weight(.medium))
                                Text(info.toolErrors[k] ?? "").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                toolList(info)
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("Tools & rules")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $filter, prompt: "Filter tools")
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
    }

    // MARK: sections

    private var permissions: some View {
        Section {
            toggle("Code execution", "code_execution", def: true)
            toggle("Shell commands", "shell_enabled", def: false)
            toggle("Write access on the cluster", "cluster_write", def: false)
            toggle("Write anywhere", "write_any", def: false)
        } header: {
            Text("Permissions")
        } footer: {
            Text("Code execution: the python tool runs real code on the Mac. The cluster: qsub, qdel "
                 + "and remote commands; read-only status always works. Without write anywhere, "
                 + "writes stay in the workspace."
                 + (full ? " Shell, cluster and write anywhere are on anyway while Full access is on." : ""))
        }
    }

    private var rulesSection: some View {
        Section {
            if rules.deny.isEmpty && rules.allow.isEmpty {
                Text("No rules yet — none needed until you add one.").foregroundStyle(.secondary)
            }
            ForEach(Array(rules.deny.enumerated()), id: \.offset) { i, r in
                ruleRow("deny", r).swipeActions { removeButton("deny", i) }
            }
            ForEach(Array(rules.allow.enumerated()), id: \.offset) { i, r in
                ruleRow("allow", r).swipeActions { removeButton("allow", i) }
            }
        } header: {
            Text("Your own rules")
        } footer: {
            Text("Deny always blocks that pattern, in every autonomy mode. Allow pre-approves a match "
                 + "that would otherwise ask — it can never reach an action that is always blocked. "
                 + "Swipe a rule to remove it.")
        }
    }

    private var addRule: some View {
        Section("Add a rule") {
            Picker("Kind", selection: $ruleKind) {
                Text("Deny").tag("deny"); Text("Allow").tag("allow")
            }
            .pickerStyle(.segmented)
            TextField("Tool — * for any, or e.g. run_shell", text: $ruleTool)
                .autocorrectionDisabled().textInputAutocapitalization(.never)
            TextField("Pattern — e.g. git diff*", text: $rulePattern)
                .autocorrectionDisabled().textInputAutocapitalization(.never)
            TextField("Note (optional)", text: $ruleNote)
            Button("Add \(ruleKind) rule") { Task { await add() } }
                .disabled(rulePattern.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    @ViewBuilder private func toolList(_ info: ToolsInfo) -> some View {
        let enabled = settings["tools_enabled"]?.object ?? [:]
        let names = Array(Set(info.allTools + info.tools)).sorted()
            .filter { filter.isEmpty || $0.localizedCaseInsensitiveContains(filter) }
        ForEach(groups(names, all: info.allTools), id: \.0) { title, list in
            Section("\(title) (\(list.count))") {
                ForEach(list, id: \.self) { n in
                    Toggle(isOn: Binding(
                        get: { enabled[n]?.bool ?? true },
                        set: { on in Task { await save(["tools_enabled": [n: on]], "\(n) \(on ? "on" : "off")") } })) {
                        Text(n).font(.callout.monospaced())
                    }
                }
            }
        }
    }

    // MARK: pieces

    private func toggle(_ title: String, _ key: String, def: Bool) -> some View {
        Toggle(title, isOn: Binding(
            get: { settings[key]?.bool ?? def },
            set: { on in Task { await save([key: on], "\(title.lowercased()) \(on ? "on" : "off")") } }))
    }

    private func ruleRow(_ kind: String, _ r: PermissionRule) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(kind).font(.caption.weight(.bold))
                    .foregroundStyle(kind == "deny" ? .red : .green)
                Text(r.tool ?? "*").font(.caption.monospaced())
            }
            Text(r.pattern ?? "").font(.callout.monospaced())
            if let n = r.note, !n.isEmpty { Text(n).font(.caption).foregroundStyle(.secondary) }
        }
    }

    private func removeButton(_ kind: String, _ index: Int) -> some View {
        Button("Remove", role: .destructive) {
            Task {
                do {
                    rules = try await state.requireServer().removePermissionRule(kind: kind, index: index)
                    note = "rule removed"
                } catch { note = error.localizedDescription }
            }
        }
    }

    /// Same grouping as the web page.
    private func groups(_ names: [String], all: [String]) -> [(String, [String])] {
        let builtin: Set<String> = ["web_search", "fetch_url", "read_file", "write_file", "run_shell",
            "fetch_paper_pdf", "search_knowledge", "use_skill", "list_skills", "check_citations", "list_dir",
            "grep_files", "http_json", "pubmed_search", "arabidopsis_gene", "sequence", "cluster_status",
            "cluster_ls", "cluster_read", "cluster_run", "cluster_submit", "cluster_qdel", "alphafold",
            "uniprot", "ncbi", "remember", "python", "screen_look", "screen_click", "screen_move",
            "screen_drag", "screen_type", "screen_key", "screen_scroll"]
        var g: [String: [String]] = [:]
        for n in names {
            let key: String
            if n.hasPrefix("paperfetch_") { key = "paperfetch" }
            else if n.hasPrefix("zotero_") { key = "zotero" }
            else if (all.contains(n) && !n.contains("_")) || builtin.contains(n) { key = "built-in" }
            else { key = "other MCP" }
            g[key, default: []].append(n)
        }
        return ["built-in", "paperfetch", "zotero", "other MCP"].compactMap { k in g[k].map { (k, $0) } }
    }

    // MARK: I/O

    private func load() async {
        do {
            let i = try await state.requireServer().toolsInfo()
            info = i
            settings = i.settings ?? .object([:])
            rules = PermissionRules(json: settings["permission_rules"])
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func save(_ changes: [String: Any], _ done: String) async {
        do {
            let r = try await state.requireServer().saveSettings(changes)
            settings = r.settings
            rules = PermissionRules(json: r.settings["permission_rules"])
            info?.tools = r.tools
            info?.toolErrors = r.toolErrors
            note = done
            await state.refreshAutonomy()
        } catch { note = error.localizedDescription }
    }

    private func add() async {
        do {
            rules = try await state.requireServer().addPermissionRule(
                kind: ruleKind,
                tool: ruleTool.trimmingCharacters(in: .whitespaces).isEmpty ? "*" : ruleTool.trimmingCharacters(in: .whitespaces),
                pattern: rulePattern.trimmingCharacters(in: .whitespaces),
                note: ruleNote.trimmingCharacters(in: .whitespaces))
            rulePattern = ""; ruleNote = ""; ruleTool = ""
            note = "\(ruleKind) rule added"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}

/// Orbit's MCP servers, as the JSON config the Mac keeps (Claude's format).
struct MCPServersView: View {
    @EnvironmentObject var state: AppState
    @State private var text = ""
    @State private var original = ""
    @State private var loaded = false
    @State private var errors: [String: String] = [:]
    @State private var error: String?
    @State private var note: String?
    @State private var confirmSave = false
    @State private var saving = false

    var body: some View {
        Form {
            if let error { ErrorRow(message: error) }
            if loaded {
                Section {
                    TextEditor(text: $text)
                        .font(.caption.monospaced())
                        .frame(minHeight: 320)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } footer: {
                    Text("Same format as Claude's config: {\"mcpServers\": {name: {command, args, env}}}. "
                         + "Saving reconnects every server.")
                }
                if !errors.isEmpty {
                    Section("Connection errors") {
                        ForEach(errors.keys.sorted(), id: \.self) { k in
                            LabeledContent(k) { Text(errors[k] ?? "").font(.caption) }
                        }
                    }
                }
            } else if error == nil {
                LoadingRow()
            }
        }
        .navigationTitle("MCP servers")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                Button(saving ? "Saving…" : "Save") {
                    if parsed() != nil { confirmSave = true } else { note = "That isn't valid JSON" }
                }
                .disabled(text == original || saving)
            }
        }
        .confirmationDialog("Save and reconnect every MCP server?", isPresented: $confirmSave,
                            titleVisibility: .visible) {
            Button("Save") { Task { await save() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Anything using those tools right now loses them for a moment.")
        }
        .task { if !loaded { await load() } }
        .settingsNote($note)
    }

    private func parsed() -> Any? {
        guard let d = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return nil }
        return obj
    }

    private func load() async {
        do {
            let s = try state.requireServer()
            let data = try await s.mcpConfig()
            let obj = try JSONSerialization.jsonObject(with: data)
            let pretty = try JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            text = String(data: pretty, encoding: .utf8) ?? ""
            original = text
            errors = (try? await s.toolsInfo().toolErrors) ?? [:]
            loaded = true
            error = nil
        } catch { self.error = error.localizedDescription }
    }

    private func save() async {
        guard let cfg = parsed() else { note = "That isn't valid JSON"; return }
        saving = true
        defer { saving = false }
        do {
            errors = try await state.requireServer().saveMCPConfig(cfg)
            original = text
            note = errors.isEmpty ? "saved — servers reconnected" : "saved, with errors below"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }
}
