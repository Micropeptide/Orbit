import Foundation

/// The Claude Code-style transcript features: going back to an earlier
/// message, running a shell command from the composer, and what fills the
/// context window. Every call names the chat it is about.
extension OrbitServer {

    /// Put a chat back to just before one of your messages (`index` counts your
    /// messages from 0). With `files`, the file changes later answers made go back too.
    func rewind(sid: String, index: Int, files: Bool) async throws -> (dropped: Int, undone: [String]) {
        let r = try await postJSON("/api/rewind", ["sid": sid, "index": index, "files": files])
        let dropped = (r["dropped"] as? Int) ?? (r["n"] as? Int) ?? 0
        let undone = ((r["undone"] as? [Any]) ?? []).map { "\($0)" }
        return (dropped, undone)
    }

    enum BangOutcome {
        case ran(BangRun)
        /// The Mac wants a yes first, and says why.
        case confirm(String)
    }

    /// Run a command in the chat's folder; its output joins the conversation.
    func bang(sid: String, command: String, confirmed: Bool) async throws -> BangOutcome {
        var req = try request("/api/bang", method: "POST",
                              body: ["sid": sid, "command": command, "confirmed": confirmed])
        req.timeoutInterval = 600          // a build or a test run takes a while
        let data: Data
        do {
            data = try await run(req)
        } catch Failure.server(let code, let raw) {
            throw Failure.server(code, Self.errorText(raw))
        }
        let o = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        if let why = o["confirm"] as? String, !why.isEmpty { return .confirm(why) }
        if let e = o["error"] as? String, !e.isEmpty { throw Failure.server(400, e) }
        let rc = (o["rc"] as? Int) ?? (o["rc"] as? Double).map { Int($0) } ?? 0
        let secs = (o["secs"] as? Double) ?? (o["secs"] as? Int).map(Double.init)
        return .ran(BangRun(cmd: command, rc: rc, secs: secs, host: o["host"] as? String,
                            out: (o["output"] as? String) ?? ""))
    }

    /// What fills this chat's context window, part by part.
    func context(sid: String) async throws -> ContextDetail {
        let obj = try await getJSON("/api/context?sid=\(Self.escaped(sid))&full=1")
        guard let o = obj as? [String: Any] else { throw Failure.decoding("context") }
        if let e = o["error"] as? String, !e.isEmpty { throw Failure.server(400, e) }
        return ContextDetail(json: o)
    }
}
