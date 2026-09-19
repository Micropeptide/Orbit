import Foundation

/// What a Claude Code subagent did, under the Agent call that started it: its steps
/// while it works, and "Done (12 tool uses · 34k tokens · 1m 5s)" when it finishes.
/// A subagent sent to the background reports after its call has returned.
struct SubagentInfo: Codable, Hashable {
    struct Step: Codable, Hashable {
        var name: String
        var args: [String: String]

        var line: String {
            let t = ToolText.target(name, args)
            return ToolText.display(name) + (t.isEmpty ? "" : " " + t)
        }
        enum CodingKeys: String, CodingKey { case name, args }
        init(name: String, args: [String: String]) { self.name = name; self.args = args }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            name = (try? c.decode(String.self, forKey: .name)) ?? "tool"
            args = ((try? c.decode([String: JSONValue].self, forKey: .args)) ?? [:]).mapValues(ToolText.text)
        }
    }

    var description = ""
    var type = ""
    var tools = 0
    var tokens = 0
    var secs: Double?
    var steps: [Step] = []
    var background = false
    var status: String?
    var summary: String?

    /// "Done (12 tool uses · 34k tokens · 1m 5s)", or "Running in the background".
    var line: String {
        if background { return "Running in the background" }
        var head = "Done"
        if let s = status, !s.isEmpty, !["completed", "done"].contains(s.lowercased()) { head = s.capitalized }
        var parts = [ToolText.plural(tools, "tool use", "tool uses")]
        if tokens > 0 { parts.append(HomeDashboard.tokens(tokens) + " tokens") }
        if let secs, secs > 0 { parts.append(ToolText.secs(secs)) }
        return head + " (" + parts.joined(separator: " · ") + ")"
    }

    enum CodingKeys: String, CodingKey { case description, type, tools, tokens, secs, steps, background, status, summary }
    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        description = c.lenientString(.description) ?? ""
        type = c.lenientString(.type) ?? ""
        tools = Int(c.lenientDouble(.tools) ?? 0)
        tokens = Int(c.lenientDouble(.tokens) ?? 0)
        secs = c.lenientDouble(.secs)
        steps = (try? c.decode([Step].self, forKey: .steps)) ?? []
        background = c.lenientBool(.background) ?? false
        status = c.lenientString(.status)
        summary = c.lenientString(.summary)
    }

    /// From a live event's payload (JSONSerialization).
    init?(any: Any?) {
        guard let d = any as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: d),
              let v = try? JSONDecoder().decode(SubagentInfo.self, from: data) else { return nil }
        self = v
    }
}
