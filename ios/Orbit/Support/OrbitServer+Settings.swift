import Foundation

/// The Mac's Settings, reached from the phone: providers and keys, fallback,
/// general options, tools and rules, MCP, Claude Code, Codex, phone access,
/// status and health. Every call mirrors what the web page's Settings sends.
extension OrbitServer {

    // ------------------------------------------------------------ helpers

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    private func getJSON<T: Decodable>(_ path: String, as type: T.Type,
                                       timeout: TimeInterval? = nil) async throws -> T {
        try decode(T.self, try await settingsCall(path, timeout: timeout))
    }

    private func postJSON<T: Decodable>(_ path: String, _ body: [String: Any], as type: T.Type,
                                        timeout: TimeInterval? = nil) async throws -> T {
        try decode(T.self, try await settingsCall(path, method: "POST", body: body, timeout: timeout))
    }

    /// Posts and surfaces an `error` field the Mac put in an otherwise-200 answer.
    @discardableResult
    private func postChecked(_ path: String, _ body: [String: Any],
                             timeout: TimeInterval? = nil) async throws -> JSONValue {
        let v = try await postJSON(path, body, as: JSONValue.self, timeout: timeout)
        if let e = v["error"]?.string, !e.isEmpty { throw Failure.server(400, e) }
        return v
    }

    // ------------------------------------------------------------ providers, accounts, keys

    /// `fresh` asks the Mac to re-check the Claude sign-in instead of its cached answer.
    func harness(fresh: Bool = false) async throws -> HarnessOverview {
        try await getJSON(fresh ? "/api/harness?fresh=1" : "/api/harness", as: HarnessOverview.self,
                          timeout: 60)
    }

    /// Save (or, with an empty value, remove) one secret by its key name. The
    /// value goes to the Mac only; nothing of it is kept or shown on the phone.
    func saveSecret(name: String, value: String) async throws {
        try await settingsCall("/api/secrets/save", method: "POST", body: ["secrets": [name: value]])
    }

    /// Switch on the local server of a model host on the Mac (Bionic), which keeps
    /// it off until something needs it. Returns what it says afterwards.
    @discardableResult
    func startBionic() async throws -> JSONValue {
        try await postChecked("/api/bionic/start", [:], timeout: 60)
    }

    /// Put a model into the Mac's memory now, so the next message does not wait for it.
    @discardableResult
    func loadBionic(model: String) async throws -> JSONValue {
        try await postChecked("/api/bionic/load", ["model": model], timeout: 600)
    }

    /// Give back the memory a model host on the Mac is holding. Only ever on your say-so:
    /// the host is an app you use yourself, and it reloads the model when it is next needed.
    @discardableResult
    func unloadBionic(model: String) async throws -> JSONValue {
        try await postChecked("/api/bionic/unload", ["model": model], timeout: 60)
    }

    /// add | remove | rename | activate | clear
    @discardableResult
    func harnessAccount(provider: String, op: String, id: String? = nil,
                        label: String? = nil) async throws -> JSONValue {
        var body: [String: Any] = ["provider": provider, "op": op]
        if let id { body["id"] = id }
        if let label { body["label"] = label }
        return try await postChecked("/api/harness/account", body)
    }

    /// One tiny request to a model, through the route a chat would take.
    func harnessTest(modelID: String) async throws -> HarnessTestResult {
        let data = try await settingsCall("/api/harness/test", method: "POST",
                                          body: ["id": modelID], timeout: 180)
        let r = try decode(HarnessTestResult.self, data)
        if r.ok == nil, let e = r.error { throw Failure.server(404, e) }
        return r
    }

    /// Re-read a provider's model list. Returns how many it found and any complaint.
    func harnessRefresh(provider: String) async throws -> (count: Int, note: String?) {
        let v = try await postChecked("/api/harness/refresh", ["provider": provider], timeout: 120)
        let row = v["results"]?[provider]?.array ?? []
        return (row.first?.int ?? 0, row.count > 1 ? row[1].string : nil)
    }

    /// Registry patch: `hidden`, `custom`, `proxy`, or per-provider `providers`.
    func harnessSave(_ patch: [String: Any]) async throws {
        try await postChecked("/api/harness/save", patch)
    }

    // ------------------------------------------------------------ Orbit's own model list

    func modelCatalogue() async throws -> ModelCatalogue {
        try await getJSON("/api/models", as: ModelCatalogue.self, timeout: 60)
    }

    func addClassicProvider(id: String, label: String, kind: String, baseURL: String,
                            keyName: String) async throws {
        try await postChecked("/api/model/provider", [
            "id": id,
            "provider": ["label": label, "kind": kind, "base_url": baseURL, "key": keyName],
        ])
    }

    /// Ask a provider which models it serves. Returns how many it found.
    func fetchProviderModels(_ provider: String) async throws -> Int {
        let v = try await postChecked("/api/model/fetch", ["provider": provider], timeout: 90)
        return v["found"]?.int ?? 0
    }

    func forgetModel(_ id: String) async throws {
        try await postChecked("/api/model/forget", ["id": id])
    }

    // ------------------------------------------------------------ settings

    /// All of Orbit's settings. Posting an empty change is how the Mac hands them over.
    func settings() async throws -> JSONValue {
        try await saveSettings([:]).settings
    }

    /// Merge `changes` into the Mac's settings; answers with all of them and the tools now loaded.
    @discardableResult
    func saveSettings(_ changes: [String: Any]) async throws
        -> (settings: JSONValue, tools: [String], toolErrors: [String: String]) {
        let v = try await postChecked("/api/settings", ["settings": changes])
        let errors = (v["tool_errors"]?.object ?? [:]).mapValues { $0.string ?? "\($0.foundation)" }
        return (v["settings"] ?? .object([:]), v["tools"]?.strings ?? [], errors)
    }

    func toolsInfo() async throws -> ToolsInfo {
        try await getJSON("/api/info", as: ToolsInfo.self)
    }

    /// kind: allow | deny. Answers with the rules as they now are.
    func addPermissionRule(kind: String, tool: String, pattern: String,
                           note: String) async throws -> PermissionRules {
        let v = try await postChecked("/api/permissions/add",
                                      ["kind": kind, "tool": tool, "pattern": pattern, "note": note])
        return PermissionRules(json: v["rules"])
    }

    func removePermissionRule(kind: String, index: Int) async throws -> PermissionRules {
        let v = try await postChecked("/api/permissions/remove", ["kind": kind, "index": index])
        return PermissionRules(json: v["rules"])
    }

    /// Orbit's MCP config, exactly as saved (same format as Claude's).
    func mcpConfig() async throws -> Data {
        try await settingsCall("/api/mcp")
    }

    /// Save the whole MCP config; every server reconnects. Answers with connection errors.
    func saveMCPConfig(_ config: Any) async throws -> [String: String] {
        let v = try await postChecked("/api/mcp/save", ["config": config], timeout: 120)
        return (v["tool_errors"]?.object ?? [:]).mapValues { $0.string ?? "\($0.foundation)" }
    }

    // ------------------------------------------------------------ Claude Code

    /// Orbit's options for Claude Code, the permission modes, known MCP servers.
    func claudeInfo() async throws -> ClaudeInfo {
        try await getJSON("/api/claude/info?sid=", as: ClaudeInfo.self, timeout: 60)
    }

    /// Merge options into Orbit's Claude Code settings (defaults for new chats and the rest).
    @discardableResult
    func saveClaudeOptions(_ settings: [String: Any]) async throws -> JSONValue {
        let v = try await postChecked("/api/claude/settings", ["settings": settings])
        return v["settings"] ?? .object([:])
    }

    func claudeConfig() async throws -> ClaudeConfig {
        try await getJSON("/api/claude/config", as: ClaudeConfig.self, timeout: 60)
    }

    /// Patch Claude's own settings file (a key set to null is removed).
    func patchClaudeSettings(_ patch: [String: Any]) async throws {
        try await postChecked("/api/claude/claude_settings", ["patch": patch, "scope": "user"])
    }

    func claudeSkill(op: String, name: String? = nil, on: Bool? = nil,
                     source: String? = nil) async throws -> CLIOutcome {
        var body: [String: Any] = ["op": op]
        if let name { body["name"] = name }
        if let on { body["on"] = on }
        if let source { body["source"] = source }
        let r = try await postJSON("/api/claude/skills", body, as: CLIOutcome.self, timeout: 300)
        if let e = r.error, !e.isEmpty { throw Failure.server(400, e) }
        return r
    }

    func claudePlugins() async throws -> ClaudePlugins {
        try await getJSON("/api/claude/plugins", as: ClaudePlugins.self, timeout: 90)
    }

    /// enable | disable | install | uninstall | update | marketplace_add
    func claudePlugin(op: String, name: String) async throws -> CLIOutcome {
        let r = try await postJSON("/api/claude/plugins", ["op": op, "name": name],
                                   as: CLIOutcome.self, timeout: 320)
        if let e = r.error, !e.isEmpty { throw Failure.server(400, e) }
        return r
    }

    func claudeMCP() async throws -> ClaudeMCPList {
        try await getJSON("/api/claude/mcp", as: ClaudeMCPList.self, timeout: 90)
    }

    func removeClaudeMCP(name: String) async throws -> CLIOutcome {
        let r = try await postJSON("/api/claude/mcp", ["op": "remove", "name": name, "scope": "user"],
                                   as: CLIOutcome.self, timeout: 90)
        if let e = r.error, !e.isEmpty { throw Failure.server(400, e) }
        return r
    }

    // ------------------------------------------------------------ Codex

    func codexInfo() async throws -> CodexInfo {
        try await getJSON("/api/codex/info", as: CodexInfo.self, timeout: 60)
    }

    /// Install Codex on an SSH host, or check the copy already there.
    func codexInstall(host: String) async throws -> HostActionResult {
        let r = try await postJSON("/api/codex/install", ["host": host], as: HostActionResult.self, timeout: 600)
        if r.ok == false || r.ok == nil { throw Failure.server(400, r.error ?? r.why ?? "the install failed") }
        return r
    }

    /// Copy this Mac's Codex sign-in to an SSH host.
    func codexCopyLogin(host: String) async throws {
        let r = try await postJSON("/api/codex/copy_login", ["host": host], as: HostActionResult.self, timeout: 120)
        if r.ok != true { throw Failure.server(400, r.error ?? r.why ?? "the copy failed") }
    }

    /// The SSH hosts the Mac knows about and what it last found on each. Read only.
    func sshHosts() async throws -> [SSHHostProbe] {
        struct R: Decodable { var hosts: [SSHHostProbe]? }
        return try await getJSON("/api/remote/hosts", as: R.self, timeout: 30).hosts ?? []
    }

    /// Everything the Codex settings screen shows: Orbit's options, Codex's own
    /// state, AGENTS.md, skills, plugins and MCP servers.
    func codexConfig() async throws -> CodexConfig {
        try await getJSON("/api/codex/config", as: CodexConfig.self, timeout: 90)
    }

    @discardableResult
    func saveCodexOptions(_ settings: [String: Any]) async throws -> JSONValue {
        let v = try await postChecked("/api/codex/settings", ["settings": settings])
        return v["settings"] ?? .object([:])
    }

    /// Replace ~/.codex/AGENTS.md on the Mac (it backs up the previous one).
    func saveCodexAgentsMD(_ text: String) async throws {
        try await postChecked("/api/codex/agents_md", ["text": text])
    }

    /// kind: skills (install source / remove name), plugins (add / remove / marketplace name),
    /// mcp (add name + command argv / remove name).
    func codexManage(kind: String, op: String, name: String? = nil, source: String? = nil,
                     command: [String]? = nil) async throws -> CLIOutcome {
        var body: [String: Any] = ["kind": kind, "op": op]
        if let name { body["name"] = name }
        if let source { body["source"] = source }
        if let command { body["command"] = command }
        let r = try await postJSON("/api/codex/manage", body, as: CLIOutcome.self, timeout: 320)
        if r.ok == false || (r.ok == nil && r.error != nil) {
            throw Failure.server(400, r.error ?? r.output ?? "Codex refused")
        }
        return r
    }

    // ------------------------------------------------------------ phone access

    func remoteAccess() async throws -> RemoteAccess {
        try await getJSON("/api/remote", as: RemoteAccess.self)
    }

    /// off | tailscale | lan. Takes effect when Orbit restarts.
    func setRemoteMode(_ mode: String) async throws {
        try await postChecked("/api/remote/mode", ["mode": mode])
    }

    /// New pairing token: every paired device has to scan again.
    func rotateRemoteToken() async throws {
        try await postChecked("/api/remote/rotate", [:])
    }

    // ------------------------------------------------------------ status and health

    func serverDetail() async throws -> ServerDetail {
        try await getJSON("/api/status", as: ServerDetail.self)
    }

    func healthCheck() async throws -> [HealthRow] {
        try await getJSON("/api/health", as: [HealthRow].self, timeout: 90)
    }

    func aboutMac() async throws -> AboutMac {
        try await getJSON("/api/about", as: AboutMac.self, timeout: 60)
    }

    func codeStatus() async throws -> CodeStatus {
        try await getJSON("/api/code", as: CodeStatus.self)
    }

    /// Restart Orbit on the Mac. It waits for running answers unless forced;
    /// the message says which happened.
    func restartOrbit(force: Bool = false) async throws -> String {
        let v = try await postChecked("/api/restart_ui", force ? ["force": true] : [:])
        return v["msg"]?.string ?? "restarting"
    }

    /// Permanently delete what has been in the bin longer than the Mac keeps things.
    func purgeExpiredTrash() async throws -> Int {
        let v = try await postChecked("/api/trash/purge", [:])
        return v["purged"]?.int ?? 0
    }
}
