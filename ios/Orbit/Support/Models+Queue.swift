import Foundation

// ------------------------------------------------------------------ composer state

/// What the composer keeps between screens that is not the draft itself: the open
/// chat's context gauge, which chats have news you have not looked at, long pastes
/// folded into chips, and the project the chat list is filtered to.
struct ComposerExtras {
    /// The open chat's context window, from `/api/status?sid=`.
    var context: ContextState?
    var contextSid: String?
    /// Chats already warned that the window is nearly full, so the line shows once.
    var contextWarned: Set<String> = []
    /// News per chat you were not looking at when it happened: an answer, an
    /// approval, a question, an error.
    var unseen: [String: Int] = [:]
    /// What the running-state poll saw last, so a change can be announced.
    var lastRunning: Set<String>?
    var lastWaiting: Set<String>?
    /// The project the chat list shows; a new chat starts in it.
    var projectFilter: String?

    var unseenTotal: Int { unseen.values.reduce(0, +) }
}

/// One answer's worth of the queue after a `now`: whether it went into the
/// running answer as a note, or was put first in line.
struct QueueNowResult {
    var interjected: Bool
    var queue: QueueState
}

// ------------------------------------------------------------------ send later

/// `/later` times in words, as the web reads them: "21:30", "9pm",
/// "tomorrow 9am", "mon 8:00", "in 2h", "in 45m", "daily 8:00", "weekdays 9am".
enum LaterParser {
    struct Parsed: Equatable {
        var at: Date
        var rep: Repeat
        var text: String
    }

    static func parse(_ raw: String, now: Date = .now, calendar: Calendar = .current) -> Parsed? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        var rep: Repeat = .once
        if let m = s.firstMatch(#"^(daily|every\s*day|weekdays|weekly)\s+"#) {
            let word = m[1].lowercased()
            rep = word.hasSuffix("weekly") ? .weekly : word == "weekdays" ? .weekdays : .daily
            s = String(s.dropFirst(m[0].count))
        }
        var at: Date
        if let m = s.firstMatch(#"^in\s+(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\b\s*"#) {
            let n = Double(m[1]) ?? 0
            let unit = m[2].lowercased().first
            let secs = unit == "m" ? 60.0 : unit == "h" ? 3600.0 : 86400.0
            at = now.addingTimeInterval(n * secs)
            s = String(s.dropFirst(m[0].count))
        } else {
            var day: String?
            if let m = s.firstMatch(#"^(today|tonight|tomorrow|tmr|mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+"#) {
                day = m[1].lowercased()
                s = String(s.dropFirst(m[0].count))
            }
            guard let m = s.firstMatch(#"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b\s*"#) else { return nil }
            // a bare number is a word in the message, not a time
            guard !m[2].isEmpty || !m[3].isEmpty else { return nil }
            var h = Int(m[1]) ?? 0
            let mi = Int(m[2]) ?? 0
            let ap = m[3].lowercased()
            if ap == "pm", h < 12 { h += 12 }
            if ap == "am", h == 12 { h = 0 }
            guard h <= 23, mi <= 59 else { return nil }
            s = String(s.dropFirst(m[0].count))
            guard var d = calendar.date(bySettingHour: h, minute: mi, second: 0, of: now) else { return nil }
            let weekdays = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
            if day == "tomorrow" || day == "tmr" {
                d = calendar.date(byAdding: .day, value: 1, to: d) ?? d
            } else if let day, let want = weekdays.firstIndex(of: String(day.prefix(3))) {
                let have = calendar.component(.weekday, from: d) - 1
                var add = (want - have + 7) % 7
                if add == 0, d <= now { add = 7 }
                d = calendar.date(byAdding: .day, value: add, to: d) ?? d
            } else if d <= now {
                d = calendar.date(byAdding: .day, value: 1, to: d) ?? d
            }
            at = d
        }
        return Parsed(at: at, rep: rep, text: s.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    static let usage = "/later 21:30 <message> · /later tomorrow 9am <message> · "
        + "/later in 2h <message> · /later daily 8:00 <message>"
}

private extension String {
    /// The first case-insensitive match of a pattern, as its groups ("" for a group
    /// that did not take part). Index 0 is the whole match.
    func firstMatch(_ pattern: String) -> [String]? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]),
              let m = re.firstMatch(in: self, range: NSRange(startIndex..., in: self)) else { return nil }
        return (0..<m.numberOfRanges).map { i in
            Range(m.range(at: i), in: self).map { String(self[$0]) } ?? ""
        }
    }
}

// ------------------------------------------------------------------ prompt history

/// The last 50 messages you sent, newest last, kept on this phone — the web's
/// Ctrl+R "Earlier messages".
enum PromptHistory {
    private static let key = "orbit.promptHistory"

    /// Oldest first, each text once (lists saved before `push` removed copies may have repeats).
    static func load() -> [String] {
        let raw = UserDefaults.standard.stringArray(forKey: key) ?? []
        var seen = Set<String>()
        return raw.reversed().filter { seen.insert($0).inserted }.reversed()
    }

    /// Sending something again moves it to the newest place rather than listing it
    /// twice: the history sheet names its rows by their text.
    static func push(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t.count <= 20_000 else { return }
        var h = load()
        h.removeAll { $0 == t }
        h.append(t)
        UserDefaults.standard.set(Array(h.suffix(50)), forKey: key)
    }
}

// ------------------------------------------------------------------ long pastes

/// A long paste folds into a chip — `[Pasted #3 · ~120 lines]` in the box —
/// and is put back in full when the message goes. Kept per chat with the draft,
/// so leaving and coming back does not lose it.
enum Pastes {
    static let minChars = 1200
    static let minLines = 12
    private static func key(_ sid: String) -> String { "pastes." + sid }

    static func token(_ n: Int, lines: Int) -> String { "[Pasted #\(n) · ~\(lines) lines]" }

    static func load(_ sid: String) -> [Int: String] {
        guard let raw = UserDefaults.standard.dictionary(forKey: key(sid)) as? [String: String] else { return [:] }
        return Dictionary(uniqueKeysWithValues: raw.compactMap { k, v in Int(k).map { ($0, v) } })
    }

    static func save(_ sid: String, _ pastes: [Int: String]) {
        if pastes.isEmpty {
            UserDefaults.standard.removeObject(forKey: key(sid))
        } else {
            UserDefaults.standard.set(Dictionary(uniqueKeysWithValues: pastes.map { (String($0), $1) }),
                                      forKey: key(sid))
        }
    }

    /// Every token in the text replaced by what was pasted.
    static func expand(_ text: String, _ pastes: [Int: String]) -> String {
        guard !pastes.isEmpty,
              let re = try? NSRegularExpression(pattern: #"\[Pasted #(\d+) · ~\d+ lines\]"#) else { return text }
        var out = text
        for m in re.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let whole = Range(m.range, in: out),
                  let nr = Range(m.range(at: 1), in: text), let n = Int(text[nr]),
                  let body = pastes[n] else { continue }
            out.replaceSubrange(whole, with: body)
        }
        return out
    }

    /// The numbers of the tokens still in the text.
    static func tokens(in text: String) -> [Int] {
        guard let re = try? NSRegularExpression(pattern: #"\[Pasted #(\d+) · ~\d+ lines\]"#) else { return [] }
        return re.matches(in: text, range: NSRange(text.startIndex..., in: text)).compactMap {
            Range($0.range(at: 1), in: text).flatMap { Int(text[$0]) }
        }
    }
}

// ------------------------------------------------------------------ transcript

extension Message {
    /// The same step without its finished tool rows, for `/hidetools`.
    var hidingTools: Message {
        var m = self
        m.tool_runs = nil
        m.tools = nil
        return m
    }
}

extension TranscriptRow {
    /// Rows that carry a time under them: your messages, and the last step of each answer.
    static func stamped(_ rows: [TranscriptRow]) -> Set<UUID> {
        var out = Set<UUID>()
        for (i, r) in rows.enumerated() where r.message.t != nil {
            let next = i + 1 < rows.count ? rows[i + 1].message : nil
            if r.message.isUser || next == nil || next?.isUser == true { out.insert(r.id) }
        }
        return out
    }
}

/// A message's time, short: "14:02" today, "yesterday 14:02", "Mon 14:02" this
/// week, "12 Sep 14:02" before that.
enum MessageTimeText {
    static func describe(_ t: Double, now: Date = .now) -> String {
        let d = Date(timeIntervalSince1970: t)
        let cal = Calendar.current
        let time = d.formatted(date: .omitted, time: .shortened)
        if cal.isDateInToday(d) { return time }
        if cal.isDateInYesterday(d) { return "yesterday \(time)" }
        if now.timeIntervalSince(d) < 6 * 86400 {
            return d.formatted(.dateTime.weekday(.abbreviated)) + " \(time)"
        }
        return d.formatted(.dateTime.day().month(.abbreviated)) + " \(time)"
    }

    /// "just now", "5m ago", "3h ago", "2d ago" — for the recent chats on an empty chat.
    static func relative(_ t: Double, now: Date = .now) -> String {
        let s = now.timeIntervalSince1970 - t
        if s < 90 { return "just now" }
        if s < 3600 { return "\(Int((s / 60).rounded()))m ago" }
        if s < 86400 { return "\(Int((s / 3600).rounded()))h ago" }
        return "\(Int((s / 86400).rounded()))d ago"
    }
}

/// A file offered by the `@` menu: from the workspace or the knowledge library.
struct MentionFile: Identifiable, Hashable {
    var name: String
    var rel: String
    var area: String
    var id: String { rel }
}
