import Foundation

/// The Library endpoints: saved prompts, knowledge, agents, skills, memory and
/// instructions. Every shape here is the one the Mac's `orbit-ui` sends.
extension OrbitServer {

    // ------------------------------------------------------------ plumbing

    private func libGet(_ path: String) async throws -> Data {
        try await perform(try authorisedRequest(path))
    }

    @discardableResult
    private func libPost(_ path: String, _ body: [String: Any] = [:]) async throws -> Data {
        let data = try await perform(try authorisedRequest(path, method: "POST", body: body))
        // a few endpoints answer 200 with {"error": …}
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let e = obj["error"] as? String, !e.isEmpty {
            throw Failure.server(400, e)
        }
        return data
    }

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    private static func pathSegment(_ s: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?#")
        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s
    }

    private static func queryValue(_ s: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?#")
        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s
    }

    // ------------------------------------------------------------ saved prompts

    /// Yours and the built-in ones, sorted with yours first.
    func prompts() async throws -> [SavedPrompt] {
        let data = try await libGet("/api/prompts")
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw Failure.decoding("prompts") }
        return obj.compactMap { name, value -> SavedPrompt? in
            guard let v = value as? [String: Any] else { return nil }
            return SavedPrompt(name: name, text: v["text"] as? String ?? "",
                               desc: v["desc"] as? String ?? "",
                               builtin: v["builtin"] as? Bool ?? false)
        }
        .sorted { ($0.builtin ? 1 : 0, $0.name) < ($1.builtin ? 1 : 0, $1.name) }
    }

    func savePrompt(name: String, desc: String, text: String) async throws {
        try await libPost("/api/prompts/save", ["name": name, "desc": desc, "text": text])
    }

    func deletePrompt(name: String) async throws {
        try await libPost("/api/prompts/delete", ["name": name])
    }

    // ------------------------------------------------------------ knowledge

    func knowledge() async throws -> [KnowledgeDoc] {
        try decode([KnowledgeDoc].self, try await libGet("/api/knowledge"))
    }

    /// Add a document; the Mac reindexes straight away and reports the totals.
    func uploadKnowledge(data: Data, filename: String, mime: String) async throws -> KnowledgeIndexStats {
        var r = try authorisedRequest("/api/knowledge/upload", method: "POST")
        let boundary = "orbit.\(UUID().uuidString)"
        var body = Data()
        func add(_ s: String) { body.append(Data(s.utf8)) }
        let safeName = filename.replacingOccurrences(of: "\"", with: "")
        add("--\(boundary)\r\n")
        add("Content-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\n")
        add("Content-Type: \(mime)\r\n\r\n")
        body.append(data)
        add("\r\n--\(boundary)--\r\n")
        r.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        r.httpBody = body
        r.timeoutInterval = 600               // indexing a big PDF takes a while
        let stats = try decode(KnowledgeIndexStats.self, try await perform(r))
        if let e = stats.error { throw Failure.server(400, e) }
        return stats
    }

    /// Moves the document to the bin on the Mac.
    func deleteKnowledge(name: String) async throws {
        try await libPost("/api/knowledge/delete", ["name": name])
    }

    func reindexKnowledge() async throws -> KnowledgeIndexStats {
        var r = try authorisedRequest("/api/knowledge/reindex", method: "POST", body: [:])
        r.timeoutInterval = 600
        return try decode(KnowledgeIndexStats.self, try await perform(r))
    }

    /// nil project = searched from every chat.
    func setKnowledgeProject(name: String, project: String?) async throws {
        try await libPost("/api/knowledge/project",
                          ["name": name, "project": project.map { $0 as Any } ?? NSNull()])
    }

    // ------------------------------------------------------------ agents

    func agents() async throws -> (agents: [AgentPreset], active: String?) {
        let data = try await libGet("/api/agents")
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw Failure.decoding("agents") }
        let dict = obj["agents"] as? [String: Any] ?? [:]
        let list = dict.compactMap { name, value -> AgentPreset? in
            guard let v = value as? [String: Any] else { return nil }
            return AgentPreset(name: name, instructions: v["instructions"] as? String ?? "",
                               desc: v["desc"] as? String ?? "", tools: v["tools"] as? [String])
        }.sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
        return (list, obj["active"] as? String)
    }

    /// Tools empty = every tool.
    func saveAgent(name: String, desc: String, instructions: String, tools: [String]) async throws {
        try await libPost("/api/agents/save", ["name": name, "desc": desc,
                                               "instructions": instructions, "tools": tools])
    }

    func deleteAgent(name: String) async throws {
        try await libPost("/api/agents/delete", ["name": name])
    }

    /// Every tool Orbit has, for choosing an agent's tools.
    func allTools() async throws -> [String] {
        struct I: Codable { var tools: [String]?; var all_tools: [String]? }
        let i = try decode(I.self, try await libGet("/api/info"))
        return (i.all_tools ?? i.tools ?? []).sorted()
    }

    /// What the Mac has for a chat — its agent and its own instructions.
    func chatLibraryState(sid: String) async throws -> ChatLibraryState {
        let st = try decode(ChatLibraryState.self, try await libGet("/api/state?sid=\(OrbitServer.escaped(sid))"))
        guard st.sid == sid else { throw Failure.server(409, "the Mac switched to another chat — try again") }
        return st
    }

    /// Give a chat an agent (nil clears it). Returns the tools now active.
    @discardableResult
    func selectAgent(_ name: String?, sid: String) async throws -> [String] {
        struct R: Codable { var active: String?; var tools: [String]? }
        let data = try await libPost("/api/agent/select", ["name": name ?? "", "sid": sid])
        return (try? JSONDecoder().decode(R.self, from: data))?.tools ?? []
    }

    /// This chat's own extra system prompt (blank clears it).
    func setChatInstructions(_ text: String, sid: String) async throws {
        try await libPost("/api/sysprompt", ["text": text, "sid": sid])
    }

    // ------------------------------------------------------------ skills

    func skills() async throws -> [SkillInfo] {
        try decode([SkillInfo].self, try await libGet("/api/skills"))
    }

    func skillText(name: String) async throws -> String {
        struct R: Codable { var text: String? }
        return try decode(R.self, try await libGet("/api/skill/\(Self.pathSegment(name))")).text ?? ""
    }

    /// Returns the name the Mac saved it under (it keeps letters, digits, - and _).
    @discardableResult
    func saveSkill(name: String, text: String) async throws -> String {
        struct R: Codable { var name: String? }
        let data = try await libPost("/api/skills/save", ["name": name, "text": text])
        return (try? JSONDecoder().decode(R.self, from: data))?.name ?? name
    }

    func deleteSkill(name: String) async throws {
        try await libPost("/api/skills/delete", ["name": name])
    }

    // ------------------------------------------------------------ memory and instructions

    func memories() async throws -> [MemoryNote] {
        try decode([MemoryNote].self, try await libGet("/api/memory"))
    }

    func memoryText(name: String) async throws -> String {
        struct R: Codable { var text: String? }
        return try decode(R.self, try await libGet("/api/memory/\(Self.pathSegment(name))")).text ?? ""
    }

    @discardableResult
    func saveMemory(name: String, text: String) async throws -> String {
        struct R: Codable { var name: String? }
        let data = try await libPost("/api/memory/save", ["name": name, "text": text])
        return (try? JSONDecoder().decode(R.self, from: data))?.name ?? name
    }

    func deleteMemory(name: String) async throws {
        try await libPost("/api/memory/delete", ["name": name])
    }

    /// Durable facts worth keeping from a chat — the model reads it, so it takes a moment.
    func suggestMemories(sid: String) async throws -> [SuggestedMemory] {
        struct R: Codable { var items: [SuggestedMemory]?; var error: String? }
        var req = try authorisedRequest("/api/memory/suggest", method: "POST", body: ["sid": sid])
        req.timeoutInterval = 300
        let r = try decode(R.self, try await perform(req))
        if let e = r.error, !e.isEmpty, (r.items ?? []).isEmpty { throw Failure.server(400, e) }
        return r.items ?? []
    }

    /// Standing instructions, added to every Orbit chat.
    func instructions() async throws -> String {
        struct R: Codable { var text: String? }
        return try decode(R.self, try await libGet("/api/instructions")).text ?? ""
    }

    func saveInstructions(_ text: String) async throws {
        try await libPost("/api/instructions", ["text": text])
    }

    /// The base system prompt from settings, and whether instructions and memory go in.
    func systemPromptSettings() async throws -> (prompt: String, useInstructions: Bool, useMemory: Bool) {
        struct S: Codable { var system_prompt: String?; var use_instructions: Bool?; var use_memory: Bool? }
        struct R: Codable { var settings: S }
        let r = try decode(R.self, try await libPost("/api/settings", ["settings": [String: Any]()]))
        return (r.settings.system_prompt ?? "", r.settings.use_instructions ?? false,
                r.settings.use_memory ?? false)
    }

    func setSystemPromptSettings(_ changes: [String: Any]) async throws {
        try await libPost("/api/settings", ["settings": changes])
    }

    /// Orbit's built-in system prompt, for putting it back.
    func defaultPrompt() async throws -> String {
        struct R: Codable { var text: String? }
        return try decode(R.self, try await libGet("/api/default_prompt")).text ?? ""
    }

    /// The system prompt actually sent, with instructions and memory in place.
    func systemPreview() async throws -> String {
        struct R: Codable { var text: String? }
        return try decode(R.self, try await libPost("/api/system_preview")).text ?? ""
    }

    /// Whether new chats run through Claude Code.
    func harnessMode() async throws -> Bool {
        struct R: Codable { var harness_mode: Bool? }
        return try decode(R.self, try await libGet("/api/models")).harness_mode ?? false
    }

    // ------------------------------------------------------------ Claude Code

    /// Claude Code's own slash commands and skills.
    func claudeCommands() async throws -> [ClaudeCommand] {
        struct R: Codable { var commands: [ClaudeCommand]? }
        return try decode(R.self, try await libGet("/api/claude/commands")).commands ?? []
    }

    /// Claude's instruction files and memory for a folder — the chat's folder
    /// when `cwd` is nil and a chat is given.
    func claudeMemory(sid: String?, cwd: String?) async throws -> ClaudeMemoryState {
        var path = "/api/claude/memory?sid=" + Self.queryValue(sid ?? "")
        if let cwd, !cwd.isEmpty { path += "&cwd=" + Self.queryValue(cwd) }
        return try decode(ClaudeMemoryState.self, try await libGet(path))
    }

    /// scope: user | project | project-dir | local
    func saveClaudeInstructions(scope: String, cwd: String, text: String) async throws {
        try await libPost("/api/claude/memory", ["op": "instructions", "scope": scope, "cwd": cwd, "text": text])
    }

    /// Returns true when it was a new memory (the Mac lists it in MEMORY.md).
    @discardableResult
    func saveClaudeMemory(cwd: String, file: String, text: String) async throws -> Bool {
        struct R: Codable { var new: Bool? }
        let data = try await libPost("/api/claude/memory", ["op": "save", "cwd": cwd, "file": file, "text": text])
        return (try? JSONDecoder().decode(R.self, from: data))?.new ?? false
    }

    func deleteClaudeMemory(cwd: String, file: String) async throws {
        try await libPost("/api/claude/memory", ["op": "delete", "cwd": cwd, "file": file])
    }

    func setClaudeChatInstructions(sid: String, text: String) async throws {
        try await libPost("/api/claude/memory", ["op": "chat", "sid": sid, "text": text])
    }
}
