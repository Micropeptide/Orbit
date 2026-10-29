import Foundation

/// Crew mode (`/api/crew`): a builder chat and a reviewer chat that improve a folder, round after
/// round, until a limit or until you stop them. Read leniently from `JSONValue`.

struct CrewRun: Identifiable, Hashable {
    struct Party: Hashable {
        var model: String?
        var sid: String?
        var rounds: Int
    }

    struct Round: Identifiable, Hashable {
        var id: Int { round }
        var round: Int
        var score: Int?
        var summary: String
        var issues: [String]
        var nextTasks: [String]
    }

    var id: String
    var title: String
    var brief: String
    var folder: String
    var criteria: String
    /// running, paused, stopped, done.
    var state: String
    /// Why it is in that state, in words.
    var reason: String
    /// build, review, idle.
    var phase: String
    var round: Int
    var tokens: Int
    var best: Int?
    var bestRound: Int
    var hours: Double
    var maxRounds: Int
    var maxTokens: Int
    var attention: String
    var notes: [String]
    var backlog: [String]
    var builders: [Party]
    var reviewers: [Party]
    var history: [Round]
    var created: Double
    var updated: Double
    /// What it is doing now, where the Mac says.
    var activity: String?

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        title = v.str("title") ?? "Crew"
        brief = v.str("brief") ?? ""
        folder = v.str("folder") ?? ""
        criteria = v.str("criteria") ?? ""
        state = v.str("state") ?? ""
        reason = v.str("reason") ?? ""
        phase = v.str("phase") ?? ""
        round = v.integer("round") ?? 0
        tokens = v.integer("tokens") ?? 0
        best = v.integer("best")
        bestRound = v.integer("best_round") ?? 0
        let l = v["limits"] ?? .null
        hours = l.dbl("hours") ?? 0; maxRounds = l.integer("max_rounds") ?? 0; maxTokens = l.integer("max_tokens") ?? 0
        attention = v.str("attention") ?? ""
        notes = v["notes"]?.strings ?? []
        backlog = v["backlog"]?.strings ?? []
        func parties(_ k: String) -> [Party] {
            v.list(k).map { Party(model: $0.str("model"), sid: $0.str("sid"), rounds: $0.integer("rounds") ?? 0) }
        }
        builders = parties("builders"); reviewers = parties("reviewers")
        history = v.list("history").map {
            Round(round: $0.integer("round") ?? 0, score: $0.integer("score"), summary: $0.str("summary") ?? "",
                  issues: $0["issues"]?.strings ?? [], nextTasks: $0["next_tasks"]?.strings ?? [])
        }
        created = v.dbl("created") ?? 0
        updated = v.dbl("updated") ?? 0
        activity = v["activity"]?.string ?? v["activity"]?.str("text")
    }

    var isRunning: Bool { state == "running" }
    var isPaused: Bool { state == "paused" }
}

struct CrewList {
    var runs: [CrewRun]
    init(json v: JSONValue) { runs = v.list("runs").map { CrewRun(json: $0) } }
}
