import Foundation

/// What the owner does to a shared project from the phone: make one, invite people, look after who is in it, pause it. All of it
/// is the Mac's own `/api/collabhost` console; nothing here decides anything the Mac does not check again.

struct SharedMember: Identifiable, Decodable, Hashable {
    let id: String
    var name: String
    var role: String?
    var state: String?
    var owner: Bool?
    /// What this person may do here, in the Mac's own plain sentences.
    var summary: [String]?

    var isMuted: Bool { state == "muted" }
}

struct SharedInviteRow: Identifiable, Decodable, Hashable {
    let id: String
    var role: String?
    var usesLeft: Int?
    var expiresAt: Double?
}

struct SharedPeople: Decodable {
    var members: [SharedMember] = []
    var invites: [SharedInviteRow] = []
    var roles: [String] = []

    enum CodingKeys: String, CodingKey { case members, invites, roles }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        members = (try? c.decode([SharedMember].self, forKey: .members)) ?? []
        invites = (try? c.decode([SharedInviteRow].self, forKey: .invites)) ?? []
        roles = (try? c.decode([String].self, forKey: .roles)) ?? []
    }
}

struct SharedInviteLink: Decodable {
    var link: String
    var appLink: String?
    var role: String?

    /// A link to this Mac's own door (127.0.0.1) opens nowhere else: say so before it is sent.
    var onlyOnTheMac: Bool {
        guard let h = URL(string: link)?.host?.lowercased() else { return true }
        return h == "127.0.0.1" || h == "localhost" || h == "::1" || h.hasSuffix(".local")
    }
}

extension OrbitServer {
    private func snake<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try d.decode(type, from: data)
    }

    /// A new shared project in a folder on the Mac. Returns its id.
    @discardableResult
    func sharedCreateProject(name: String, workingDir: String, ownerName: String) async throws -> String {
        let data = try await collab(["op": "create", "name": name, "working_dir": workingDir, "owner_name": ownerName])
        struct R: Decodable { struct P: Decodable { var id: String }; var project: P }
        return try JSONDecoder().decode(R.self, from: data).project.id
    }

    func sharedPeople(project: String) async throws -> SharedPeople {
        try snake(SharedPeople.self, try await collab(["op": "people", "project": project], timeout: 15))
    }

    /// An invitation link. `uses` 0 means as many as come; `expiresDays` nil means it does not lapse.
    func sharedInvite(project: String, role: String, uses: Int, expiresDays: Int?) async throws -> SharedInviteLink {
        var body: [String: Any] = ["op": "invite", "project": project, "role": role, "uses": uses]
        if let expiresDays { body["expires_in"] = expiresDays * 86_400 }
        return try snake(SharedInviteLink.self, try await collab(body))
    }

    /// remove | mute | unmute | role (value: the role) | revoke_invite (member: the invitation id)
    func sharedMemberAction(project: String, member: String, action: String, value: String? = nil) async throws {
        var body: [String: Any] = ["op": "member_action", "project": project, "member": member, "action": action]
        if let value { body["value"] = value }
        _ = try await collab(body)
    }

    /// Stop everyone from sending until it is resumed.
    func sharedSetPaused(project: String, paused: Bool) async throws {
        _ = try await collab(["op": paused ? "panic" : "resume", "project": project])
    }

    func sharedSettings(project: String, name: String? = nil, allowExport: Bool? = nil) async throws {
        var body: [String: Any] = ["op": "project_settings", "project": project]
        if let name { body["name"] = name }
        if let allowExport { body["allow_export"] = allowExport }
        _ = try await collab(body)
    }
}
