import SwiftUI

/// What easy mode keeps.
///
/// The phone could turn easy mode on and off but never see or choose what it left on
/// the bench — which is the whole point of it: sixty tools is a lot to offer a small
/// model, the schemas alone cost most of a modest window, and the more there are the
/// more often the wrong one is picked.
///
/// Two lists, because they are two different things: Orbit's own tool names
/// (`read_file`, `run_shell`) and Claude Code's (`Read`, `Bash`). They were once one
/// setting under one name, which meant a chat that set one had it read as the other.
struct EasyModeView: View {
    @EnvironmentObject var state: AppState
    /// Set to choose for one chat rather than for Orbit; nil edits Orbit's own.
    var sid: String?

    @State private var settings: JSONValue = .object([:])
    @State private var claude = OrbitServer.EasyTools()
    @State private var loading = true
    @State private var learning = false
    @State private var error: String?
    @State private var note: String?
    @State private var filter = ""

    private var easyOn: Bool { settings["easy_mode"]?.bool ?? false }
    private var orbitKeep: Set<String> { Set(settings["easy_tools"]?.strings ?? []) }
    private var orbitAll: [String] { (settings["_all_tools"]?.strings ?? []).sorted() }

    var body: some View {
        List {
            if let error { ErrorRow(message: error) }
            if loading { LoadingRow() } else {
                Section {
                    Toggle("Easy mode", isOn: Binding(
                        get: { easyOn },
                        set: { on in Task { await setEasy(on) } }))
                } footer: {
                    Text("Only the tools ticked below are offered. A chat can keep its own "
                         + "answer to this — that switch is in the chat's ⋯ menu; this one is "
                         + "what a chat follows when it has not set one.")
                }
                orbitSection
                claudeSection
                mcpSection
            }
        }
        .navigationTitle("Easy mode")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $filter, prompt: "Filter tools")
        .task { await load() }
        .refreshable { await load() }
        .settingsNote($note)
    }

    // MARK: the two lists

    @ViewBuilder private var orbitSection: some View {
        let names = orbitAll.filter { filter.isEmpty || $0.localizedCaseInsensitiveContains(filter) }
        if !names.isEmpty {
            Section {
                ForEach(names, id: \.self) { n in
                    Toggle(isOn: Binding(
                        get: { orbitKeep.contains(n) },
                        set: { on in Task { await toggleOrbit(n, on) } })) {
                        Text(n).font(.callout.monospaced())
                    }
                }
            } header: {
                Text("Orbit's own agent · \(orbitKeep.count) of \(orbitAll.count) kept")
            }
        }
    }

    @ViewBuilder private var claudeSection: some View {
        let names = claude.known.filter { filter.isEmpty || $0.localizedCaseInsensitiveContains(filter) }
        Section {
            if claude.known.isEmpty {
                Text("Claude Code has not said yet what tools it has.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button(learning ? "Asking…" : "Ask it now") { Task { await load(learn: true) } }
                    .disabled(learning)
            } else {
                ForEach(names, id: \.self) { n in
                    Toggle(isOn: Binding(
                        get: { claude.keep.contains(n) },
                        set: { on in Task { await toggleClaude(n, on) } })) {
                        Text(n).font(.callout.monospaced())
                    }
                }
            }
        } header: {
            Text("Claude Code · \(claude.keep.count) of \(claude.known.count) kept")
        } footer: {
            if !claude.known.isEmpty {
                Text("A name Claude Code does not have would stop a run, so only the ones it "
                     + "has said it has can be chosen.")
            }
        }
    }

    @ViewBuilder private var mcpSection: some View {
        if !claude.mcp.isEmpty {
            Section {
                ForEach(claude.mcp, id: \.self) { n in
                    Toggle(isOn: Binding(
                        get: { claude.mcpKeep.contains(n) },
                        set: { on in Task { await toggleMCP(n, on) } })) {
                        Text(n).font(.callout)
                    }
                }
            } header: {
                Text("MCP servers in easy mode")
            } footer: {
                Text("None ticked means none are started, which is usually what you want: a "
                     + "server's tools are more schemas for the model to read past.")
            }
        }
    }

    // MARK: I/O

    private func load(learn: Bool = false) async {
        if learn { learning = true }
        defer { loading = false; learning = false }
        do {
            let server = try state.requireServer()
            var s = try await server.settings()
            // every tool that exists, not only the short list this chat is being
            // offered — in easy mode those ARE the short list, and nothing could be
            // ticked back on
            let info = try await server.toolsInfo()
            let all = Array(Set(info.allTools + info.tools)).sorted()
            if case .object(var o) = s {
                o["_all_tools"] = .array(all.map { .string($0) })
                s = .object(o)
            }
            settings = s
            claude = try await server.claudeEasyTools(sid: sid, learn: learn)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func setEasy(_ on: Bool) async {
        do {
            if let sid {
                await state.setChatSetting("easy_mode", on)
                if case .object(var o) = settings { o["easy_mode"] = .bool(on); settings = .object(o) }
            } else {
                let r = try await state.requireServer().saveSettings(["easy_mode": on])
                settings = merged(r.settings)
            }
            note = on ? "easy mode on" : "easy mode off"
        } catch { note = error.localizedDescription }
    }

    private func toggleOrbit(_ name: String, _ on: Bool) async {
        var keep = orbitKeep
        if on { keep.insert(name) } else { keep.remove(name) }
        do {
            let list = keep.sorted()
            if let sid {
                await state.setChatSetting("easy_tools", list)
                if case .object(var o) = settings {
                    o["easy_tools"] = .array(list.map { .string($0) }); settings = .object(o)
                }
            } else {
                let r = try await state.requireServer().saveSettings(["easy_tools": list])
                settings = merged(r.settings)
            }
        } catch { note = error.localizedDescription }
    }

    private func toggleClaude(_ name: String, _ on: Bool) async {
        var keep = Set(claude.keep)
        if on { keep.insert(name) } else { keep.remove(name) }
        claude.keep = keep.sorted()
        do {
            // per chat it is its own setting, because the two lists are different
            // namespaces and "easy_tools" already means Orbit's
            if let sid { await state.setChatSetting("claude_easy_tools", claude.keep) }
            else { try await state.requireServer().saveClaudeOptions(["easy_tools": claude.keep]) }
        } catch { note = error.localizedDescription }
    }

    private func toggleMCP(_ name: String, _ on: Bool) async {
        var keep = Set(claude.mcpKeep)
        if on { keep.insert(name) } else { keep.remove(name) }
        claude.mcpKeep = keep.sorted()
        do { try await state.requireServer().saveClaudeOptions(["easy_mcp": claude.mcpKeep]) }
        catch { note = error.localizedDescription }
    }

    /// Keep the tool list we added to the settings object through a save.
    private func merged(_ fresh: JSONValue) -> JSONValue {
        guard case .object(var o) = fresh else { return fresh }
        o["_all_tools"] = settings["_all_tools"] ?? .array([])
        return .object(o)
    }
}
