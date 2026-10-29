import Foundation

/// Settings → Helpers (`/api/sciencebridge`): other agents (Claude Science, Claude Code, Codex, anything
/// that speaks MCP) hand work to Orbit's cheaper models, and anything that changes files waits for a yes.
/// Read leniently from `JSONValue`. An app's token is never read: it stays on the Mac.

/// The door itself and the apps allowed through it.
struct HelperStatus {
    var enabled: Bool
    var running: Bool
    var url: String?
    var waiting: Int
    var clients: [HelperClient]

    init(json v: JSONValue) {
        enabled = v.flag("enabled") ?? false
        running = v.flag("running") ?? false
        url = v.str("url")
        waiting = v.integer("waiting") ?? 0
        clients = v.list("clients").map { HelperClient(json: $0) }
    }
}

/// One app that may hand Orbit work, with its limits.
struct HelperClient: Identifiable, Hashable {
    var id: String
    var name: String
    /// `writes` (ask before anything that changes files), `all` (before every job), `none`.
    var approval: String
    /// `ask` lets the app ask to read or change the person's own chats, Crew runs, shared projects and cluster models (every change still waits for a yes); `off` keeps it out.
    var actions: String
    /// `long` (when a long job finishes), `always`, `never`.
    var notify: String
    var workdirs: [String]
    /// 0 = no limit.
    var maxRunning: Int
    var maxPerDay: Int
    var maxThreadMessagesPerDay: Int
    var threadRounds: Int
    var threadModel: String
    var lastSeen: Double?
    var jobs: Int

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        name = v.str("name") ?? "App"
        approval = v.str("approval") ?? "writes"
        actions = v.str("actions") ?? "off"
        notify = v.str("notify") ?? "long"
        workdirs = v["workdirs"]?.strings ?? []
        maxRunning = v.integer("max_running") ?? 0
        maxPerDay = v.integer("max_per_day") ?? 0
        maxThreadMessagesPerDay = v.integer("max_thread_messages_per_day") ?? 0
        threadRounds = v.integer("thread_rounds") ?? 30
        threadModel = v.str("thread_model") ?? ""
        lastSeen = v.dbl("last_seen")
        jobs = v.integer("jobs") ?? 0
    }

    /// What `configure` takes for this app's `settings`.
    var settingsJSON: [String: Any] {
        ["name": name, "approval": approval, "actions": actions, "notify": notify, "workdirs": workdirs,
         "max_running": maxRunning, "max_per_day": maxPerDay,
         "max_thread_messages_per_day": maxThreadMessagesPerDay, "thread_rounds": threadRounds,
         "thread_model": threadModel]
    }
}

/// Everything the apps sent: jobs, conversations, and what Orbit's models did for them.
struct HelperInbox {
    var jobs: [HelperJob]
    var threads: [HelperThread]
    var waiting: Int
    /// Orbit's model -> (jobs, tokens), the last 7 days.
    var stats: [(model: String, jobs: Int, tokens: Int)]

    init(json v: JSONValue) {
        jobs = v.list("jobs").map { HelperJob(json: $0) }
        threads = v.list("threads").map { HelperThread(json: $0) }.filter { $0.state == "open" }
        waiting = v.integer("waiting") ?? 0
        stats = (v["stats"]?.object ?? [:]).map { ($0.key, $0.value.integer("jobs") ?? 0, $0.value.integer("tokens") ?? 0) }
            .sorted { $0.1 > $1.1 }
    }
}

struct HelperJob: Identifiable, Hashable {
    var id: String
    /// waiting (for your yes), running, done, failed, cancelled, denied.
    var state: String
    var app: String
    var task: String
    var label: String
    var model: String
    var answer: String
    var note: String
    var workdir: String?
    var write: Bool
    var created: Double
    var started: Double?
    var ended: Double?
    var tokens: Int
    var confidence: String
    var sid: String?

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        state = v.str("state") ?? ""
        app = v.str("app") ?? ""
        task = v.str("task") ?? ""
        label = v.str("label") ?? ""
        model = v.str("model") ?? v.str("tier") ?? ""
        answer = v.str("answer") ?? ""
        note = v.str("note") ?? ""
        workdir = v.str("workdir")
        write = v.flag("write") ?? false
        created = v.dbl("created") ?? 0
        started = v.dbl("started"); ended = v.dbl("ended")
        tokens = v.integer("tokens") ?? 0
        confidence = v.str("confidence") ?? ""
        sid = v.str("sid")
    }

    var title: String { label.isEmpty ? task : label }
    var seconds: Int? {
        guard let e = ended, let s = started ?? Optional(created) else { return nil }
        return max(1, Int((e - s).rounded()))
    }
}

/// A conversation an app holds with an Orbit chat.
struct HelperThread: Identifiable, Hashable {
    var id: String
    var name: String
    var sid: String?
    var role: String
    var model: String
    var rounds: Int
    var maxRounds: Int
    var state: String
    var app: String
    var unread: Int
    var last: Double?

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        name = v.str("name") ?? ""
        sid = v.str("sid"); role = v.str("role") ?? ""; model = v.str("model") ?? ""
        rounds = v.integer("rounds") ?? 0; maxRounds = v.integer("max_rounds") ?? 0
        state = v.str("state") ?? ""; app = v.str("app") ?? ""
        unread = v.integer("unread") ?? 0; last = v.dbl("last")
    }
}
