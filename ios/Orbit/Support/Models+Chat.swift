import Foundation

/// Shapes for chat actions and the chat list: questions and approvals raised
/// mid-answer, per-answer stats, usage, citations, projects and row status.

// ------------------------------------------------------------------ mid-answer prompts

/// A question the model asks while it works (`ask_user`). Answered with
/// `/api/answer`; a multiple-choice one takes a list.
struct AskQuestion: Identifiable, Hashable {
    var id: String
    var question: String
    var options: [String]
    var multiple: Bool

    init?(_ obj: [String: Any]?) {
        guard let obj, let id = obj["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        question = (obj["question"] as? String) ?? ""
        options = ((obj["options"] as? [Any]) ?? []).map { "\($0)" }
        multiple = (obj["multiple"] as? Bool) ?? ((obj["multiple"] as? Int).map { $0 != 0 } ?? false)
    }
}

/// An approval request with everything the Mac sends: which engine asked
/// (Claude Code and Codex answer "always" differently), the arguments, and a
/// diff when the tool writes a file.
struct ApprovalPrompt: Identifiable, Hashable {
    var id: String
    var name: String
    var reason: String
    var args: [(key: String, value: String)]
    var claude: Bool
    var codex: Bool
    var suggestedPattern: String
    var suggestions: [String]
    var diff: String?
    var diffPath: String?
    /// The project this chat belongs to, when it belongs to one: the scope between
    /// "for this chat" and "everywhere" — "let pytest run here".
    var projectID: String?
    var projectName: String?

    static func == (a: ApprovalPrompt, b: ApprovalPrompt) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }

    init?(_ obj: [String: Any]?) {
        guard let obj, let id = obj["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        name = (obj["name"] as? String) ?? "tool"
        reason = (obj["reason"] as? String) ?? ""
        let a = (obj["args"] as? [String: Any]) ?? [:]
        args = a.map { (key: $0.key, value: "\($0.value)") }.sorted { $0.key < $1.key }
        claude = (obj["claude"] as? Bool) ?? false
        codex = (obj["codex"] as? Bool) ?? false
        suggestedPattern = (obj["suggested_pattern"] as? String) ?? "*"
        suggestions = ((obj["suggestions"] as? [Any]) ?? []).map { "\($0)" }
        let d = obj["diff"] as? [String: Any]
        diff = d?["diff"] as? String
        diffPath = d?["path"] as? String
        let pr = obj["project"] as? [String: Any]
        projectID = pr?["id"] as? String
        projectName = (pr?["name"] as? String) ?? projectID
    }
}

/// What `/api/approve` is told. `always` means a saved rule — or, for Codex,
/// its own approval for the rest of that session.
struct ApprovalReply {
    var allow: Bool
    var always = false
    var pattern: String? = nil
    var note: String? = nil
    /// A reason given with Deny; the model reads it and changes course.
    var message: String? = nil

    var body: [String: Any] {
        var b: [String: Any] = ["allow": allow]
        if always { b["always"] = true }
        if let pattern { b["pattern"] = pattern }
        if let note { b["note"] = note }
        if let message, !message.isEmpty { b["message"] = message }
        return b
    }
}

/// Chat-action state the app keeps beside the transcript. One value on
/// `AppState`, so the shared object grows by a single property.
struct ChatExtras {
    var question: AskQuestion?
    var approval: ApprovalPrompt?
    /// Plan mode for the open chat: it may read and propose, and change nothing.
    var planMode = false
    /// What the open chat remembers for itself. Empty means it follows Orbit's
    /// own settings, which is what a chat does until you change something in it.
    var prefs: [String: JSONValue] = [:]
    /// Easy mode in the open chat: a small model is offered only the essential
    /// tools. The Mac resolves it, since a chat that never set one follows Orbit's.
    var easyMode = false
    /// The temporary chat opened from this phone, if any — the only one burn may erase.
    var tempSid: String?
    /// The answer stopped at its round or time limit; offer to continue.
    var roundLimit: String?
    /// Chats waiting for you: an approval or a question is open.
    var waiting: Set<String> = []
    /// A short message at the bottom of the screen.
    var toast: String?
    /// The last chat moved to the bin from the list, for Undo.
    var binned: (sid: String, name: String, title: String)?
    /// A `!` command the Mac wants confirmed before it runs.
    var bangConfirm: BangConfirm?
    /// Bumped when the permission mode changes from the mode line, so the work bar reads it again.
    var workRevision = 0
}

// ------------------------------------------------------------------ per answer

struct TokenUsage: Codable, Hashable {
    var prompt_tokens: Int?
    var completion_tokens: Int?

    enum CodingKeys: String, CodingKey { case prompt_tokens, completion_tokens }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        prompt_tokens = c.lenientDouble(.prompt_tokens).map { Int($0) }
        completion_tokens = c.lenientDouble(.completion_tokens).map { Int($0) }
    }
}

extension Message {
    /// "12.4 s · 1,203 tok · 97.0 tok/s" from what the Mac saved with the answer.
    var statsLine: String? {
        var parts: [String] = []
        if let s = secs, s.isFinite { parts.append(Self.duration(s)) }
        if let out = usage?.completion_tokens, out > 0 {
            parts.append("\(out.formatted()) tok")
            if let s = secs, s > 0 { parts.append(String(format: "%.1f tok/s", Double(out) / s)) }
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var undoableChanges: [String] {
        guard changes_undone != true, t != nil else { return [] }
        return changes ?? []
    }

    static func duration(_ s: Double) -> String {
        if s < 60 { return String(format: "%.1f s", s) }
        let m = Int(s) / 60, r = Int(s) % 60
        if m < 60 { return "\(m)m \(r)s" }
        return "\(m / 60)h \(m % 60)m"
    }

    /// The answer without Markdown markup, for pasting somewhere plain.
    var plainText: String {
        MarkdownText.Block.parse(text).map { block -> String in
            switch block {
            case .code(_, let code): return code
            case .math(let tex): return tex
            case .rule: return ""
            case .table(let rows): return rows.map { $0.map(Self.strip).joined(separator: "\t") }.joined(separator: "\n")
            case .text(let s), .heading(_, let s): return Self.strip(s)
            case .list(let items):
                return items.map { String(repeating: "  ", count: $0.depth) + ($0.number ?? "•") + " " + Self.strip($0.text) }
                    .joined(separator: "\n")
            case .quote(_, let title, let body):
                return ([title].compactMap { $0 } + [Message(role: "assistant", text: body).plainText]).joined(separator: "\n")
            }
        }
        .filter { !$0.isEmpty }
        .joined(separator: "\n\n")
    }

    private static func strip(_ s: String) -> String {
        String(MarkdownText.attributed(s).characters)
    }
}

/// One DOI checked against Crossref.
struct CitationRow: Codable, Hashable, Identifiable {
    var doi: String
    var ok: Bool
    var title: String?
    var why: String?
    var id: String { doi }

    enum CodingKeys: String, CodingKey { case doi, ok, title, why }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        doi = (try? c.decode(String.self, forKey: .doi)) ?? "?"
        ok = c.lenientBool(.ok) ?? false
        title = try? c.decode(String.self, forKey: .title)
        why = try? c.decode(String.self, forKey: .why)
    }
}

// ------------------------------------------------------------------ usage

struct UsageStats: Decodable {
    struct ModelRow: Decodable, Hashable {
        var turns: Int
        var prompt_tokens: Int
        var completion_tokens: Int
        var seconds: Double
        enum CodingKeys: String, CodingKey { case turns, prompt_tokens, completion_tokens, seconds }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            turns = Int(c.lenientDouble(.turns) ?? 0)
            prompt_tokens = Int(c.lenientDouble(.prompt_tokens) ?? 0)
            completion_tokens = Int(c.lenientDouble(.completion_tokens) ?? 0)
            seconds = c.lenientDouble(.seconds) ?? 0
        }
    }
    struct DayRow: Decodable, Hashable {
        var turns: Int
        var tokens: Int
        enum CodingKeys: String, CodingKey { case turns, tokens }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            turns = Int(c.lenientDouble(.turns) ?? 0)
            tokens = Int(c.lenientDouble(.tokens) ?? 0)
        }
    }
    var turns: Int
    var models: [String: ModelRow]
    var tools: [String: Int]
    var by_day: [String: DayRow]

    enum CodingKeys: String, CodingKey { case turns, models, tools, by_day }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        turns = Int(c.lenientDouble(.turns) ?? 0)
        models = (try? c.decode([String: ModelRow].self, forKey: .models)) ?? [:]
        tools = (try? c.decode([String: Int].self, forKey: .tools)) ?? [:]
        by_day = (try? c.decode([String: DayRow].self, forKey: .by_day)) ?? [:]
    }
}

struct LedgerSummary: Decodable, Hashable {
    var turns: Int
    var prompt_tokens: Int
    var completion_tokens: Int
    var seconds: Double
    var tok_per_s: Double

    enum CodingKeys: String, CodingKey { case turns, prompt_tokens, completion_tokens, seconds, tok_per_s }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        turns = Int(c.lenientDouble(.turns) ?? 0)
        prompt_tokens = Int(c.lenientDouble(.prompt_tokens) ?? 0)
        completion_tokens = Int(c.lenientDouble(.completion_tokens) ?? 0)
        seconds = c.lenientDouble(.seconds) ?? 0
        tok_per_s = c.lenientDouble(.tok_per_s) ?? 0
    }
}

// ------------------------------------------------------------------ projects

/// A project as the Mac stores it, with the fields its editor changes.
struct ProjectDetail: Identifiable, Hashable {
    var id: String
    var name: String
    var description: String
    var instructions: String
    var color: String
    var folder: String
    var trustTools: Bool
    var order: Double

    static let colors = ["#6b5bd6", "#2d7d4f", "#a8721c", "#c0392b", "#2b7a9b", "#8e44ad"]

    init(id: String, _ obj: [String: Any]) {
        self.id = id
        name = (obj["name"] as? String) ?? "Untitled project"
        description = (obj["description"] as? String) ?? ""
        instructions = (obj["instructions"] as? String) ?? ""
        color = (obj["color"] as? String) ?? Self.colors[0]
        folder = (obj["folder"] as? String) ?? ""
        trustTools = (obj["trust_tools"] as? Bool) ?? false
        order = (obj["order"] as? Double) ?? Double((obj["order"] as? Int) ?? 0)
    }

    init(new: Void = ()) {
        id = ""; name = ""; description = ""; instructions = ""
        color = Self.colors[0]; folder = ""; trustTools = false; order = 0
    }
}

// ------------------------------------------------------------------ chat list

/// Which chats the list shows.
enum ChatFilter: String, CaseIterable, Identifiable {
    case active, pinned, archived, all, attention
    var id: String { rawValue }
    var label: String {
        switch self {
        case .active: return "Active"
        case .pinned: return "Pinned"
        case .archived: return "Archived"
        case .all: return "All"
        case .attention: return "Needs attention"
        }
    }
    var icon: String {
        switch self {
        case .active: return "tray"
        case .pinned: return "pin"
        case .archived: return "archivebox"
        case .all: return "tray.2"
        case .attention: return "exclamationmark.circle"
        }
    }
}

/// What a row says about its chat, in the order the Mac's list ranks them.
enum ChatRowStatus: Equatable {
    case waiting, answering, queued(Int), unread, scheduled(Double), none

    /// Answering, waiting for you, queued, or new since you looked.
    var needsAttention: Bool {
        switch self {
        case .waiting, .answering, .queued, .unread: return true
        case .scheduled, .none: return false
        }
    }

    var label: String? {
        switch self {
        case .waiting: return "waiting for you"
        case .answering: return "answering"
        case .queued(let n): return "\(n) queued"
        case .unread: return "new"
        case .scheduled(let at): return "scheduled " + When.describe(Date(timeIntervalSince1970: at))
        case .none: return nil
        }
    }
}

/// When you last looked at each chat on this phone, so an answer that landed
/// since shows as new. Chats never opened here are not marked.
enum SeenChats {
    private static let key = "orbit.seenChats"

    static func all() -> [String: Double] {
        (UserDefaults.standard.dictionary(forKey: key) as? [String: Double]) ?? [:]
    }

    static func mark(_ sid: String, mtime: Double) {
        var d = all()
        d[sid] = max(mtime, Date.now.timeIntervalSince1970)
        if d.count > 400 {
            for k in d.sorted(by: { $0.value < $1.value }).prefix(d.count - 400).map(\.key) { d.removeValue(forKey: k) }
        }
        UserDefaults.standard.set(d, forKey: key)
    }

    static func isUnread(_ chat: ChatSummary, seen: [String: Double]) -> Bool {
        guard let t = seen[chat.id] else { return false }
        return chat.mtime > t + 2
    }
}
