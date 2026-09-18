import Foundation

/// Tool calls said the way Claude Code says them — `⏺ Read notes.md`, then
/// `⎿ Read 32 lines` — plus the other shapes the rebuilt web UI shows: todo
/// lists, `!` shell runs, and what fills the context window. The wording and
/// rules follow the Mac's web UI (TOOLNAME, resultSummary…) so the two read alike.

// ------------------------------------------------------------------ one call

/// One tool call: live (running until its result arrives) or saved with a
/// message as `tool_runs`.
struct ToolRun: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    /// Every argument as text; objects and lists as compact JSON.
    var args: [String: String]
    var ok: Bool?
    var secs: Double?
    var output: String?
    /// Lines a file edit added and removed, when the Mac sent a diff.
    var added: Int?
    var removed: Int?
    /// False while a live call is still running.
    var done = true
    /// It never reported back: the answer ended or was stopped first.
    var stopped = false
    /// When a live call began, for its running clock. Not saved.
    var startedAt: Date?
    /// Worked out once, not on every redraw: a large JSON result is costly to read.
    private(set) var summary = ""

    var display: String { ToolText.display(name) }
    var target: String { ToolText.target(name, args) }
    var family: String? { ToolText.family[display] }
    var failed: Bool { ok == false || stopped }
    var running: Bool { !done }
    /// Arguments in a stable order, for the expanded row.
    var argsText: String {
        args.keys.sorted().map { "\($0): \(String(args[$0]!.prefix(600)))" }.joined(separator: "\n")
    }

    enum CodingKeys: String, CodingKey {
        case id, name, args, ok, secs, output, added, removed, done, stopped
        case summary = "ios_summary"
    }

    init(id: String, name: String, args: [String: String]) {
        self.id = id.isEmpty ? UUID().uuidString : id
        self.name = name
        self.args = args
        done = false
        startedAt = Date()
    }

    /// A live `tool` or `tool_result` event's payload.
    init(event d: [String: Any], finished: Bool) {
        id = (d["id"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? UUID().uuidString
        name = (d["name"] as? String) ?? "tool"
        args = ToolText.stringify((d["args"] as? [String: Any]) ?? [:])
        done = finished
        startedAt = finished ? nil : Date()
        guard finished else { return }
        ok = d["ok"] as? Bool
        secs = (d["secs"] as? Double) ?? (d["secs"] as? Int).map(Double.init)
        if let s = d["output"] as? String { output = s }
        else if let o = d["output"], !(o is NSNull) { output = ToolText.json(o) }
        if let diff = d["diff"] as? [String: Any] {
            added = (diff["added"] as? Int) ?? (diff["added"] as? Double).map { Int($0) }
            removed = (diff["removed"] as? Int) ?? (diff["removed"] as? Double).map { Int($0) }
        }
        finish()
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = c.lenientString(.id) ?? UUID().uuidString
        name = (try? c.decode(String.self, forKey: .name)) ?? "tool"
        let raw = (try? c.decode([String: JSONValue].self, forKey: .args)) ?? [:]
        args = raw.mapValues(ToolText.text)
        ok = c.lenientBool(.ok)
        secs = c.lenientDouble(.secs)
        if let s = try? c.decode(String.self, forKey: .output) { output = s }
        else if let v = try? c.decode(JSONValue.self, forKey: .output), !v.isNull { output = ToolText.text(v) }
        added = c.lenientDouble(.added).map { Int($0) }
        removed = c.lenientDouble(.removed).map { Int($0) }
        done = c.lenientBool(.done) ?? true
        stopped = c.lenientBool(.stopped) ?? false
        if let s = try? c.decode(String.self, forKey: .summary), !s.isEmpty { summary = s } else { finish() }
    }

    /// The offline copy keeps the start of a long output; the summary line was
    /// worked out from all of it and is kept as it was.
    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(name, forKey: .name)
        try c.encode(args.mapValues { String($0.prefix(2000)) }, forKey: .args)
        try c.encodeIfPresent(ok, forKey: .ok)
        try c.encodeIfPresent(secs, forKey: .secs)
        try c.encodeIfPresent(output.map { String($0.prefix(4000)) }, forKey: .output)
        try c.encodeIfPresent(added, forKey: .added)
        try c.encodeIfPresent(removed, forKey: .removed)
        try c.encode(done, forKey: .done)
        try c.encode(stopped, forKey: .stopped)
        try c.encode(summary, forKey: .summary)
    }

    /// Fill in the one-line result, once the call is over.
    mutating func finish() {
        summary = done ? ToolText.summary(self) : ""
    }

    /// Take a live result into the running row it answers.
    mutating func complete(with r: ToolRun) {
        ok = r.ok
        secs = r.secs ?? startedAt.map { Date().timeIntervalSince($0) }
        output = r.output
        added = r.added ?? added
        removed = r.removed ?? removed
        if args.isEmpty { args = r.args }
        done = true
        finish()
    }

    /// The answer ended before this call came back.
    mutating func markStopped() {
        guard !done else { return }
        done = true
        stopped = true
        secs = startedAt.map { Date().timeIntervalSince($0) }
        finish()
    }
}

/// A file edit shown while an answer ran, for /diff.
struct ShownDiff: Identifiable, Hashable {
    let id = UUID()
    var path: String
    var diff: String
    var added: Int
    var removed: Int
    var existed: Bool

    init?(_ obj: Any?) {
        guard let d = obj as? [String: Any], let text = d["diff"] as? String, !text.isEmpty else { return nil }
        path = (d["path"] as? String) ?? ""
        diff = text
        added = (d["added"] as? Int) ?? 0
        removed = (d["removed"] as? Int) ?? 0
        existed = (d["existed"] as? Bool) ?? true
    }
}

// ------------------------------------------------------------------ wording

enum ToolText {
    /// Every tool a model can call — Orbit's own, Claude Code's, Codex's — by
    /// the name Claude Code gives it.
    static let names: [String: String] = [
        "read_file": "Read", "Read": "Read", "NotebookRead": "Read", "read_chat": "Read chat",
        "write_file": "Write", "Write": "Write", "edit_file": "Update", "Edit": "Update", "MultiEdit": "Update",
        "multi_edit": "Update", "NotebookEdit": "Edit notebook", "apply_patch": "Update",
        "run_shell": "Bash", "Bash": "Bash", "shell": "Bash", "BashOutput": "Bash output", "KillShell": "Kill shell",
        "run_shell_background": "Bash (background)", "check_background": "Background", "list_background": "Background",
        "python": "Python", "glob": "Search", "Glob": "Search", "grep_files": "Search", "Grep": "Search",
        "search_knowledge": "Search", "search_chats": "Search chats", "search_agent_memory": "Search memory",
        "list_dir": "List", "LS": "List", "web_search": "Web Search", "WebSearch": "Web Search",
        "fetch_url": "Fetch", "WebFetch": "Fetch", "fetch_paper_pdf": "Fetch paper", "http_json": "Fetch",
        "task": "Agent", "Task": "Agent", "Agent": "Agent", "TodoWrite": "Todos", "plan": "Plan",
        "TaskCreate": "Todos", "TaskUpdate": "Todos", "remember": "Remember", "use_skill": "Skill",
        "cluster_run": "Cluster", "cluster_submit": "Cluster", "cluster_status": "Cluster", "cluster_ls": "Cluster",
        "cluster_read": "Cluster", "cluster_qdel": "Cluster", "ask_user": "Ask",
    ]
    /// What a call says while it is still running.
    static let verbs: [String: String] = [
        "Read": "Reading", "Write": "Writing", "Update": "Editing", "Edit notebook": "Editing",
        "Bash": "Running", "Python": "Running", "Search": "Searching", "Search chats": "Searching",
        "Search memory": "Searching", "Web Search": "Searching", "List": "Listing", "Fetch": "Fetching",
        "Fetch paper": "Fetching", "Agent": "Running task", "Cluster": "Running", "Plan": "Planning",
        "Todos": "Updating todos",
    ]
    /// Calls that only look things up: several in a row fold into one line.
    static let family: [String: String] = [
        "Read": "read", "Search": "search", "Search chats": "search", "Search memory": "search",
        "Web Search": "search", "List": "list", "Fetch": "fetch", "Fetch paper": "fetch",
    ]
    static let familyWords: [String: (String, String, String)] = [
        "read": ("Read", "file", "files"), "search": ("Searched for", "pattern", "patterns"),
        "list": ("Listed", "directory", "directories"), "fetch": ("Fetched", "page", "pages"),
    ]

    static func display(_ n: String) -> String {
        let n = n.isEmpty ? "tool" : n
        if let d = names[n] { return d }
        if n.hasPrefix("mcp__") {
            return (n.components(separatedBy: "__").last ?? n).replacingOccurrences(of: "_", with: " ")
        }
        if n.contains(".") { return (n.split(separator: ".").last.map(String.init) ?? n).replacingOccurrences(of: "_", with: " ") }
        return n.replacingOccurrences(of: "_", with: " ")
    }

    static func verb(_ display: String) -> String { verbs[display] ?? display }

    static func shortPath(_ s: String) -> String {
        let p = s.split(separator: "/").map(String.init)
        if p.count > 2 { return p.suffix(2).joined(separator: "/") }
        return s.hasPrefix("~/") ? String(s.dropFirst(2)) : s
    }

    private static func oneLine(_ s: String) -> String {
        s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    /// The target the way Claude Code writes it: a path for file tools, the
    /// command for a shell call, the pattern for a search.
    static func target(_ name: String, _ args: [String: String]) -> String {
        let disp = display(name)
        let fp = args["file_path"] ?? args["notebook_path"] ?? args["path"] ?? args["file"]
        if let fp, ["Read", "Write", "Update", "Edit notebook", "List"].contains(disp) { return shortPath(fp) }
        if disp == "Bash" || disp == "Python" {
            var c = oneLine(args["command"] ?? args["code"] ?? args["script"] ?? "")
            // Codex wraps every command in a login shell: show the command itself
            if let r = c.range(of: #"^(?:/(?:usr/)?bin/)?(?:ba|z)?sh -l?c (['"])([\s\S]*)\1$"#, options: .regularExpression),
               r == c.startIndex..<c.endIndex {
                let quote = c.first(where: { $0 == "'" || $0 == "\"" }) ?? "'"
                if let open = c.firstIndex(of: quote), let close = c.lastIndex(of: quote), open < close {
                    c = String(c[c.index(after: open)..<close])
                }
            }
            return String(c.prefix(120))
        }
        if disp == "Search" {
            return String((args["pattern"] ?? args["query"] ?? args["glob"] ?? "").prefix(90))
                + (args["path"].map { " in " + shortPath($0) } ?? "")
        }
        if disp == "Fetch" || disp == "Web Search" { return String((args["url"] ?? args["query"] ?? "").prefix(90)) }
        if disp == "Agent" { return String(oneLine(args["description"] ?? args["prompt"] ?? "").prefix(90)) }
        for k in ["description", "query", "url", "path", "pattern", "name", "command"] {
            if let v = args[k], !v.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return String(oneLine(v).prefix(90))
            }
        }
        return ""
    }

    static func nLines(_ s: String) -> Int {
        guard !s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return 0 }
        var t = Substring(s)
        while t.hasSuffix("\n") { t = t.dropLast() }
        return t.split(separator: "\n", omittingEmptySubsequences: false).count
    }

    static func plural(_ n: Int, _ one: String, _ many: String) -> String { "\(n) \(n == 1 ? one : many)" }

    private static func firstLine(_ s: String) -> String? {
        s.split(separator: "\n").first { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.map(String.init)
    }

    /// What came back, in one phrase — "Wrote 32 lines to notes.md", "Found 12 matches".
    static func summary(_ p: ToolRun) -> String {
        let out = p.output ?? ""
        let disp = p.display
        if p.stopped { return "stopped before it came back" }
        // Orbit's shell tools answer "exit=N\nstdout:\n…\nstderr:\n…": lead with what it printed
        if let sh = shell(out) {
            let printed = sh.stdout.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? sh.stderr : sh.stdout
            let first = firstLine(printed) ?? "(No output)"
            let rest = max(0, nLines(printed) - 1)
            return (sh.code != "0" ? "exit \(sh.code) · " : "") + String(oneLine(first).prefix(150))
                + (rest > 0 ? "  +" + plural(rest, "line", "lines") : "")
        }
        if p.ok == false { return String(oneLine(firstLine(out) ?? "failed").prefix(160)) }
        if p.added != nil || p.removed != nil {
            return "Added " + plural(p.added ?? 0, "line", "lines") + ", removed " + plural(p.removed ?? 0, "line", "lines")
        }
        if out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return disp == "Bash" || disp == "Python" ? "(No output)" : "(No content)"
        }
        switch disp {
        case "Read": return "Read " + plural(nLines(out), "line", "lines")
        case "Write":
            let n = firstInt(out, #"(\d+)\s+lines?"#) ?? nLines(p.args["content"] ?? p.args["text"] ?? "")
            let to = p.args["file_path"] ?? p.args["path"]
            return "Wrote " + plural(n > 0 ? n : nLines(out), "line", "lines") + (to.map { " to " + shortPath($0) } ?? "")
        case "Update", "Edit notebook":
            if let m = groups(out, #"(\d+)\s+(?:insertions?|additions?)[^\d]+(\d+)"#), m.count == 3,
               let a = Int(m[1]), let r = Int(m[2]) {
                return "Added " + plural(a, "line", "lines") + ", removed " + plural(r, "line", "lines")
            }
            return String(oneLine(firstLine(out) ?? "").prefix(160))
        case "Search", "Search chats", "Search memory":
            if out.range(of: #"^\s*(no matches|nothing found|\[\]|none)"#, options: [.regularExpression, .caseInsensitive]) != nil {
                return "No matches found"
            }
            if let n = firstInt(out, #"(\d+)\s+(?:match|hit|result)"#, caseless: true) {
                return "Found " + plural(n, "match", "matches")
            }
            return "Found " + plural(nLines(out), "result", "results")
        case "List": return plural(nLines(out), "entry", "entries")
        case "Web Search", "Fetch", "Fetch paper":
            let n = nLines(out) > 1 ? nLines(out) : max(1, Int((Double(out.count) / 1000).rounded()))
            return plural(n, "line", "lines") + " back"
        case "Todos", "Plan": return "Todos updated"
        default: break
        }
        // JSON back: say what is in it on one line rather than "{ +40 lines"
        let tr = out.trimmingCharacters(in: .whitespacesAndNewlines)
        if tr.hasPrefix("{") || tr.hasPrefix("[") {
            if tr.utf8.count < 400_000, let data = tr.data(using: .utf8),
               let j = try? JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed]) {
                return jsonSummary(j, source: tr)
            }
            let pairs = jsonPairs(String(tr.prefix(800)))
            if !pairs.isEmpty { return pairs.joined(separator: " · ") }
        }
        let rest = nLines(out) - 1
        return String(oneLine(firstLine(out) ?? "").prefix(160)) + (rest > 0 ? "  +" + plural(rest, "line", "lines") : "")
    }

    static func jsonSummary(_ j: Any, source: String) -> String {
        if let a = j as? [Any] { return a.isEmpty ? "(empty list)" : plural(a.count, "item", "items") }
        if let o = j as? [String: Any] {
            if let e = o["error"], !(e is NSNull) { return String("\(e)".prefix(160)) }
            var parts: [String] = []
            // the keys in the order the tool wrote them, as the web shows them
            var keys = topLevelKeys(source).filter { o[$0] != nil }
            if keys.count != o.count { keys = o.keys.sorted() }
            for k in keys {
                let v = o[k]!
                let val: String
                if let a = v as? [Any] { val = "\(a.count) \(a.count == 1 ? "item" : "items")" }
                else if v is [String: Any] { val = "{…}" }
                else { val = String(oneLine(scalar(v)).prefix(40)) }
                parts.append("\(k): \(val)")
                if parts.joined(separator: " · ").count > 150 { break }
            }
            return parts.isEmpty ? "(empty)" : parts.joined(separator: " · ")
        }
        return String(scalar(j).prefix(160))
    }

    private static func scalar(_ v: Any) -> String {
        if v is NSNull { return "null" }
        if let n = v as? NSNumber {
            if CFGetTypeID(n) == CFBooleanGetTypeID() { return n.boolValue ? "true" : "false" }
            return n.stringValue
        }
        return "\(v)"
    }

    /// `"key": value` pairs from JSON too long or broken to parse.
    private static func jsonPairs(_ s: String) -> [String] {
        guard let re = try? NSRegularExpression(
            pattern: #""([\w .-]{1,30})"\s*:\s*("(?:[^"\\]|\\.){0,40}"|-?[\d.]+|true|false|null|\[|\{)"#) else { return [] }
        return re.matches(in: s, range: NSRange(s.startIndex..., in: s)).prefix(6).compactMap { m in
            guard let k = Range(m.range(at: 1), in: s), let v = Range(m.range(at: 2), in: s) else { return nil }
            var val = String(s[v])
            if val == "[" { val = "[…]" } else if val == "{" { val = "{…}" }
            else if val.hasPrefix("\"") { val = String(val.dropFirst().dropLast()) }
            return "\(s[k]): \(val)"
        }
    }

    /// The keys of a JSON object at its top level, in order.
    static func topLevelKeys(_ s: String) -> [String] {
        var keys: [String] = []
        var depth = 0, inString = false, escaped = false
        var current = ""
        var lastString: String?
        for ch in s {
            if inString {
                if escaped { escaped = false; current.append(ch) }
                else if ch == "\\" { escaped = true }
                else if ch == "\"" { inString = false; lastString = current }
                else { current.append(ch) }
                continue
            }
            switch ch {
            case "\"": inString = true; current = ""
            case "{", "[": depth += 1; lastString = nil
            case "}", "]":
                depth -= 1; lastString = nil
                if depth == 0 { return keys }
            case ":":
                if depth == 1, let k = lastString { keys.append(k) }
                lastString = nil
            default:
                if !ch.isWhitespace { lastString = nil }
            }
        }
        return keys
    }

    static func shell(_ out: String) -> (code: String, stdout: String, stderr: String)? {
        guard out.hasPrefix("exit="), let nl = out.firstIndex(of: "\n") else { return nil }
        let code = String(out[out.index(out.startIndex, offsetBy: 5)..<nl])
        guard Int(code) != nil else { return nil }
        let after = out[out.index(after: nl)...]
        guard after.hasPrefix("stdout:\n") else { return nil }
        let body = after.dropFirst("stdout:\n".count)
        if let r = body.range(of: "\nstderr:\n") {
            return (code, String(body[..<r.lowerBound]), String(body[r.upperBound...]))
        }
        return (code, String(body), "")
    }

    private static func groups(_ s: String, _ pattern: String, caseless: Bool = false) -> [String]? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: caseless ? [.caseInsensitive] : []),
              let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
        return (0..<m.numberOfRanges).map { Range(m.range(at: $0), in: s).map { String(s[$0]) } ?? "" }
    }

    private static func firstInt(_ s: String, _ pattern: String, caseless: Bool = false) -> Int? {
        groups(String(s.prefix(20_000)), pattern, caseless: caseless).flatMap { $0.count > 1 ? Int($0[1]) : nil }
    }

    /// "Read 3 files, Searched for 1 pattern".
    static func familyLabel(_ runs: [ToolRun]) -> String {
        var order: [String] = []
        var counts: [String: Int] = [:]
        for r in runs {
            guard let f = r.family else { continue }
            if counts[f] == nil { order.append(f) }
            counts[f, default: 0] += 1
        }
        return order.map { f in
            let w = familyWords[f] ?? ("Ran", "call", "calls")
            return w.0 + " " + plural(counts[f]!, w.1, w.2)
        }.joined(separator: ", ")
    }

    /// 0.4s, 12s, 3m 05s, 1h 02m — as the web writes durations.
    static func secs(_ s: Double) -> String {
        let s = s.isFinite ? max(0, s) : 0
        if s < 9.95 { return String(format: "%.1fs", s) }
        let r = Int(s.rounded())
        if r < 60 { return "\(r)s" }
        if r < 3600 { return "\(r / 60)m " + String(format: "%02ds", r % 60) }
        let m = Int((Double(r) / 60).rounded())
        return "\(m / 60)h " + String(format: "%02dm", m % 60)
    }

    // ---- argument text

    static func stringify(_ d: [String: Any]) -> [String: String] {
        d.mapValues { v in
            if let s = v as? String { return s }
            if v is [Any] || v is [String: Any] { return json(v) }
            return scalar(v)
        }
    }

    static func json(_ v: Any) -> String {
        guard JSONSerialization.isValidJSONObject(v),
              let d = try? JSONSerialization.data(withJSONObject: v, options: [.sortedKeys, .withoutEscapingSlashes])
        else { return "\(v)" }
        return String(decoding: d, as: UTF8.self)
    }

    static func text(_ v: JSONValue) -> String {
        switch v {
        case .string(let s): return s
        case .null: return "null"
        case .bool(let b): return b ? "true" : "false"
        case .number(let n): return n == n.rounded() && abs(n) < 1e15 ? String(Int(n)) : String(n)
        case .array, .object:
            let enc = JSONEncoder()
            enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
            return (try? enc.encode(v)).map { String(decoding: $0, as: UTF8.self) } ?? ""
        }
    }
}

// ------------------------------------------------------------------ fold

/// Consecutive finished look-ups fold into one line; anything else stands alone.
enum ToolFold: Identifiable {
    case single(ToolRun, key: String)
    case group([ToolRun], key: String)

    var id: String {
        switch self {
        case .single(_, let k), .group(_, let k): return k
        }
    }

    static func fold(_ runs: [ToolRun]) -> [ToolFold] {
        var out: [ToolFold] = []
        var pending: [ToolRun] = []
        var start = 0
        func flush() {
            if pending.count >= 2 { out.append(.group(pending, key: "g\(start)")) }
            else if let one = pending.first { out.append(.single(one, key: "s\(start)")) }
            pending = []
        }
        for (i, r) in runs.enumerated() {
            let foldable = r.family != nil && r.done && !r.failed
            if foldable {
                if pending.isEmpty { start = i }
                pending.append(r)
            } else {
                flush()
                out.append(.single(r, key: "s\(i)"))
            }
        }
        flush()
        return out
    }
}

// ------------------------------------------------------------------ todos

/// One step of the plan tool's list.
struct PlanStep: Hashable {
    var done: Bool
    var active: Bool
    var text: String

    /// Claude Code's marks: ☒ done, ◼ in hand, ☐ still to do.
    var mark: String { done ? "\u{2612}" : active ? "\u{25FC}" : "\u{2610}" }

    /// Lines like `0. [x] step`, `1. [>] step`, `2. [ ] step`.
    static func parse(_ out: String) -> [PlanStep] {
        var steps: [PlanStep] = []
        for line in out.split(separator: "\n") {
            guard let dot = line.firstIndex(of: "."), Int(line[..<dot]) != nil else { continue }
            let rest = line[line.index(after: dot)...]
            guard rest.hasPrefix(" ["), rest.count >= 4 else { continue }
            let mark = rest[rest.index(rest.startIndex, offsetBy: 2)]
            guard rest[rest.index(rest.startIndex, offsetBy: 3)] == "]" else { continue }
            let text = rest.dropFirst(4).trimmingCharacters(in: .whitespaces)
            steps.append(PlanStep(done: mark == "x", active: mark == ">", text: text))
        }
        // nothing marked as in hand: it is the first one not done, as in Claude Code's list
        if !steps.isEmpty, !steps.contains(where: \.active), let i = steps.firstIndex(where: { !$0.done }) {
            steps[i].active = true
        }
        return steps
    }

    /// The plan in force: the last one written since your last message.
    static func current(in messages: [Message]) -> [PlanStep]? {
        var last: String?
        for m in messages {
            if m.isUser {
                if m.note != true && !m.text.lowercased().hasPrefix("continue") { last = nil }
                continue
            }
            if let p = m.plan, !p.isEmpty { last = p }
            for r in m.tool_runs ?? [] where r.name == "plan" { if let o = r.output, !o.isEmpty { last = o } }
        }
        guard let last else { return nil }
        let steps = parse(last)
        return steps.isEmpty ? nil : steps
    }
}

// ------------------------------------------------------------------ ! shell runs

/// A command you ran with `!` in the composer, and what it printed.
struct BangRun: Codable, Hashable {
    var cmd: String
    var rc: Int
    var secs: Double?
    var host: String?
    var out: String
    /// Still running on the Mac; shown as a placeholder. Not saved.
    var running = false

    enum CodingKeys: String, CodingKey { case cmd, rc, secs, host, out }

    init(cmd: String, rc: Int, secs: Double?, host: String?, out: String, running: Bool = false) {
        self.cmd = cmd; self.rc = rc; self.secs = secs; self.host = host; self.out = out; self.running = running
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        cmd = (try? c.decode(String.self, forKey: .cmd)) ?? ""
        rc = c.lenientDouble(.rc).map { Int($0) } ?? 0
        secs = c.lenientDouble(.secs)
        host = try? c.decode(String.self, forKey: .host)
        out = (try? c.decode(String.self, forKey: .out)) ?? ""
    }

    /// "exit 0 · 1.2s · on host"
    var meta: String {
        if running { return "running…" }
        return "exit \(rc)" + (secs.map { " · " + ToolText.secs($0) } ?? "")
            + (host.flatMap { $0.isEmpty ? nil : " · on \($0)" } ?? "")
    }
}

/// A command the Mac wants you to confirm before it runs.
struct BangConfirm: Identifiable, Hashable {
    let id = UUID()
    var cmd: String
    var reason: String
}

// ------------------------------------------------------------------ one answer, one block

extension Message {
    /// How long this step thought: measured live, or from when its thinking
    /// began to when the step was written.
    var thoughtFor: Double? {
        if let thoughtSecs { return thoughtSecs }
        guard let first = thinking_marks?.first, first.count > 1, let t, t > first[1] else { return nil }
        return t - first[1]
    }

    /// A saved step with nothing but tool calls: it joins the step before it,
    /// so its calls fold together with those.
    var onlyToolCalls: Bool {
        !isUser && text.isEmpty && (thinking ?? "").isEmpty && (plots ?? []).isEmpty
            && !(tool_runs ?? []).isEmpty && (changes ?? []).isEmpty && secs == nil && usage == nil
    }
}

/// A message as the transcript draws it.
struct TranscriptRow: Identifiable {
    /// Its position in the chat's messages.
    var index: Int
    var message: Message
    /// Only the first step of an answer names the model.
    var showByline: Bool
    /// A step with nothing but tool calls, drawn tucked under the step before it.
    var joinsPrevious = false
    var id: UUID { message.id }

    /// One row per message; bylines only where an answer begins. (Merging tool-only steps
    /// into one tall row left the lazy transcript blank on long chats, so they stay their
    /// own rows and are drawn close under the step before instead.)
    static func build(_ messages: [Message]) -> [TranscriptRow] {
        var rows: [TranscriptRow] = []
        rows.reserveCapacity(messages.count)
        for (i, m) in messages.enumerated() {
            let afterAnswer = rows.last.map { !$0.message.isUser } ?? false
            rows.append(TranscriptRow(index: i, message: m, showByline: m.isUser || !afterAnswer,
                                      joinsPrevious: afterAnswer && m.onlyToolCalls))
        }
        return rows
    }
}

// ------------------------------------------------------------------ context

/// What fills the open chat's context window, from `/api/context`.
struct ContextDetail {
    var used: Int
    var max: Int
    var pct: Double
    var basis: String?
    /// Largest first.
    var parts: [(name: String, tokens: Int)]
    var images: Int
    var messages: Int
    var free: Int
    var autocompactAt: Double?

    init(json o: [String: Any]) {
        func int(_ k: String) -> Int { (o[k] as? Int) ?? (o[k] as? Double).map { Int($0) } ?? 0 }
        used = int("used")
        max = int("max")
        pct = (o["pct"] as? Double) ?? Double(int("pct"))
        basis = o["basis"] as? String
        let raw = (o["parts"] as? [String: Any]) ?? [:]
        parts = raw.map { (name: $0.key, tokens: ($0.value as? Int) ?? ($0.value as? Double).map { Int($0) } ?? 0) }
            .sorted { $0.tokens > $1.tokens }
        images = int("images")
        messages = int("messages")
        free = o["free"] == nil ? Swift.max(0, max - used) : int("free")
        autocompactAt = (o["autocompact_at"] as? Double) ?? (o["autocompact_at"] as? Int).map(Double.init)
    }
}
