import Foundation

/// Background work and the furniture of agent chats: what is running now
/// (`/tasks`), cluster jobs, sessions other agents began, "New chat with…"
/// presets, and the details of a Claude Code or Codex chat.

// ------------------------------------------------------------------ the list

/// Where a chat in the list came from, when another agent began it. Those
/// sessions sit in their own folded sections rather than among your chats.
enum ExternalSource: String, CaseIterable, Identifiable {
    case claude, codex, opencode
    var id: String { rawValue }

    var label: String {
        switch self {
        case .claude: return "From Claude Code"
        case .codex: return "From Codex"
        case .opencode: return "From OpenCode"
        }
    }

    var tip: String {
        switch self {
        case .claude:
            return "Sessions from the Claude CLI and Claude's desktop app — open one to continue it here, "
                + "in the same Claude session."
        case .codex:
            return "Codex sessions — open one to continue it here; Orbit runs Codex resuming that same session."
        case .opencode:
            return "OpenCode sessions — open one to continue it here; Orbit runs OpenCode resuming that same session."
        }
    }

    var symbol: String {
        switch self {
        case .claude: return "sparkle"
        case .codex: return "chevron.left.forwardslash.chevron.right"
        case .opencode: return "terminal"
        }
    }

    /// The same test the Mac's list makes: by `source`, or by the id's prefix
    /// for a Mac that predates `source`.
    init?(chat c: ChatSummary) {
        if c.source == "codex" || c.id.hasPrefix("cx-") { self = .codex }
        else if c.source == "opencode" || c.id.hasPrefix("oc-") { self = .opencode }
        else if c.external == true || c.id.hasPrefix("cq-") { self = .claude }
        else { return nil }
    }
}

/// List state that outlives one screen: how many chats to ask for, and how
/// many the Mac has in all.
struct WorkExtras {
    /// The Mac's own list asks for 500 at a time.
    static let page = 500
    var chatLimit = WorkExtras.page
    var chatTotal: Int?
    /// `/tasks`: the sheet of everything running in the background.
    var showTasks = false
    /// The short tour shown once, after this phone first pairs.
    var showTips = false
}

// ------------------------------------------------------------------ /tasks

/// One thing running in the background, as `/api/tasks` lists it: a chat
/// answering, a message waiting in a queue, or a shell command a model left running.
struct BackgroundTask: Decodable, Identifiable, Hashable {
    enum Kind: String { case answer, queued, shell, other }

    var kind: Kind
    var rawID: String
    var title: String
    var status: String?
    var since: Double?
    var text: String?
    var sid: String?
    var canStop: Bool

    /// Queue item ids are only unique within their chat.
    var id: String { "\(kind.rawValue)|\(sid ?? "")|\(rawID)" }

    var kindLabel: String {
        switch kind {
        case .answer: return "answering"
        case .queued: return "queued"
        case .shell: return "shell"
        case .other: return "task"
        }
    }

    var symbol: String {
        switch kind {
        case .answer: return "bubble.left.and.text.bubble.right"
        case .queued: return "tray.full"
        case .shell: return "terminal"
        case .other: return "gearshape.2"
        }
    }

    enum CodingKeys: String, CodingKey { case kind, id, title, status, since, text, sid, can_stop }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        kind = Kind(rawValue: (try? c.decode(String.self, forKey: .kind)) ?? "") ?? .other
        rawID = c.lenientString(.id) ?? ""
        title = (try? c.decode(String.self, forKey: .title)) ?? ""
        status = try? c.decode(String.self, forKey: .status)
        since = c.lenientDouble(.since)
        text = try? c.decode(String.self, forKey: .text)
        sid = (try? c.decode(String.self, forKey: .sid)).flatMap { $0.isEmpty ? nil : $0 }
        canStop = c.lenientBool(.can_stop) ?? false
    }

    /// "waiting for the model · for 4 min · “the message”"
    func detail(now: Double) -> String {
        var parts: [String] = []
        if let s = status, !s.isEmpty { parts.append(s) }
        if let since, now > since { parts.append("for " + Self.duration(now - since)) }
        if let t = text, !t.isEmpty { parts.append("“\(t)”") }
        return parts.joined(separator: " · ")
    }

    static func duration(_ secs: Double) -> String {
        let s = Int(max(0, secs))
        if s < 60 { return "\(s)s" }
        if s < 3600 { return "\(s / 60) min" }
        let h = s / 3600, m = (s % 3600) / 60
        return m == 0 ? "\(h) h" : "\(h) h \(m) min"
    }
}

struct BackgroundTasks: Decodable {
    var items: [BackgroundTask]
    var now: Double

    enum CodingKeys: String, CodingKey { case items, now }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        items = (try? c.decode([BackgroundTask].self, forKey: .items)) ?? []
        now = c.lenientDouble(.now) ?? Date.now.timeIntervalSince1970
    }
}

// ------------------------------------------------------------------ cluster jobs

/// A job in the cluster's queue, as `qstat` shows it.
struct ClusterJob: Decodable, Identifiable, Hashable {
    var id: String
    var prio: String?
    var name: String
    var user: String?
    var state: String
    var since: String?
    var slots: String?

    /// qstat's short states, as words.
    var stateLabel: String {
        switch state {
        case "r": return "running"
        case "qw": return "queued"
        case "Eqw": return "error"
        default: return state
        }
    }

    enum CodingKeys: String, CodingKey { case id, prio, name, user, state, since, slots }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = c.lenientString(.id) ?? ""
        prio = c.lenientString(.prio)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        user = try? c.decode(String.self, forKey: .user)
        state = (try? c.decode(String.self, forKey: .state)) ?? ""
        since = try? c.decode(String.self, forKey: .since)
        slots = c.lenientString(.slots)
    }
}

struct ClusterJobs: Decodable {
    var jobs: [ClusterJob]
    var error: String?

    enum CodingKeys: String, CodingKey { case jobs, error }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        jobs = (try? c.decode([ClusterJob].self, forKey: .jobs)) ?? []
        error = (try? c.decode(String.self, forKey: .error)).flatMap { $0.isEmpty ? nil : $0 }
    }
}

/// How long past jobs with a similar name took.
struct ClusterEstimate: Decodable {
    var runs: Int?
    var median_min: Double?
    var max_min: Double?
}

// ------------------------------------------------------------------ New chat with…

/// A saved "New chat with…" choice: a model, a machine, a folder and a mode,
/// to start the same kind of chat again. Kept in Orbit's Claude Code settings,
/// so the Mac's web page lists the same presets.
struct ChatPreset: Identifiable, Hashable {
    var name: String
    var model: String
    var cwd: String
    var mode: String
    var host: String
    /// Names are how the Mac tells presets apart; two with the same name are
    /// still separate rows, hence the position.
    var index = 0
    var id: String { "\(index)|\(name)" }

    init(name: String, model: String, cwd: String, mode: String, host: String) {
        self.name = name; self.model = model; self.cwd = cwd; self.mode = mode; self.host = host
    }

    init?(json v: JSONValue, index: Int) {
        guard let name = v["name"]?.string, !name.isEmpty else { return nil }
        self.name = name
        model = v["model"]?.string ?? ""
        cwd = v["cwd"]?.string ?? ""
        mode = v["mode"]?.string ?? ""
        host = v["host"]?.string ?? ""
        self.index = index
    }

    var json: [String: Any] { ["name": name, "model": model, "cwd": cwd, "mode": mode, "host": host] }

    var permissionMode: PermissionMode? { PermissionMode(server: mode) }
}

// ------------------------------------------------------------------ an agent chat's details

/// What `/api/claude/info?sid=` says about one Claude Code or Codex chat,
/// beyond where it works (`ChatWork`): how to continue it in a terminal, the
/// session's profile, skills and MCP servers, and the extra folders it may use.
struct ChatAgentInfo {
    struct MCPServer: Hashable, Identifiable {
        var name: String
        var status: String
        var id: String { name }
        var ok: Bool { status == "connected" }
    }

    var codex: Bool
    var installed: Bool
    var version: String?
    /// The terminal command that continues this chat's Claude session.
    var resume: String?
    var session: String?
    var codexThread: String?
    var host: String?
    /// Answering right now: only then can Claude Code be asked about its context or MCP servers.
    var running: Bool
    var profile: String?
    var skills: [String]
    var mcp: [MCPServer]
    /// MCP servers named in Orbit's Claude Code settings ("*" = all of yours).
    var mcpConfigured: [String]
    var addDirs: [String]

    init(json o: [String: Any]) {
        func s(_ v: Any?) -> String? {
            guard let v = v as? String, !v.isEmpty else { return nil }
            return v
        }
        let settings = o["settings"] as? [String: Any] ?? [:]
        codex = (o["codex"] as? Bool) ?? false
        installed = (o["installed"] as? Bool) ?? false
        version = s(o["version"])
        resume = s(o["resume"])
        session = s(o["session"])
        codexThread = s(o["codex_thread"])
        host = s(o["host"])
        running = (o["running"] as? Bool) ?? false
        profile = s(settings["profile"])
        skills = (o["skills"] as? [Any] ?? []).compactMap { $0 as? String }
        mcp = (o["mcp"] as? [[String: Any]] ?? []).compactMap { m in
            guard let name = s(m["name"]) else { return nil }
            return MCPServer(name: name, status: s(m["status"]) ?? "unknown")
        }
        mcpConfigured = (settings["mcp_servers"] as? [Any] ?? []).compactMap { $0 as? String }
        addDirs = (o["add_dirs"] as? [Any] ?? []).compactMap { $0 as? String }
    }

    /// For Codex, the command that opens the same thread in the Codex CLI.
    var terminalCommand: String? {
        if codex { return codexThread.map { "codex resume \($0)" } }
        return resume
    }
}

// ------------------------------------------------------------------ scheduled tasks

extension ScheduledTask {
    /// A run the Mac scheduled itself, to carry a chat on after a used-up allowance resets.
    var isLimitResume: Bool { kind == "limit_resume" }

    /// The chat such a run continues: its name is "continue after usage limit: <chat>".
    var limitResumeChat: String {
        let prefix = "continue after usage limit: "
        if name.lowercased().hasPrefix(prefix) { return String(name.dropFirst(prefix.count)) }
        return name.isEmpty ? "this chat" : name
    }
}
