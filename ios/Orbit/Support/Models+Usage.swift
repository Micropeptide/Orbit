import Foundation

/// What is left of each account's allowance, what each model has spent, and
/// when providers are cheaper — the figures the web page's model pickers show
/// next to every provider and model. Decoding is forgiving, as everywhere: a
/// provider that reports nothing must not blank the picker.

// MARK: - Spend through Orbit (usage.windows)

/// What went through Orbit for one model or account, per window. OpenCode Go
/// publishes allowances rather than balances, so `allowance` and `leftPct` are
/// Orbit's estimate from what it sent.
struct OrbitSpend: Decodable, Hashable {
    struct Window: Decodable, Hashable {
        var spent: Double
        var tokens: Int?
        var allowance: Double?
        var leftPct: Int?

        enum CodingKeys: String, CodingKey { case spent, tokens, allowance, left_pct }

        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            spent = c.lenient(Double.self, .spent) ?? 0
            tokens = c.lenient(Double.self, .tokens).map { Int($0) }
            allowance = c.lenient(Double.self, .allowance)
            leftPct = c.lenient(Double.self, .left_pct).map { Int($0) }
        }
    }

    var requests: Int
    var windows: [String: Window]
    /// The account the allowance belongs to, by its label.
    var account: String?

    enum CodingKeys: String, CodingKey { case requests, windows, account }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        requests = c.lenient(Double.self, .requests).map { Int($0) } ?? 0
        windows = c.lenient([String: Window].self, .windows) ?? [:]
        account = c.lenient(String.self, .account)
    }

    var month: Window? { windows["month"] }

    /// "~$0.58 used this month via Orbit" — nothing until something went through Orbit.
    var shortText: String? {
        guard requests > 0, let s = month?.spent, s > 0 else { return nil }
        return String(format: "~$%.2f used this month via Orbit", s)
    }

    /// "5 hours: $0.00 of $6 (100% left) · week: … — account"
    var longText: String? {
        let rows = [("5 hours", "5h"), ("week", "week"), ("month", "month")].compactMap { name, key -> String? in
            guard let w = windows[key] else { return nil }
            var s = String(format: "\(name): $%.2f", w.spent)
            if let a = w.allowance {
                s += " of $" + (a == a.rounded() ? String(Int(a)) : String(format: "%.2f", a))
                if let l = w.leftPct { s += " (\(l)% left)" }
            }
            return s
        }
        guard !rows.isEmpty else { return nil }
        return rows.joined(separator: " · ") + (account.map { " — \($0)" } ?? "")
    }
}

// MARK: - A provider's own figures, in words

extension LiveUsage {
    /// "80% 5h · 95% wk · 70% mo left", only when the provider reported a 5-hour window.
    var shortText: String? {
        guard error == nil, rolling != nil else { return nil }
        let parts = [("5h", rolling), ("wk", weekly), ("mo", monthly)].compactMap { n, w in
            w.map { "\($0.left)% \(n)" }
        }
        return parts.joined(separator: " · ") + " left"
    }

    /// "5 hours: 80% left, resets 17 Sep 13:47 · week: …"
    var longText: String {
        if let e = error { return "usage unavailable (\(e))" }
        return [("5 hours", rolling), ("week", weekly), ("month", monthly)].compactMap { n, w -> String? in
            guard let w else { return nil }
            var s = "\(n): \(w.left)% left" + (w.limited ? " (limit reached)" : "")
            if let r = w.resets { s += ", resets " + r.formatted(.dateTime.month(.abbreviated).day().hour().minute()) }
            return s
        }.joined(separator: " · ")
    }
}

extension HarnessProvider {
    /// The account the picker reports on: the first with a key that is not used up,
    /// else the first at all (the web page's choice).
    var reportingAccount: HarnessAccount? {
        accounts.first { $0.keySet && $0.exhaustedUntil == nil } ?? accounts.first
    }

    /// Every keyed account is used up: when the soonest comes back.
    var usedUpUntil: Date? {
        let keyed = accounts.filter(\.keySet)
        guard !keyed.isEmpty, keyed.allSatisfy({ $0.exhaustedUntil != nil }) else { return nil }
        return keyed.compactMap(\.exhaustedUntil).min().map { Date(timeIntervalSince1970: $0) }
    }

    /// Why this provider cannot answer, in the picker's words. nil = it can.
    var pickerProblem: String? {
        if let d = usedUpUntil {
            return "used up until " + d.formatted(.dateTime.weekday(.abbreviated).hour().minute())
        }
        if ready { return nil }
        if isSubscription { return login == "missing" ? "Claude Code not installed" : "not signed in" }
        return "needs a key"
    }
}

// MARK: - Gateway (/api/harness → gateway.stats)

struct GatewayStats: Decodable, Hashable {
    var requests: Int
    var errors: Int
    var byProvider: [String: Int]

    enum CodingKeys: String, CodingKey { case requests, errors, by_provider }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        requests = c.lenient(Double.self, .requests).map { Int($0) } ?? 0
        errors = c.lenient(Double.self, .errors).map { Int($0) } ?? 0
        byProvider = (c.lenient([String: Double].self, .by_provider) ?? [:]).mapValues { Int($0) }
    }

    /// "15 requests, 3 failed · opencode-go 15"
    var text: String {
        var s = "\(requests) request\(requests == 1 ? "" : "s")"
        if errors > 0 { s += ", \(errors) failed" }
        let by = byProvider.sorted { $0.value > $1.value }.map { "\($0.key) \($0.value)" }
        if !by.isEmpty { s += " · " + by.joined(separator: ", ") }
        return s
    }
}

// MARK: - Codex, one provider at a time (/api/codex/models?provider=)

struct CodexProviderModels: Decodable {
    struct Model: Decodable, Hashable {
        var id: String
        var label: String
        var context: Int?
        var ready: Bool
    }
    var provider: String
    var label: String
    var ready: Bool
    var models: [Model]

    enum CodingKeys: String, CodingKey { case provider, label, ready, models }
    enum MK: String, CodingKey { case id, label, context, ready }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        provider = c.lenient(String.self, .provider) ?? ""
        label = c.lenient(String.self, .label) ?? provider
        ready = c.lenient(Bool.self, .ready) ?? false
        var out: [Model] = []
        if var arr = try? c.nestedUnkeyedContainer(forKey: .models) {
            while !arr.isAtEnd {
                guard let m = try? arr.nestedContainer(keyedBy: MK.self),
                      let id = m.lenient(String.self, .id) else { _ = try? arr.decode(JSONValue.self); continue }
                out.append(Model(id: id, label: m.lenient(String.self, .label) ?? id,
                                 context: m.lenient(Double.self, .context).map { Int($0) },
                                 ready: m.lenient(Bool.self, .ready) ?? true))
            }
        }
        models = out
    }
}

// MARK: - Cheaper hours (/api/offpeak)

struct OffpeakPolicy: Decodable, Identifiable, Hashable {
    struct Status: Decodable, Hashable {
        var active: Bool
        var what: String?
        var label: String?
        var peak: String?
        var windows: [String]
        var windowsLocal: [String]
        var spans: [[Double]]
        var startsAt: Double?
        var endsAt: Double?

        enum CodingKeys: String, CodingKey {
            case active, what, label, peak, windows, windows_local, spans, starts_at, ends_at
        }

        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            active = c.lenient(Bool.self, .active) ?? false
            what = c.lenient(String.self, .what)
            label = c.lenient(String.self, .label)
            peak = c.lenient(String.self, .peak)
            windows = c.lenient([String].self, .windows) ?? []
            windowsLocal = c.lenient([String].self, .windows_local) ?? []
            spans = c.lenient([[Double]].self, .spans) ?? []
            startsAt = c.lenient(Double.self, .starts_at)
            endsAt = c.lenient(Double.self, .ends_at)
        }

        /// By the window's own times, since the Mac's answer may be minutes old.
        var isActive: Bool {
            let now = Date().timeIntervalSince1970
            if active, let e = endsAt, now >= e { return false }
            if !active, let s = startsAt, now >= s { return true }
            return active
        }
    }

    var provider: String
    var appliesTo: String?
    var models: [String]
    var exclude: [String]
    var discount: [String: Double]
    var effective: String?
    var ends: String?
    var sources: [String]
    var quote: String?
    var note: String?
    var checkedAt: String?
    var status: Status?

    var id: String { provider + "|" + (appliesTo ?? "") }

    enum CodingKeys: String, CodingKey {
        case provider, applies_to, models, exclude, discount, effective, ends, sources, quote, note
        case checked_at, status
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        provider = c.lenient(String.self, .provider) ?? "?"
        appliesTo = c.lenient(String.self, .applies_to)
        models = c.lenient([String].self, .models) ?? []
        exclude = c.lenient([String].self, .exclude) ?? []
        discount = c.lenient([String: Double].self, .discount) ?? [:]
        effective = c.lenient(String.self, .effective)
        ends = c.lenient(String.self, .ends)
        sources = c.lenient([String].self, .sources) ?? []
        quote = c.lenient(String.self, .quote)
        note = c.lenient(String.self, .note)
        checkedAt = c.lenient(String.self, .checked_at)
        status = c.lenient(Status.self, .status)
    }

    /// "requests count 0.5× against the plan" / "output: 50% off"
    var discountText: String {
        discount.sorted { $0.key < $1.key }.map { k, v in
            k == "quota_multiplier" ? "requests count \(v.formatted())× against the plan"
                : "\(k.replacingOccurrences(of: "_", with: " ")): \(Int(((1 - v) * 100).rounded()))% off"
        }.joined(separator: " · ")
    }

    var modelsText: String {
        let m = (models.isEmpty ? ["*"] : models).map { $0 == "*" ? "all" : ($0.hasSuffix("*") ? String($0.dropLast()) + "…" : $0) }
        return m.joined(separator: ", ") + (exclude.isEmpty ? "" : " — except " + exclude.joined(separator: ", "))
    }
}

struct OffpeakList: Decodable {
    var policies: [OffpeakPolicy]
    enum CodingKeys: String, CodingKey { case policies }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        policies = c.lenient([OffpeakPolicy].self, .policies) ?? []
    }
}

// MARK: - Model ids

enum ModelID {
    /// The provider a harness model belongs to: `harness:opencode-go/x` → opencode-go.
    /// The local Claude Code model is "local"; Orbit's own models have none.
    static func provider(_ id: String) -> String? {
        if id.hasPrefix("claude-qwen-cli") { return "local" }
        for prefix in ["harness:", "codex:", "harness-direct:"] where id.hasPrefix(prefix) {
            let rest = id.dropFirst(prefix.count)
            guard let slash = rest.firstIndex(of: "/") else { return nil }
            return String(rest[..<slash])
        }
        return nil
    }

    /// The model part after the provider: `harness:opencode-go/glm-5` → glm-5.
    static func model(_ id: String) -> String? {
        guard provider(id) != nil, let slash = id.firstIndex(of: "/") else { return nil }
        return String(id[id.index(after: slash)...])
    }
}

// MARK: - What the app keeps

/// Usage figures, read when a picker or Settings opens. One copy in AppState so
/// the picker, the composer's cheaper-hours badge and Settings agree.
struct UsageState {
    var overview: HarnessOverview?
    var overviewAt: Date?
    /// Codex readiness per provider, from `/api/codex/models`.
    var codex: [String: CodexProviderModels] = [:]
    var offpeak: [OffpeakPolicy]?
    /// Providers whose model list is being refreshed.
    var refreshing: Set<String> = []

    func provider(_ pid: String) -> HarnessProvider? {
        overview?.providers.first { $0.id == pid }
    }

    func harnessModel(_ id: String) -> HarnessModel? {
        guard let pid = ModelID.provider(id), let mid = ModelID.model(id) else { return nil }
        return provider(pid)?.models.first { $0.id == mid }
    }
}
