import Foundation

/// The message queue, and the smaller calls behind the composer's commands:
/// queue a message while an answer runs, send one in now, read the message a
/// queued answer took, the chat's context gauge, and the `/` commands the Mac
/// answers (`/status`, `/tools`, `/rename`).
extension OrbitServer {

    // ------------------------------------------------------------ queue

    /// Put a message at the back of a chat's queue: it starts by itself when the
    /// answers ahead of it are done. Attachments go with it, which a steer note cannot do.
    @discardableResult
    func enqueue(sid: String, text: String, attachments: [[String: String]]) async throws -> QueueState {
        try await queue(sid: sid, op: "add", ["text": text, "attachments": attachments])
    }

    /// Send a waiting message now. While the chat answers, the Mac hands it to the
    /// running answer as a note (`interjected`); otherwise it goes first in line and starts.
    func queueNow(sid: String, id: String) async throws -> QueueNowResult {
        struct R: Codable { var ok: Bool?; var interjected: Bool?; var queue: QueueState?; var error: String? }
        let data = try await post("/api/queue", ["sid": sid, "op": "now", "id": id])
        let r = try? JSONDecoder().decode(R.self, from: data)
        if let e = r?.error { throw Failure.server(400, e) }
        return QueueNowResult(interjected: r?.interjected ?? false, queue: r?.queue ?? .empty)
    }

    /// Whether a chat is answering, and the message that answer is for — the one
    /// it has just taken from the queue.
    func liveUser(_ sid: String) async throws -> (running: Bool, user: String?) {
        struct L: Codable { var running: Bool?; var user: String? }
        let l = try await get("/api/live/\(sid)", as: L.self)
        return (l.running ?? false, l.user)
    }

    // ------------------------------------------------------------ chats

    /// A new chat in a project (nil: none). An older Mac ignores the project.
    func newChat(project: String?) async throws -> String {
        struct N: Codable { var sid: String }
        let data = try await post("/api/new", ["project": project ?? NSNull()])
        return try JSONDecoder().decode(N.self, from: data).sid
    }

    // ------------------------------------------------------------ status

    /// The model server's state and this chat's context window.
    struct ChatStatus {
        var running: Bool
        var model: String?
        var memoryGB: Double?
        var context: ContextState?
    }

    func chatStatus(sid: String?) async throws -> ChatStatus {
        let path = "/api/status" + (sid.map { "?sid=" + Self.escaped($0) } ?? "")
        guard let o = try await getJSON(path) as? [String: Any] else { throw Failure.decoding("status") }
        var ctx: ContextState?
        if let c = o["context"] as? [String: Any] {
            func int(_ k: String) -> Int { (c[k] as? Int) ?? (c[k] as? Double).map { Int($0) } ?? 0 }
            let max = int("max")
            if max > 0 {
                ctx = ContextState(used: int("used"), max: max,
                                   pct: (c["pct"] as? Double) ?? Double(int("pct")),
                                   basis: c["basis"] as? String)
            }
        }
        let mem = (o["memory_gb"] as? Double) ?? (o["memory_gb"] as? String).flatMap(Double.init)
        return ChatStatus(running: (o["running"] as? Bool) ?? false,
                          model: o["model"] as? String, memoryGB: mem, context: ctx)
    }

    /// The tools Orbit's own chats can use right now.
    func activeTools() async throws -> [String] {
        let o = try await getJSON("/api/info") as? [String: Any]
        return (o?["tools"] as? [String]) ?? []
    }
}
