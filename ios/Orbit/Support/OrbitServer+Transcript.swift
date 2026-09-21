import Foundation

/// The Claude Code-style transcript features: going back to an earlier
/// message, running a shell command from the composer, and what fills the
/// context window. Every call names the chat it is about.
extension OrbitServer {

    /// What putting the files back would actually do, before it does any of it.
    /// A file you edited yourself since the answer wrote it lands in `unsafe`, and
    /// nothing is restored at all unless you say to go ahead anyway.
    struct UndoPreview {
        /// path -> what would happen to it ("restore", "remove (created here)").
        var safe: [(path: String, what: String)] = []
        /// path -> why it would be left alone ("changed since the answer wrote it").
        var unsafe: [(path: String, why: String)] = []
        /// Files with no snapshot to go back to.
        var gone: [(path: String, why: String)] = []
        var messages = 0

        var isEmpty: Bool { safe.isEmpty && unsafe.isEmpty && gone.isEmpty }

        init(_ r: [String: Any]) {
            func rows(_ key: String, _ field: String) -> [(String, String)] {
                ((r[key] as? [Any]) ?? []).compactMap {
                    guard let d = $0 as? [String: Any], let p = d["path"] as? String else { return nil }
                    return (p, (d[field] as? String) ?? "")
                }
            }
            safe = rows("safe", "what").map { (path: $0.0, what: $0.1) }
            unsafe = rows("unsafe", "why").map { (path: $0.0, why: $0.1) }
            // a file the answer created and something has already deleted arrives with
            // "what" rather than "why", and read by one key alone showed a bare path
            gone = ((r["gone"] as? [Any]) ?? []).compactMap {
                guard let d = $0 as? [String: Any], let p = d["path"] as? String else { return nil }
                return (path: p, why: (d["why"] as? String) ?? (d["what"] as? String) ?? "")
            }
            messages = (r["messages"] as? Int) ?? 0
        }
    }

    func rewindPreview(sid: String, index: Int) async throws -> UndoPreview {
        UndoPreview(try await postJSON("/api/rewind/preview", ["sid": sid, "index": index]))
    }

    /// Put a chat back to just before one of your messages (`index` counts your
    /// messages from 0). With `files`, the file changes later answers made go back too.
    /// `force` restores even files that changed after the answer wrote them.
    /// What a rewind actually did. `lines` is what the Mac had to say, refusals
    /// included, so counting it was counting refusals as restorations.
    struct RewindResult {
        var dropped = 0
        var restored: [String] = []
        var refused: [String] = []
        var lines: [String] = []
    }

    func rewind(sid: String, index: Int, files: Bool, force: Bool = false) async throws -> RewindResult {
        let r = try await postJSON("/api/rewind", ["sid": sid, "index": index,
                                                   "files": files, "force": force])
        func list(_ k: String) -> [String] { ((r[k] as? [Any]) ?? []).map { "\($0)" } }
        // an older Mac answers with "undone" alone and no account of what it refused
        let lines = list("undone")
        return RewindResult(dropped: (r["dropped"] as? Int) ?? (r["n"] as? Int) ?? 0,
                            restored: r["restored"] == nil ? lines : list("restored"),
                            refused: list("refused"),
                            lines: lines)
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
