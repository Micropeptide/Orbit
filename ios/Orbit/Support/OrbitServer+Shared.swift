import Foundation

/// Shared projects, as the Mac serves them to a paired phone.
///
/// Two doors, both behind the phone's ordinary pairing:
///  - `/api/collabhost` is the owner's console (list projects, share a chat…)
///  - `/shared/<id>/api/collab/…` is the project itself, with the owner's
///    sign-in added by the Mac, so the phone never holds a project token.
extension OrbitServer {

    struct SharedStatusAnswer: Decodable {
        var enabled: Bool
        var running: Bool
        var projects: [SharedProject]

        enum CodingKeys: String, CodingKey { case enabled, running, projects }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            enabled = (try? c.decode(Bool.self, forKey: .enabled)) ?? false
            running = (try? c.decode(Bool.self, forKey: .running)) ?? false
            projects = (try? c.decode([SharedProject].self, forKey: .projects)) ?? []
        }
    }

    /// The Mac answers a refused console call as `{"error": "..."}`; show that sentence, not the JSON.
    func collab(_ body: [String: Any], timeout: TimeInterval = 30) async throws -> Data {
        do {
            var req = try request("/api/collabhost", method: "POST", body: body)
            req.timeoutInterval = timeout
            return try await run(req)
        } catch Failure.server(let code, let raw) {
            if let d = raw.data(using: .utf8),
               let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
               let m = o["error"] as? String { throw Failure.server(code, m) }
            throw Failure.server(code, raw)
        }
    }

    func sharedStatus() async throws -> SharedStatusAnswer {
        try JSONDecoder().decode(SharedStatusAnswer.self, from: try await collab(["op": "status"], timeout: 10))
    }

    // ------------------------------------------------------------ one project

    private struct ProjectView: Decodable {
        var me: String?
        var members: [SharedPerson]?
        var chats: [SharedChat]?
        var online: [String]?
        var turn_mode: String?
        var frozen: Bool?
    }

    private struct EventPage: Decodable {
        struct Ev: Decodable { var seq: Int?; var ts: Double?; var type: String?; var author: String? }
        var events: [Ev]
    }

    private func sharedPath(_ pid: String, _ rest: String) -> String {
        "/shared/\(pid)/api/collab/p/\(pid)\(rest)"
    }

    /// Who is in a project and who is here now, its chats, and how much has been
    /// said since the phone last had it open.
    func sharedDetail(_ pid: String, seenSeq: Int?) async throws -> SharedDetail {
        let v = try await get(sharedPath(pid, ""), as: ProjectView.self)
        var d = SharedDetail()
        d.me = v.me
        d.people = v.members ?? []
        d.online = v.online ?? []
        d.chats = v.chats ?? []
        d.turnMode = v.turn_mode
        d.frozen = v.frozen ?? false

        // Walk the events after the last one seen. A project this phone has not
        // looked at before gets a baseline, not a pile of "unread".
        var after = seenSeq ?? 0
        var lastTS: Double? = SharedSeen.ts(pid)
        var unread = 0
        var more = false
        var pages = 0
        while pages < 25 {
            pages += 1
            let page = try await get(sharedPath(pid, "/events?after=\(after)&limit=200"), as: EventPage.self)
            for e in page.events {
                if let s = e.seq { after = max(after, s) }
                if let t = e.ts { lastTS = max(lastTS ?? 0, t) }
                if e.type == "msg", e.author != v.me { unread += 1 }
            }
            if page.events.count < 200 { break }
            if pages == 25 { more = true }
        }
        if seenSeq == nil {
            SharedSeen.set(pid, after)       // first sight: from here on, count what is new
            unread = 0; more = false
        }
        if let lastTS { SharedSeen.setTS(pid, lastTS) }
        d.unread = unread
        d.unreadMore = more
        d.lastActivity = lastTS
        return d
    }

    /// The newest event in a project (what "seen" means).
    func sharedLatestSeq(_ pid: String) async throws -> Int {
        var after = SharedSeen.get(pid) ?? 0
        for _ in 0..<25 {
            let page = try await get(sharedPath(pid, "/events?after=\(after)&limit=200"), as: EventPage.self)
            for e in page.events { if let s = e.seq { after = max(after, s) } }
            if page.events.count < 200 { break }
        }
        return after
    }

    // ------------------------------------------------------------ sharing a chat into a project

    struct SharePreview: Decodable {
        struct Warning: Decodable { var kind: String? }
        var title: String?
        var messages: Int?
        var warnings: [Warning]?
    }

    func sharePreview(project: String, chat: String) async throws -> SharePreview {
        try JSONDecoder().decode(SharePreview.self,
            from: try await collab(["op": "share_preview", "project": project, "chat": chat]))
    }

    /// Copy a chat of the owner's into a project. Returns the shared chat's title.
    func shareChat(project: String, chat: String, confirmSecrets: Bool) async throws -> String {
        struct R: Decodable { var title: String? }
        let data = try await collab(["op": "share_chat", "project": project, "chat": chat,
                                     "confirm_secrets": confirmSecrets])
        return (try? JSONDecoder().decode(R.self, from: data))?.title ?? "chat"
    }

    func removeSharedChat(project: String, chat: String) async throws {
        _ = try await collab(["op": "remove_chat", "project": project, "chat": chat])
    }

    /// Make a copy of a shared chat among the owner's own chats. Returns its title.
    func copySharedChat(project: String, chat: String) async throws -> String {
        struct R: Decodable { var title: String? }
        let data = try await collab(["op": "copy_chat", "project": project, "chat": chat])
        return (try? JSONDecoder().decode(R.self, from: data))?.title ?? "chat"
    }
}
