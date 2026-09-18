import Foundation

/// What a new chat's home page shows, from the Mac's `/api/home`: activity over
/// the last two weeks, what is running or waiting on you, what is coming up, and
/// what is left of each allowance. Every field is optional on the wire, so an
/// older or newer Mac still decodes.
struct HomeOverview: Decodable {
    struct Day: Decodable, Identifiable {
        var day: String
        var turns: Int
        var tokens: Int
        var seconds: Double
        var toolRuns: Int
        var id: String { day }
        /// Answers, plus a little for tool calls, so a day of pure tool work still shows.
        var weight: Double { Double(turns) + Double(toolRuns) / 10 }

        enum CodingKeys: String, CodingKey { case day, turns, tokens, seconds, tool_runs }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            day = c.lenientString(.day) ?? ""
            turns = Int(c.lenientDouble(.turns) ?? 0)
            tokens = Int(c.lenientDouble(.tokens) ?? 0)
            seconds = c.lenientDouble(.seconds) ?? 0
            toolRuns = Int(c.lenientDouble(.tool_runs) ?? 0)
        }
        init(day: String = "", turns: Int = 0, tokens: Int = 0, seconds: Double = 0, toolRuns: Int = 0) {
            self.day = day; self.turns = turns; self.tokens = tokens; self.seconds = seconds; self.toolRuns = toolRuns
        }
    }

    struct ModelUse: Decodable, Identifiable {
        var model: String
        var turns: Int
        var id: String { model }
        enum CodingKeys: String, CodingKey { case model, turns }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            model = c.lenientString(.model) ?? "?"
            turns = Int(c.lenientDouble(.turns) ?? 0)
        }
    }

    struct Upcoming: Decodable, Identifiable {
        var kind: String
        var title: String
        var at: Double
        var sid: String?
        var text: String?
        var repeats: Bool
        var missed: Bool
        var id: String { "\(kind)|\(title)|\(at)" }
        enum CodingKeys: String, CodingKey { case kind, title, at, sid, text, `repeat`, missed }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            kind = c.lenientString(.kind) ?? "task"
            title = c.lenientString(.title) ?? ""
            at = c.lenientDouble(.at) ?? 0
            sid = c.lenientString(.sid)
            text = c.lenientString(.text)
            repeats = c.lenientBool(.`repeat`) ?? false
            missed = c.lenientBool(.missed) ?? false
        }
    }

    struct Failed: Decodable, Identifiable {
        var title: String
        var at: Double?
        var sid: String?
        var result: String?
        var id: String { "\(title)|\(at ?? 0)" }
        enum CodingKeys: String, CodingKey { case title, at, sid, result }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            title = c.lenientString(.title) ?? ""
            at = c.lenientDouble(.at)
            sid = c.lenientString(.sid)
            result = c.lenientString(.result)
        }
    }

    struct Problem: Decodable, Identifiable {
        var name: String
        var detail: String
        var id: String { name }
        enum CodingKeys: String, CodingKey { case name, detail }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            name = c.lenientString(.name) ?? ""
            detail = c.lenientString(.detail) ?? ""
        }
    }

    struct Allowance: Decodable, Identifiable {
        struct Window: Decodable, Identifiable {
            var name: String
            var left: Int
            var resets: Double?
            var limited: Bool
            var id: String { name }
            enum CodingKeys: String, CodingKey { case name, left, resets, limited }
            init(from d: Decoder) throws {
                let c = try d.container(keyedBy: CodingKeys.self)
                name = c.lenientString(.name) ?? ""
                left = Int(c.lenientDouble(.left) ?? 0)
                limited = c.lenientBool(.limited) ?? false
                // an ISO date from OpenCode, epoch seconds from Codex
                if let n = c.lenientDouble(.resets) { resets = n }
                else if let s = c.lenientString(.resets) { resets = HomeOverview.parseDate(s) }
                else { resets = nil }
            }
        }
        var provider: String
        var label: String
        var account: String?
        var windows: [Window]
        var exhaustedUntil: Double?
        var spentMonth: Double?
        var id: String { "\(provider)|\(account ?? "")" }
        var name: String {
            guard let a = account, !a.isEmpty, a != "Main" else { return label }
            return "\(label) · \(a)"
        }
        enum CodingKeys: String, CodingKey { case provider, label, account, windows, exhausted, spent }
        struct Exhausted: Decodable { var until: Double? }
        struct Spent: Decodable { var month: Double? }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            provider = c.lenientString(.provider) ?? ""
            label = c.lenientString(.label) ?? provider
            account = c.lenientString(.account)
            windows = (try? c.decode([Window].self, forKey: .windows)) ?? []
            exhaustedUntil = (try? c.decode(Exhausted.self, forKey: .exhausted))?.until
            spentMonth = (try? c.decode(Spent.self, forKey: .spent))?.month
        }
    }

    var now: Double
    var days: [Day]
    var today: Day
    var week: Day
    var lastWeek: Day
    var streak: Int
    var models: [ModelUse]
    var tasks: [BackgroundTask]
    var upcoming: [Upcoming]
    var failed: [Failed]
    var problems: [Problem]
    var allowances: [Allowance]

    enum CodingKeys: String, CodingKey {
        case now, days, today, week, last_week, streak, models, tasks, upcoming, failed, problems, allowances
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        now = c.lenientDouble(.now) ?? Date.now.timeIntervalSince1970
        days = (try? c.decode([Day].self, forKey: .days)) ?? []
        today = (try? c.decode(Day.self, forKey: .today)) ?? Day()
        week = (try? c.decode(Day.self, forKey: .week)) ?? Day()
        lastWeek = (try? c.decode(Day.self, forKey: .last_week)) ?? Day()
        streak = Int(c.lenientDouble(.streak) ?? 0)
        models = (try? c.decode([ModelUse].self, forKey: .models)) ?? []
        tasks = (try? c.decode([BackgroundTask].self, forKey: .tasks)) ?? []
        upcoming = (try? c.decode([Upcoming].self, forKey: .upcoming)) ?? []
        failed = (try? c.decode([Failed].self, forKey: .failed)) ?? []
        problems = (try? c.decode([Problem].self, forKey: .problems)) ?? []
        allowances = (try? c.decode([Allowance].self, forKey: .allowances)) ?? []
    }

    /// Answers this week against the week before, as a percentage; nil with no week before.
    var weekChange: Int? {
        guard lastWeek.turns > 0 else { return nil }
        return Int(((Double(week.turns - lastWeek.turns) / Double(lastWeek.turns)) * 100).rounded())
    }

    static func parseDate(_ s: String) -> Double? {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d.timeIntervalSince1970 }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)?.timeIntervalSince1970
    }
}

extension OrbitServer {
    /// The home page's figures. A Mac from before `/api/home` answers 404; the
    /// caller then shows the plain greeting.
    func home() async throws -> HomeOverview {
        let data = try await settingsCall("/api/home", timeout: 30)
        do { return try JSONDecoder().decode(HomeOverview.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }
}
