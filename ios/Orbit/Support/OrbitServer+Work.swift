import Foundation

/// Background work and agent chats: the chat list in pages, `/tasks`, cluster
/// jobs, "New chat with…" presets, and a Claude Code or Codex chat's details.
/// Every call mirrors what the Mac's web page sends.
extension OrbitServer {

    private func workJSON<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    /// An `error` the Mac put in an otherwise successful answer.
    private func workError(_ data: Data) -> String? {
        guard let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let e = o["error"] as? String, !e.isEmpty else { return nil }
        return e
    }

    // ------------------------------------------------------------ the chat list

    /// One page of chats, with how many there are in all.
    func chatPage(offset: Int = 0, limit: Int) async throws -> ChatList {
        try workJSON(ChatList.self, try await settingsCall("/api/sessions?offset=\(offset)&limit=\(limit)"))
    }

    // ------------------------------------------------------------ /tasks

    /// Everything running in the background: chats answering, queued messages,
    /// shell commands a model started.
    func backgroundTasks() async throws -> BackgroundTasks {
        try workJSON(BackgroundTasks.self, try await settingsCall("/api/tasks", timeout: 20))
    }

    /// Stop one: an answer through `/api/cancel`, a queued message by removing
    /// it, a shell command through `/api/tasks/stop` — as the Mac's /tasks does.
    func stopBackground(_ t: BackgroundTask) async throws {
        let data: Data
        switch t.kind {
        case .answer:
            data = try await settingsCall("/api/cancel", method: "POST", body: ["sid": t.sid ?? t.rawID])
        case .queued:
            guard let sid = t.sid else { throw Failure.server(400, "that message has no chat") }
            data = try await settingsCall("/api/queue", method: "POST",
                                          body: ["sid": sid, "op": "remove", "id": t.rawID])
        default:
            data = try await settingsCall("/api/tasks/stop", method: "POST",
                                          body: ["kind": t.kind.rawValue, "id": t.rawID])
        }
        if let e = workError(data) { throw Failure.server(400, e) }
    }

    // ------------------------------------------------------------ cluster jobs
    //
    // Each of these opens an SSH connection to the cluster, which limits how
    // often it may be reached: call them only when someone asks.

    func clusterJobs() async throws -> ClusterJobs {
        try workJSON(ClusterJobs.self, try await settingsCall("/api/h2/jobs", method: "POST", body: [:], timeout: 90))
    }

    func clusterLog(id: String, lines: Int = 80) async throws -> String {
        struct R: Decodable { var log: String? }
        let data = try await settingsCall("/api/h2/log", method: "POST", body: ["id": id, "lines": lines], timeout: 90)
        return (try? JSONDecoder().decode(R.self, from: data))?.log ?? ""
    }

    /// Past runs of jobs whose name starts like this one's.
    func clusterEstimate(name: String) async throws -> ClusterEstimate {
        try workJSON(ClusterEstimate.self,
                     try await settingsCall("/api/h2/estimate", method: "POST", body: ["name": name], timeout: 30))
    }

    // ------------------------------------------------------------ New chat with…

    func chatPresets() async throws -> [ChatPreset] {
        let data = try await settingsCall("/api/claude/info?sid=", timeout: 60)
        let v = try workJSON(JSONValue.self, data)
        return (v["settings"]?["presets"]?.array ?? []).enumerated()
            .compactMap { ChatPreset(json: $0.element, index: $0.offset) }
    }

    /// The whole list replaces the saved one.
    func savePresets(_ presets: [ChatPreset]) async throws {
        let data = try await settingsCall("/api/claude/settings", method: "POST",
                                          body: ["settings": ["presets": presets.map(\.json)]])
        if let e = workError(data) { throw Failure.server(400, e) }
    }

    // ------------------------------------------------------------ an agent chat

    func chatAgentInfo(sid: String) async throws -> ChatAgentInfo {
        let data = try await settingsCall("/api/claude/info?sid=\(OrbitServer.escaped(sid))", timeout: 60)
        guard let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw Failure.decoding("claude/info") }
        return ChatAgentInfo(json: o)
    }

    /// Ask the Claude Code run answering in this chat something about itself
    /// (`get_context_usage`, `mcp_status`). Its reply, formatted for reading.
    func claudeControl(sid: String, subtype: String) async throws -> String {
        let data = try await settingsCall("/api/claude/control", method: "POST",
                                          body: ["sid": sid, "subtype": subtype], timeout: 30)
        guard let obj = try? JSONSerialization.jsonObject(with: data) else {
            return String(data: data, encoding: .utf8) ?? ""
        }
        if let o = obj as? [String: Any], o.count == 1, let e = o["error"] as? String {
            throw Failure.server(400, e == "not running" ? "Claude Code isn't answering in this chat right now." : e)
        }
        let pretty = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
        return pretty.flatMap { String(data: $0, encoding: .utf8) } ?? ""
    }
}
