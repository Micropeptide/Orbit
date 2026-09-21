import Foundation

/// What an answer says about itself beyond its words and tool calls: the
/// knowledge it drew on, claims those sources barely support, warnings, hooks
/// that ran, and progress lines. The Mac sends these only while the answer
/// streams (they are not saved with the chat), so the phone keeps them for the
/// answer they came with. Wording follows the Mac's web UI.

// ------------------------------------------------------------------ stream events

/// The stream events added after the first set, parsed in `OrbitServer.parse`.
enum TranscriptEvent {
    /// Knowledge-base passages the answer used.
    case sources([SourceHit])
    /// Sentences with little overlap with those passages.
    case weakClaims([WeakClaim])
    /// A tool's output looked like it was trying to give the model orders.
    case injection(name: String, markers: [String])
    /// The request matches one of your skills.
    case skillHint(String)
    /// Still going after a long while; no action needed.
    case longRunning(minutes: Int, rounds: Int, pending: [String])
    /// A plan nudge, a run of failures, or ultrathink turned on: a system line.
    case systemLine(String)
    /// The model server errored and the answer is retrying.
    case retry(String)
    /// The same call repeated with the same arguments.
    case stagnation(tool: String, times: Int)
    /// Old tool output trimmed, or earlier turns compacted.
    case squeezed(chars: Int, pct: Int)
    case autocompactDone(before: Int, after: Int)
    /// A Claude Code hook ran ("hook PreToolUse:Bash ran").
    case hook(String)
    /// A note you sent mid-answer was read (or kept for your next message).
    case interjection(text: String, late: Bool)
    /// Stopped at the round or time limit, with the plan steps still open.
    case roundLimit(reason: String, pending: [String])
    /// A second model read back the diff this answer produced.
    case review(text: String, files: Int, model: String)
    /// A second model checked the answer against what was asked. `failOpen` means
    /// the check itself could not run, so the work was passed rather than failed.
    case verified(passed: Bool, reason: String, next: String, failOpen: Bool)

    static func int(_ v: Any?) -> Int {
        (v as? Int) ?? (v as? Double).map { Int($0) } ?? (v as? String).flatMap { Int($0) } ?? 0
    }

    static func strings(_ v: Any?) -> [String] {
        ((v as? [Any]) ?? []).map { "\($0)" }
    }

    /// One of the newer events, or nil for a kind this does not know.
    static func parse(kind: String, _ p: Any?) -> TranscriptEvent? {
        let d = (p as? [String: Any]) ?? [:]
        let msg = (d["msg"] as? String) ?? ""
        switch kind {
        case "sources":
            let hits = ((p as? [Any]) ?? []).enumerated().compactMap { SourceHit($0.element as? [String: Any], index: $0.offset) }
            return hits.isEmpty ? nil : .sources(hits)
        case "weak_claims":
            let claims = ((p as? [Any]) ?? []).enumerated().compactMap { WeakClaim($0.element as? [String: Any], index: $0.offset) }
            return claims.isEmpty ? nil : .weakClaims(claims)
        case "injection":
            return .injection(name: (d["name"] as? String) ?? "a tool", markers: strings(d["markers"]))
        case "skill_hint":
            let n = (d["name"] as? String) ?? ""
            return n.isEmpty ? nil : .skillHint(n)
        case "long_running":
            return .longRunning(minutes: int(d["minutes"]), rounds: int(d["rounds"]), pending: strings(d["pending"]))
        case "plan_nudge", "fail_streak", "ultrathink":
            return .systemLine(msg.isEmpty ? kind.replacingOccurrences(of: "_", with: " ") : msg)
        case "retry":
            let wait = (d["wait"] as? Double) ?? Double(int(d["wait"]))
            let of = d["of"] == nil ? 5 : int(d["of"])
            var line: String
            if wait > 0 { line = "model server error — retrying in \(max(1, Int(wait.rounded())))s " }
            else if (d["kind"] as? String) == "overflow" { line = "too long for the model — compacting, then retrying " }
            else { line = "model server error — retrying " }
            line += "(attempt \(int(d["attempt"])) of \(of))"
            return .retry(line)
        case "stagnation":
            return .stagnation(tool: (d["tool"] as? String) ?? "a tool", times: int(d["times"]))
        case "squeezed":
            return .squeezed(chars: int(d["chars"]), pct: int(d["pct"]))
        case "autocompact_done":
            return .autocompactDone(before: int(d["before"]), after: int(d["after"]))
        case "interjection":
            return .interjection(text: (d["text"] as? String) ?? "", late: (d["late"] as? Bool) ?? false)
        case "review":
            let text = (d["text"] as? String) ?? ""
            return text.isEmpty ? nil
                : .review(text: text, files: int(d["files"]),
                          model: (d["model"] as? String) ?? "")
        case "verified":
            return .verified(passed: (d["passed"] as? Bool) ?? true,
                             reason: (d["reason"] as? String) ?? "",
                             next: (d["next"] as? String) ?? "",
                             failOpen: (d["fail_open"] as? Bool) ?? false)
        case "round_limit":
            let why = (d["reason"] as? String) == "time" ? "stopped at the time limit"
                : "stopped after \(int(d["rounds"])) tool rounds"
            return .roundLimit(reason: why, pending: strings(d["pending"]))
        default:
            return nil
        }
    }
}

struct SourceHit: Hashable, Identifiable {
    var doc: String
    var score: String
    var snippet: String
    /// Where it came in the list: the same document and opening words can come twice.
    var index = 0
    var id: String { "\(index)\u{0}" + doc }

    init?(_ d: [String: Any]?, index: Int = 0) {
        guard let d, let doc = d["doc"] as? String else { return nil }
        self.index = index
        self.doc = doc
        if let n = d["score"] as? Double { score = String(format: "%.2f", n) }
        else { score = d["score"].map { "\($0)" } ?? "" }
        snippet = (d["snippet"] as? String) ?? ""
    }
}

struct WeakClaim: Hashable, Identifiable {
    var sentence: String
    var support: Double
    /// Where it came in the list: the same sentence can be flagged twice.
    var index = 0
    var id: String { "\(index)\u{0}" + sentence }

    init?(_ d: [String: Any]?, index: Int = 0) {
        guard let d, let s = d["sentence"] as? String else { return nil }
        self.index = index
        sentence = s
        support = (d["support"] as? Double) ?? Double(TranscriptEvent.int(d["support"]))
    }
}

/// Hooks that ran during one answer, folded into a single line.
struct HookFold: Hashable {
    var lines: [String] = []
    var bad = 0
    /// Kinds in the order they first ran, with how often.
    var kinds: [(String, Int)] = []

    static func == (a: HookFold, b: HookFold) -> Bool { a.lines == b.lines }
    func hash(into h: inout Hasher) { h.combine(lines) }

    mutating func add(_ msg: String) {
        lines.append(msg)
        if msg.range(of: #"exit [1-9]|fail|error|block"#, options: [.regularExpression, .caseInsensitive]) != nil {
            bad += 1
        }
        var kind = "hook"
        if let r = msg.range(of: #"^hook\s+([A-Za-z]+)"#, options: .regularExpression) {
            kind = String(msg[r]).components(separatedBy: .whitespaces).last ?? "hook"
        }
        if let i = kinds.firstIndex(where: { $0.0 == kind }) { kinds[i].1 += 1 } else { kinds.append((kind, 1)) }
    }

    /// "Ran 12 hooks · 1 reported a problem — PreToolUse ×6, PostToolUse ×6"
    var summary: String {
        "Ran " + ToolText.plural(lines.count, "hook", "hooks")
            + (bad > 0 ? " · \(bad) reported a problem" : "") + " — "
            + kinds.map { $0.0 + ($0.1 > 1 ? " ×\($0.1)" : "") }.joined(separator: ", ")
    }
}

/// Everything extra one answer carried, kept on the phone by chat and turn.
struct AnswerExtras: Hashable {
    /// The message that asked, to be sure a rewound chat does not show these
    /// under a different answer that now sits at the same place.
    var prompt: String
    var sources: [SourceHit] = []
    var weakClaims: [WeakClaim] = []
    var warnings: [String] = []
    var skillHint: String?
    var hooks = HookFold()
    /// System lines in the order they came: nudges, trims, compaction.
    var lines: [String] = []
    /// Only the latest of each: they replace themselves as the answer goes on.
    var retry: String?
    var longRunning: String?
    /// The read-back of what this answer changed, and the check against what was
    /// asked — each from whichever model does Orbit's own work.
    var review: Review?
    var check: Check?

    var isEmpty: Bool {
        sources.isEmpty && weakClaims.isEmpty && warnings.isEmpty && skillHint == nil
            && hooks.lines.isEmpty && lines.isEmpty && retry == nil && longRunning == nil
            && review == nil && check == nil
    }

    struct Review: Hashable {
        var text: String
        var files: Int
        var model: String
        var title: String {
            let n = "\(files) changed file" + (files == 1 ? "" : "s")
            return model.isEmpty ? "Review of \(n)" : "Review of \(n) · \(model)"
        }
    }

    struct Check: Hashable {
        var passed: Bool
        var reason: String
        var next: String
        var failOpen: Bool
        /// What to say about it in one line, or nil when it needs the fuller box.
        var line: String? {
            guard passed else { return nil }
            if failOpen { return "the check could not run" + (reason.isEmpty ? "" : ": " + reason) }
            return "checked against your request — looks done"
        }
        var problem: String {
            var t = "not finished" + (reason.isEmpty ? "" : ": " + reason)
            if !next.isEmpty { t += " → " + next }
            return t
        }
    }
}

// ------------------------------------------------------------------ transcript turns

extension TranscriptRow {
    /// Which of your messages each row answers (counting only real messages,
    /// not notes sent mid-answer), and whether it is the last row of that answer.
    static func turns(_ messages: [Message]) -> [(turn: Int, prompt: String, ends: Bool)] {
        var out: [(Int, String, Bool)] = []
        out.reserveCapacity(messages.count)
        var turn = -1
        var prompt = ""
        for (i, m) in messages.enumerated() {
            if m.isUser && m.note != true { turn += 1; prompt = m.text }
            let next = i + 1 < messages.count ? messages[i + 1] : nil
            let ends = !m.isUser && (next == nil || (next!.isUser && next!.note != true))
            out.append((turn, prompt, ends))
        }
        return out
    }
}

// ------------------------------------------------------------------ files

/// A page of the Files list.
struct FilesPage {
    var items: [RemoteFile]
    var total: Int
}

extension RemoteFile {
    /// Broad kind, for sorting by type and choosing a preview.
    var typeRank: Int {
        switch ext {
        case "png", "jpg", "jpeg", "gif", "webp", "heic", "svg": return 0
        case "pdf": return 1
        case "html", "htm": return 2
        case "md", "markdown", "txt", "docx", "doc", "rtf", "pptx": return 3
        case "csv", "tsv", "xlsx", "json", "jsonl": return 4
        case "ipynb", "py", "r", "swift", "js", "ts", "sh", "c", "cpp", "go", "rs": return 5
        default: return 9
        }
    }
}
