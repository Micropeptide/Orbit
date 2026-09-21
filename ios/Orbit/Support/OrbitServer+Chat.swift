import Foundation

/// Chat actions and chat-list management, spoken exactly as the Mac's web UI
/// speaks them. Every endpoint here answers JSON; a refusal comes back as
/// `{"error": ...}` (often with a 4xx), which is surfaced as that message.
extension OrbitServer {

    // ------------------------------------------------------------ plumbing

    /// POST and read the answer as a dictionary. A 4xx with `{"error"}`, or
    /// `{"ok": false}`, throws the Mac's own words rather than raw JSON.
    @discardableResult
    func postJSON(_ path: String, _ body: [String: Any] = [:],
                  timeout: TimeInterval? = nil) async throws -> [String: Any] {
        var req = try request(path, method: "POST", body: body)
        if let timeout { req.timeoutInterval = timeout }
        let data: Data
        do {
            data = try await run(req)
        } catch Failure.server(let code, let raw) {
            throw Failure.server(code, Self.errorText(raw))
        }
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if let e = obj["error"] as? String, !e.isEmpty { throw Failure.server(400, e) }
        if (obj["ok"] as? Bool) == false { throw Failure.server(400, "the Mac did not do that") }
        return obj
    }

    func getJSON(_ path: String) async throws -> Any {
        let data: Data
        do {
            data = try await run(try request(path))
        } catch Failure.server(let code, let raw) {
            throw Failure.server(code, Self.errorText(raw))
        }
        guard let obj = try? JSONSerialization.jsonObject(with: data) else {
            throw Failure.decoding(path)
        }
        return obj
    }

    nonisolated static func errorText(_ raw: String) -> String {
        if let d = raw.data(using: .utf8),
           let o = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
           let e = o["error"] as? String { return e }
        return raw
    }

    nonisolated static func escaped(_ s: String) -> String {
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "&=+?#")
        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s
    }

    // ------------------------------------------------------------ mid-answer

    /// Reply to a question the model asked. Several picks go as a list.
    func answerQuestion(_ id: String, answer: [String], multiple: Bool) async throws {
        let value: Any = multiple ? answer : (answer.first ?? "")
        try await postJSON("/api/answer", ["id": id, "answer": value])
    }

    func approve(_ id: String, reply: ApprovalReply) async throws {
        var body = reply.body
        body["id"] = id
        try await postJSON("/api/approve", body)
    }

    /// Answering chats, and those waiting on you (an approval or a question).
    func runningState() async throws -> (running: Set<String>, waiting: Set<String>) {
        struct R: Codable { var running: [String]?; var waiting: [String]? }
        let r = try await get("/api/running", as: R.self)
        return (Set(r.running ?? []), Set(r.waiting ?? []))
    }

    /// The live buffer with any open question or approval in it, so a chat
    /// joined mid-answer can still be answered from here.
    func livePrompts(_ sid: String) async throws -> (question: AskQuestion?, approval: ApprovalPrompt?) {
        let obj = try await getJSON("/api/live/\(sid)") as? [String: Any] ?? [:]
        return (AskQuestion(obj["question"] as? [String: Any]),
                ApprovalPrompt(obj["approval"] as? [String: Any]))
    }

    // ------------------------------------------------------------ per message

    /// A new chat holding everything before the user message at `index`
    /// (counted among user messages). Returns its id.
    func branch(_ sid: String, userIndex index: Int) async throws -> String {
        let r = try await postJSON("/api/branch", ["id": sid, "index": index])
        guard let new = r["sid"] as? String, !new.isEmpty else { throw Failure.decoding("branch") }
        return new
    }

    /// Remove the last answer and the question before it on the Mac; returns
    /// that question's text to be sent again.
    func regenerateOnMac(sid: String, deeper: Bool) async throws -> String {
        let r = try await postJSON(deeper ? "/api/retry_harder" : "/api/regenerate", ["sid": sid])
        if let s = r["content"] as? String { return s }
        if let parts = r["content"] as? [[String: Any]] {
            return parts.compactMap { $0["type"] as? String == "text" ? $0["text"] as? String : nil }
                .joined(separator: " ")
        }
        throw Failure.server(400, "nothing to retry")
    }

    /// The message that asks a stopped answer to carry on.
    func continueMessage() async throws -> String {
        let r = try await postJSON("/api/continue", [:])
        return (r["message"] as? String) ?? "Continue from where you stopped."
    }

    /// Put back the files one answer changed. Returns what the Mac did.
    func undoChanges(sid: String, t: Double) async throws -> [String] {
        let r = try await postJSON("/api/undo_changes", ["sid": sid, "t": t])
        return ((r["done"] as? [Any]) ?? []).map { "\($0)" }
    }

    /// Saved versions of a file, newest first. `rel` may be a path the Mac
    /// reported (an absolute path joins as itself).
    func checkpoints(rel: String) async throws -> [String] {
        let obj = try await getJSON("/api/checkpoints?rel=\(Self.escaped(rel))") as? [String: Any]
        return ((obj?["checkpoints"] as? [Any]) ?? []).map { "\($0)" }
    }

    func restoreCheckpoint(rel: String, name: String) async throws -> String {
        let r = try await postJSON("/api/checkpoints/restore", ["rel": rel, "name": name])
        return (r["message"] as? String) ?? "restored"
    }

    /// Every DOI in the text, resolved against Crossref.
    func checkCitations(_ text: String) async throws -> [CitationRow] {
        struct R: Codable { var rows: [CitationRow]? }
        var req = try request("/api/citations", method: "POST", body: ["text": text])
        req.timeoutInterval = 180
        let data = try await run(req)
        return (try? JSONDecoder().decode(R.self, from: data))?.rows ?? []
    }

    /// A chat, written up as a reusable skill. Runs the model, so slow.
    func captureSkill(name: String, sid: String) async throws -> String {
        let r = try await postJSON("/api/skill/capture", ["name": name, "sid": sid], timeout: 600)
        return (r["name"] as? String) ?? name
    }

    // ------------------------------------------------------------ chat level

    @discardableResult
    func setPlanMode(sid: String, on: Bool) async throws -> Bool {
        let r = try await postJSON("/api/plan_mode", ["sid": sid, "on": on])
        return (r["plan_mode"] as? Bool) ?? on
    }

    /// Allow a tool for the rest of this chat and not one message longer —
    /// nothing is written to the saved rules.
    func allowForThisChat(sid: String, tool: String, pattern: String, note: String = "") async throws {
        _ = try await postJSON("/api/permissions/session",
                               ["sid": sid, "tool": tool, "pattern": pattern, "note": note])
    }

    /// Put the projects in the order given. One write: ten separate saves used to race
    /// the Claude-group sync on the Mac and lose.
    func reorderProjects(_ ids: [String]) async throws {
        _ = try await postJSON("/api/projects/reorder", ["ids": ids])
    }

    /// Put these chats in this order, at the top of the list, until you sort by recent.
    func reorderChats(_ ids: [String]) async throws {
        _ = try await postJSON("/api/session/reorder", ["order": ids])
    }

    /// Back to newest first, forgetting every hand-placed position.
    func sortChatsByRecent() async throws {
        _ = try await postJSON("/api/session/sort_recent", [:])
    }

    /// Allow a tool in one project, for good: the scope between "for the rest of this
    /// chat" and "everywhere". The rule lives with that project's folder.
    func allowInProject(project: String, tool: String, pattern: String, note: String = "") async throws {
        _ = try await postJSON("/api/permissions/project",
                               ["kind": "allow", "project": project, "tool": tool,
                                "pattern": pattern, "note": note])
    }

    /// Set one of the settings a chat keeps for itself (easy mode, the model that
    /// does the side work, how much it may do without asking). `nil` puts the chat
    /// back on Orbit's own setting. Answers with the chat's settings as they now are.
    @discardableResult
    func setChatSetting(sid: String, key: String, value: Any?)
        async throws -> (prefs: [String: JSONValue], effective: JSONValue?) {
        let r = try await postJSON("/api/chat/setting", ["sid": sid, "key": key, "value": value ?? NSNull()])
        if let e = r["error"] as? String, !e.isEmpty { throw Failure.server(400, e) }
        let prefs = (r["prefs"] as? [String: Any]) ?? [:]
        return (prefs.compactMapValues { JSONValue(any: $0) }, JSONValue(any: r["effective"]))
    }

    /// A temporary chat: nothing written to disk. Returns its id.
    func temporaryChat(on: Bool = true) async throws -> String {
        let r = try await postJSON("/api/temp", ["on": on])
        guard let sid = r["sid"] as? String else { throw Failure.decoding("temp") }
        return sid
    }

    /// Erase a temporary chat completely. The Mac refuses for any other chat.
    func burn(sid: String) async throws {
        try await postJSON("/api/burn", ["sid": sid])
    }

    /// The chat as Markdown, as the Mac exports it, saved under its title.
    func exportMarkdown(_ id: String, title: String) async throws -> URL {
        let data = try await run(try request("/api/export?id=\(Self.escaped(id))"))
        let safe = String(title.replacingOccurrences(of: "/", with: "-").prefix(60))
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-export-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent((safe.isEmpty ? "chat" : safe) + ".md")
        try data.write(to: url, options: .atomic)
        return url
    }

    func usageStats(days: Int) async throws -> UsageStats {
        try await get("/api/stats?days=\(days)", as: UsageStats.self)
    }

    func ledger(sid: String?) async throws -> (chat: LedgerSummary, all: LedgerSummary) {
        struct R: Decodable { var session: LedgerSummary; var all: LedgerSummary }
        let q = sid.map { "?sid=\(Self.escaped($0))" } ?? ""
        let r = try await get("/api/ledger\(q)", as: R.self)
        return (r.session, r.all)
    }

    // ------------------------------------------------------------ chat list

    /// Every tag in use, most used first.
    func tags() async throws -> [(name: String, count: Int)] {
        let obj = try await getJSON("/api/tags") as? [String: Any] ?? [:]
        return obj.map { (name: $0.key, count: ($0.value as? Int) ?? 0) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.name < $1.name }
    }

    func setTags(_ id: String, _ tags: [String]) async throws {
        try await postJSON("/api/tag", ["id": id, "tags": tags])
    }

    func projectDetails() async throws -> [ProjectDetail] {
        let obj = try await getJSON("/api/projects") as? [String: Any] ?? [:]
        return obj.compactMap { k, v in (v as? [String: Any]).map { ProjectDetail(id: k, $0) } }
            .sorted { $0.order != $1.order ? $0.order < $1.order : $0.name < $1.name }
    }

    /// Create (empty id) or change a project. Returns its id.
    @discardableResult
    func saveProject(_ p: ProjectDetail) async throws -> String {
        let body: [String: Any] = [
            "id": p.id.isEmpty ? NSNull() : p.id, "name": p.name, "description": p.description,
            "instructions": p.instructions, "color": p.color, "folder": p.folder,
            "trust_tools": p.trustTools,
        ]
        let r = try await postJSON("/api/projects/save", body)
        return (r["id"] as? String) ?? p.id
    }

    /// Chats in it are kept; they just lose the project.
    func deleteProject(_ id: String) async throws {
        try await postJSON("/api/projects/delete", ["id": id])
    }

    /// Put a chat in a project, or take it out with nil.
    func assign(_ id: String, project: String?) async throws {
        try await postJSON("/api/session/assign", ["id": id, "project": project ?? NSNull()])
    }

    /// Forget any hand-made order, so pinned chats sort by recent activity again.
    func sortRecent() async throws {
        try await postJSON("/api/session/sort_recent", [:])
    }

    /// Move a chat to the bin and return its bin entry, so it can be put back.
    func bin(_ id: String) async throws -> TrashItem? {
        // an empty chat never written to disk answers ok:false, and is simply gone
        try await post("/api/delete", ["id": id])
        return try? await trash().first { $0.kind == "session" && $0.name.hasSuffix("__\(id).json") }
    }
}
