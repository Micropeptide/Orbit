import Foundation

/// Shapes for the Mac's settings and administration endpoints — the same ones
/// the web page's Settings uses. Decoding is deliberately forgiving: the Mac
/// adds fields as it grows, and one odd value must not blank a whole screen.

// MARK: - Any JSON

/// A JSON value as the Mac sent it. `/api/settings` and the MCP config are open
/// ended, so they are kept whole and read through typed accessors.
enum JSONValue: Codable, Hashable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let n): try c.encode(n)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    var bool: Bool? { if case .bool(let b) = self { return b }; return nil }
    var double: Double? {
        switch self {
        case .number(let n): return n
        case .string(let s): return Double(s)
        default: return nil
        }
    }
    var int: Int? { double.map { Int($0) } }
    var string: String? { if case .string(let s) = self { return s }; return nil }
    var array: [JSONValue]? { if case .array(let a) = self { return a }; return nil }
    var object: [String: JSONValue]? { if case .object(let o) = self { return o }; return nil }
    var isNull: Bool { if case .null = self { return true }; return false }
    var strings: [String] { array?.compactMap(\.string) ?? [] }

    /// Plain Foundation objects, for posting back through JSONSerialization.
    var foundation: Any {
        switch self {
        case .null: return NSNull()
        case .bool(let b): return b
        case .number(let n): return n == n.rounded() && abs(n) < 1e15 ? Int(n) as Any : n
        case .string(let s): return s
        case .array(let a): return a.map(\.foundation)
        case .object(let o): return o.mapValues(\.foundation)
        }
    }
}

extension KeyedDecodingContainer {
    /// Optional that shrugs off a wrong type instead of failing the parent.
    func lenient<T: Decodable>(_ type: T.Type, _ key: Key) -> T? {
        (try? decodeIfPresent(T.self, forKey: key)) ?? nil
    }
}

// MARK: - Providers, accounts and keys (/api/harness)

struct HarnessOverview: Decodable {
    var providers: [HarnessProvider]
    var proxy: String?
    var gatewayPort: Int?
    var gatewayError: String?
    /// Requests the gateway passed on since it started, and how many failed.
    var gatewayStats: GatewayStats?

    enum CodingKeys: String, CodingKey { case providers, proxy, gateway }
    enum GW: String, CodingKey { case port, error, stats }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        providers = c.lenient([HarnessProvider].self, .providers) ?? []
        proxy = c.lenient(String.self, .proxy)
        if let g = try? c.nestedContainer(keyedBy: GW.self, forKey: .gateway) {
            gatewayPort = g.lenient(Int.self, .port)
            gatewayError = g.lenient(String.self, .error)
            gatewayStats = g.lenient(GatewayStats.self, .stats)
        }
    }

    /// Model ids the picker hides, in the form `/api/harness/save` takes.
    var hiddenIDs: [String] {
        providers.flatMap { p in p.models.filter(\.hidden).map { "harness:\(p.id)/\($0.id)" } }
    }
}

struct HarnessProvider: Decodable, Identifiable, Hashable {
    var id: String
    var label: String
    var base: String?
    var altBases: [String]
    var key: String?
    var keySet: Bool
    var auth: String            // local | subscription | gateway | api_key
    var ready: Bool
    var login: String?
    var tokenSet: Bool?
    var accounts: [HarnessAccount]
    var docs: String?
    var keysURL: String?
    var custom: Bool
    var fetchedAt: Double?
    var models: [HarnessModel]

    var isLocal: Bool { auth == "local" }
    var isSubscription: Bool { auth == "subscription" }
    var takesKeys: Bool { !isLocal && !isSubscription }

    enum CodingKeys: String, CodingKey {
        case id, label, base, alt_bases, key, key_set, auth, ready, login, token_set
        case accounts, docs, keys_url, custom, fetched_at, models
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(String.self, .label) ?? id
        base = c.lenient(String.self, .base)
        altBases = c.lenient([String].self, .alt_bases) ?? []
        key = c.lenient(String.self, .key)
        keySet = c.lenient(Bool.self, .key_set) ?? false
        auth = c.lenient(String.self, .auth) ?? "api_key"
        ready = c.lenient(Bool.self, .ready) ?? false
        login = c.lenient(String.self, .login)
        tokenSet = c.lenient(Bool.self, .token_set)
        accounts = c.lenient([HarnessAccount].self, .accounts) ?? []
        docs = c.lenient(String.self, .docs)
        keysURL = c.lenient(String.self, .keys_url)
        custom = c.lenient(Bool.self, .custom) ?? false
        fetchedAt = c.lenient(Double.self, .fetched_at)
        models = c.lenient([HarnessModel].self, .models) ?? []
    }

    /// One line for a list row.
    var statusLine: String {
        if isLocal { return "on the Mac" }
        if isSubscription {
            if ready { return "uses your Claude login" }
            return login == "missing" ? "Claude Code not installed" : "not signed in"
        }
        let n = accounts.filter(\.keySet).count
        if keySet { return n > 1 ? "\(n) accounts" : "key set" }
        return "needs a key"
    }
}

struct HarnessAccount: Decodable, Identifiable, Hashable {
    var id: String
    var label: String
    var key: String             // the key's NAME (e.g. SOME_API_KEY), never its value
    var keySet: Bool
    var active: Bool
    var exhaustedUntil: Double?
    var live: LiveUsage?
    var monthSpent: Double?
    /// Spend through Orbit per window (5 hours, week, month).
    var usage: OrbitSpend?

    enum CodingKeys: String, CodingKey { case id, label, key, key_set, active, exhausted, live, usage }
    struct Exhausted: Decodable, Hashable { var until: Double? }
    struct Usage: Decodable, Hashable {
        struct Window: Decodable, Hashable { var spent: Double? }
        var windows: [String: Window]?
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(String.self, .label) ?? id
        key = c.lenient(String.self, .key) ?? ""
        keySet = c.lenient(Bool.self, .key_set) ?? false
        active = c.lenient(Bool.self, .active) ?? false
        exhaustedUntil = c.lenient(Exhausted.self, .exhausted)?.until
        live = c.lenient(LiveUsage.self, .live)
        monthSpent = c.lenient(Usage.self, .usage)?.windows?["month"]?.spent
        usage = c.lenient(OrbitSpend.self, .usage)
    }
}

/// A provider's own figures for what is left of an account's allowance.
struct LiveUsage: Decodable, Hashable {
    struct Window: Decodable, Hashable {
        var status: String?
        var percent: Double?
        var resetsAt: String?

        var left: Int { max(0, 100 - Int(percent ?? 0)) }
        var limited: Bool { status == "rate-limited" }
        var resets: Date? {
            guard let resetsAt else { return nil }
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return f.date(from: resetsAt) ?? ISO8601DateFormatter().date(from: resetsAt)
        }
    }
    var rolling: Window?
    var weekly: Window?
    var monthly: Window?
    var error: String?

    var windows: [(name: String, window: Window)] {
        [("5 hours", rolling), ("Week", weekly), ("Month", monthly)]
            .compactMap { n, w in w.map { (n, $0) } }
    }
}

struct HarnessModel: Decodable, Identifiable, Hashable {
    var id: String
    var label: String
    var format: String?
    var context: Int?
    var hidden: Bool
    var monthSpent: Double?
    /// What this model spent through Orbit, against the account's allowance.
    var usage: OrbitSpend?

    enum CodingKeys: String, CodingKey { case id, label, format, context, hidden, usage }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = c.lenient(String.self, .label) ?? id
        format = c.lenient(String.self, .format)
        context = c.lenient(Double.self, .context).map { Int($0) }
        hidden = c.lenient(Bool.self, .hidden) ?? false
        monthSpent = c.lenient(HarnessAccount.Usage.self, .usage)?.windows?["month"]?.spent
        usage = c.lenient(OrbitSpend.self, .usage)
    }

    var formatLabel: String {
        switch format {
        case "messages": return "native"
        case "chat": return "via gateway"
        case "responses": return "via gateway (Responses)"
        default: return format ?? ""
        }
    }
}

struct HarnessTestResult: Decodable {
    var ok: Bool?
    var secs: Double?
    var reply: String?
    var error: String?
}

// MARK: - The rest of the model catalogue (/api/models)

struct ModelCatalogue: Decodable {
    var models: [ModelInfo]
    var `default`: String?
    var providers: [String: ClassicProvider]
    /// Names of keys that hold a value. The Mac sends masked values; only
    /// whether one is present is kept, so nothing of a key reaches the screen.
    var keysSet: Set<String>

    enum CodingKeys: String, CodingKey { case models, `default`, providers, keys }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        models = c.lenient([ModelInfo].self, .models) ?? []
        `default` = c.lenient(String.self, .default)
        providers = c.lenient([String: ClassicProvider].self, .providers) ?? [:]
        let keys = c.lenient([String: String].self, .keys) ?? [:]
        keysSet = Set(keys.filter { !$0.value.isEmpty }.keys)
    }
}

struct ClassicProvider: Decodable, Hashable {
    var label: String?
    var kind: String?
    var base_url: String?
    var key: String?
    var keys_url: String?
    var note: String?
}

// MARK: - Settings, tools and rules

struct PermissionRule: Decodable, Hashable {
    var tool: String?
    var pattern: String?
    var note: String?
}

struct PermissionRules: Decodable, Hashable {
    var allow: [PermissionRule] = []
    var deny: [PermissionRule] = []

    init() {}
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        allow = c.lenient([PermissionRule].self, .allow) ?? []
        deny = c.lenient([PermissionRule].self, .deny) ?? []
    }
    enum CodingKeys: String, CodingKey { case allow, deny }

    init(json: JSONValue?) {
        guard let json, let data = try? JSONEncoder().encode(json),
              let r = try? JSONDecoder().decode(PermissionRules.self, from: data) else { return }
        self = r
    }
}

/// `/api/info`: which tools exist, which are loaded, and why some failed.
struct ToolsInfo: Decodable {
    var tools: [String]
    var allTools: [String]
    var toolErrors: [String: String]
    var settings: JSONValue?

    enum CodingKeys: String, CodingKey { case tools, all_tools, tool_errors, settings }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        tools = c.lenient([String].self, .tools) ?? []
        allTools = c.lenient([String].self, .all_tools) ?? []
        toolErrors = (c.lenient([String: JSONValue].self, .tool_errors) ?? [:])
            .mapValues { $0.string ?? "\($0.foundation)" }
        settings = c.lenient(JSONValue.self, .settings)
    }
}

// MARK: - Claude Code

struct ClaudeInfo: Decodable {
    var installed: Bool
    var version: String?
    var settings: JSONValue          // Orbit's options for Claude Code (claude_qwen)
    var modes: [String]
    var mcpKnown: [String]
    var claudeDefaultMode: String?

    enum CodingKeys: String, CodingKey {
        case installed, version, settings, modes, mcp_known, claude_default_mode
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        installed = c.lenient(Bool.self, .installed) ?? false
        version = c.lenient(String.self, .version)
        settings = c.lenient(JSONValue.self, .settings) ?? .object([:])
        modes = c.lenient([String].self, .modes) ?? []
        mcpKnown = c.lenient([String].self, .mcp_known) ?? []
        claudeDefaultMode = c.lenient(String.self, .claude_default_mode)
    }
}

struct ClaudeSkill: Decodable, Identifiable, Hashable {
    var name: String
    var description: String?
    var enabled: Bool
    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, description, enabled }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        description = c.lenient(String.self, .description)
        enabled = c.lenient(Bool.self, .enabled) ?? true
    }
}

/// `/api/claude/config`: Claude's own user settings and its skills.
struct ClaudeConfig: Decodable {
    var user: JSONValue
    var skills: [ClaudeSkill]

    enum CodingKeys: String, CodingKey { case user, skills }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        user = c.lenient(JSONValue.self, .user) ?? .object([:])
        skills = c.lenient([ClaudeSkill].self, .skills) ?? []
    }
}

struct ClaudePlugin: Decodable, Identifiable, Hashable {
    var id: String
    var version: String?
    var scope: String?
    var enabled: Bool?
}

struct ClaudeMarketplace: Decodable, Identifiable, Hashable {
    var name: String
    var source: String?
    var repo: String?
    var id: String { name }
}

struct ClaudePlugins: Decodable {
    var plugins: [ClaudePlugin]
    var marketplaces: [ClaudeMarketplace]
    var error: String?

    enum CodingKeys: String, CodingKey { case plugins, marketplaces, error }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        plugins = c.lenient([ClaudePlugin].self, .plugins) ?? []
        marketplaces = c.lenient([ClaudeMarketplace].self, .marketplaces) ?? []
        error = c.lenient(String.self, .error)
    }
}

struct ClaudeMCPServer: Decodable, Identifiable, Hashable {
    var name: String
    var target: String?
    var status: String?
    var id: String { name }
}

struct ClaudeMCPList: Decodable {
    var servers: [ClaudeMCPServer]?
    var error: String?
}

/// What a Claude CLI action said back.
struct CLIOutcome: Decodable {
    var ok: Bool?
    var output: String?
    var error: String?
    var installed: [String]?
    var skipped: [String]?
}

// MARK: - Codex

struct CodexInfo: Decodable {
    struct Limit: Decodable, Hashable {
        var usedPercent: Double?
        var windowDurationMins: Double?
        var resetsAt: Double?
        var left: Int { max(0, 100 - Int(usedPercent ?? 0)) }
    }
    struct Limits: Decodable, Hashable {
        var primary: Limit?
        var secondary: Limit?
        var planType: String?
    }
    struct Host: Decodable, Hashable {
        var running: Bool?
        var idle_min: Double?
    }
    struct Model: Decodable, Hashable { var id: String; var label: String? }

    var installed: Bool
    var version: String?
    var login: String?
    var models: [Model]
    var rateLimits: Limits?
    var running: Bool
    var chatsAnswering: Int
    var hosts: [String: Host]

    enum CodingKeys: String, CodingKey {
        case installed, version, login, models, rate_limits, running, chats_answering, hosts
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        installed = c.lenient(Bool.self, .installed) ?? false
        version = c.lenient(String.self, .version)
        login = c.lenient(String.self, .login)
        models = c.lenient([Model].self, .models) ?? []
        rateLimits = c.lenient(Limits.self, .rate_limits)
        running = c.lenient(Bool.self, .running) ?? false
        chatsAnswering = c.lenient(Int.self, .chats_answering) ?? 0
        hosts = c.lenient([String: Host].self, .hosts) ?? [:]
    }

    var loginLine: String {
        switch login {
        case "chatgpt": return "Signed in with ChatGPT"
        case "api_key": return "Using an API key"
        default: return "Not signed in — run codex login on the Mac"
        }
    }
}

struct HostActionResult: Decodable {
    var ok: Bool?
    var path: String?
    var version: String?
    var why: String?
    var error: String?
}

// MARK: - Phone access

struct RemoteAccess: Decodable {
    struct Tailscale: Decodable {
        var running: Bool?
        var installed: Bool?
        var name: String?
    }
    var mode: String
    var enabled: Bool
    var url: String?
    var alts: [String]
    var tokenSet: Bool
    var tailscale: Tailscale?
    var port: Int?
    var hint: String?
    /// The Mac's address on the network it is on now.
    var lanIP: String?

    enum CodingKeys: String, CodingKey { case mode, enabled, url, alts, token_set, tailscale, port, hint, lan_ip }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        mode = c.lenient(String.self, .mode) ?? "off"
        enabled = c.lenient(Bool.self, .enabled) ?? (mode != "off")
        url = c.lenient(String.self, .url)
        alts = c.lenient([String].self, .alts) ?? []
        tokenSet = c.lenient(Bool.self, .token_set) ?? false
        tailscale = c.lenient(Tailscale.self, .tailscale)
        port = c.lenient(Int.self, .port)
        hint = c.lenient(String.self, .hint)
        lanIP = c.lenient(String.self, .lan_ip)
    }
}

// MARK: - Status and health

struct ServerDetail: Decodable {
    struct Last: Decodable { var decode_tok_s: Double?; var prefill_tok_s: Double?; var ttft_s: Double? }
    var running: Bool
    var model: String?
    var memoryGB: Double?
    var last: Last?
    var contextUsed: Int?
    var contextMax: Int?
    var flags: [String: String]

    enum CodingKeys: String, CodingKey { case running, model, memory_gb, last, context_used, context_max, flags }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        running = c.lenient(Bool.self, .running) ?? false
        model = c.lenient(String.self, .model)
        memoryGB = c.lenient(Double.self, .memory_gb)
        last = c.lenient(Last.self, .last)
        contextUsed = c.lenient(Int.self, .context_used)
        contextMax = c.lenient(Int.self, .context_max)
        flags = (c.lenient([String: JSONValue].self, .flags) ?? [:])
            .mapValues { $0.string ?? "\($0.foundation)" }
    }
}

struct HealthRow: Decodable, Identifiable, Hashable {
    var name: String
    var ok: Bool
    var detail: String?
    var fix: String?
    var info: Bool?
    var id: String { name }
}

struct AboutMac: Decodable {
    var version: String?
    /// Where Orbit lives on the Mac: its folder map starts here.
    var root: String?
    var github: String?
    var model: String?
    var tools: [String]?
    var counts: [String: Int]?
}

struct CodeStatus: Decodable {
    var stale: Bool?
    var files: [String]?
}

// MARK: - Codex settings (/api/codex/config)

struct CodexConfig: Decodable {
    struct Skill: Decodable, Identifiable, Hashable {
        var name: String
        var dir: String?
        var description: String?
        var id: String { dir ?? name }
    }
    struct Plugin: Decodable, Identifiable, Hashable {
        var pluginId: String?
        var name: String?
        var enabled: Bool?
        var version: String?
        var id: String { pluginId ?? name ?? "?" }
    }
    struct Plugins: Decodable { var installed: [Plugin]? }
    struct MCP: Decodable, Identifiable, Hashable {
        struct Transport: Decodable, Hashable {
            var type: String?
            var command: String?
            var args: [String]?
            var url: String?
        }
        var name: String
        var enabled: Bool?
        var disabled_reason: String?
        var transport: Transport?
        var id: String { name }

        var target: String {
            guard let t = transport else { return "" }
            if let c = t.command { return ([c] + (t.args ?? [])).joined(separator: " ") }
            return t.url ?? t.type ?? ""
        }
    }

    var settings: JSONValue
    var info: CodexInfo?
    var agentsMD: String
    var agentsMDPath: String?
    var skills: [Skill]
    var plugins: [Plugin]
    var pluginsError: String?
    var mcp: [MCP]
    var mcpError: String?
    var tomlModel: String?
    var tomlEffort: String?
    var modes: [String]

    enum CodingKeys: String, CodingKey {
        case settings, info, agents_md, agents_md_path, skills, plugins, plugins_error
        case mcp, mcp_error, config_toml, modes
    }
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        settings = c.lenient(JSONValue.self, .settings) ?? .object([:])
        info = c.lenient(CodexInfo.self, .info)
        agentsMD = c.lenient(String.self, .agents_md) ?? ""
        agentsMDPath = c.lenient(String.self, .agents_md_path)
        skills = c.lenient([Skill].self, .skills) ?? []
        plugins = c.lenient(Plugins.self, .plugins)?.installed ?? []
        pluginsError = c.lenient(String.self, .plugins_error)
        mcp = c.lenient([MCP].self, .mcp) ?? []
        mcpError = c.lenient(String.self, .mcp_error)
        let toml = c.lenient(JSONValue.self, .config_toml)
        tomlModel = toml?["model"]?.string
        tomlEffort = toml?["model_reasoning_effort"]?.string
        modes = c.lenient([String].self, .modes) ?? []
    }
}

/// An SSH host the Mac knows, and what it last found there. Read only.
struct SSHHostProbe: Decodable, Identifiable, Hashable {
    struct Probe: Decodable, Hashable {
        var ok: Bool?
        var codex: String?
        var codex_version: String?
        var codex_login: String?
        var error: String?
    }
    var host: String
    var probe: Probe?
    var id: String { host }

    var codexLine: String {
        guard let p = probe else { return "not checked yet" }
        if p.ok == true {
            guard p.codex != nil else { return "no Codex there yet" }
            return "Codex \(p.codex_version ?? "") · \(p.codex_login ?? "not signed in")"
        }
        return p.error != nil ? "unreachable last time" : "not checked yet"
    }
}
