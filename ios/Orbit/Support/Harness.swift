import Foundation

/// Claude Code and Codex chats: which harness answers, on which machine, in
/// which folder, and how much they may do without asking. The Mac's web UI
/// has the same controls; this is the phone's view of them.

/// Who runs a chat's turn. Orbit's own agent, or one of the two coding agents
/// the Mac drives on your behalf.
enum HarnessKind: String, CaseIterable, Identifiable {
    case orbit, claude, codex
    var id: String { rawValue }

    var label: String {
        switch self {
        case .orbit: return "Orbit"
        case .claude: return "Claude Code"
        case .codex: return "Codex"
        }
    }

    /// The harness a model id belongs to: `harness:` and the local
    /// `claude-qwen-cli` run through Claude Code, `codex:` through Codex.
    init(modelID id: String?) {
        let id = id ?? ""
        if id.hasPrefix("codex:") { self = .codex }
        else if id.hasPrefix("harness:") || id.hasPrefix("claude-qwen-cli") { self = .claude }
        else { self = .orbit }
    }

    /// Only Claude Code and Codex chats have a folder, a host and a permission mode.
    var isAgent: Bool { self != .orbit }
}

/// A Claude Code / Codex permission mode, with the Mac's labels.
enum PermissionMode: String, CaseIterable, Identifiable {
    case ask = "default", acceptEdits, plan, auto, dontAsk, bypass = "bypassPermissions"
    var id: String { rawValue }

    var label: String {
        switch self {
        case .ask: return "Ask"
        case .acceptEdits: return "Accept edits"
        case .plan: return "Plan"
        case .auto: return "Auto"
        case .dontAsk: return "Don't ask"
        case .bypass: return "Bypass"
        }
    }

    var detail: String {
        switch self {
        case .ask: return "Asks before commands and edits."
        case .acceptEdits: return "Edits files without asking; asks before commands."
        case .plan: return "Reads and plans, changes nothing."
        case .auto: return "Works on its own inside the folder; asks before going outside it."
        case .dontAsk: return "Never asks; anything not already allowed is refused."
        case .bypass: return "Runs everything — commands, edits, deletions — without asking."
        }
    }

    var symbol: String {
        switch self {
        case .ask: return "hand.raised"
        case .acceptEdits: return "pencil"
        case .plan: return "list.bullet.clipboard"
        case .auto: return "sparkles"
        case .dontAsk: return "nosign"
        case .bypass: return "exclamationmark.shield"
        }
    }

    init?(server: String?) {
        guard let s = server, let m = PermissionMode(rawValue: s) else { return nil }
        self = m
    }
}

/// A host from the Mac's ssh config.
struct RemoteHost: Codable, Identifiable, Hashable {
    var host: String
    var defaultDir: String?
    var probe: HostProbe?
    var id: String { host }

    enum CodingKeys: String, CodingKey { case host, saved, probe }
    struct Saved: Codable { var default_dir: String? }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        host = try c.decode(String.self, forKey: .host)
        defaultDir = (try? c.decode(Saved.self, forKey: .saved))?.default_dir
        probe = try? c.decode(HostProbe.self, forKey: .probe)
    }

    func encode(to e: Encoder) throws {
        var c = e.container(keyedBy: CodingKeys.self)
        try c.encode(host, forKey: .host)
        try c.encode(Saved(default_dir: defaultDir), forKey: .saved)
        try c.encodeIfPresent(probe, forKey: .probe)
    }
}

/// What connecting to a host found. `claude` and `codex` arrive as the path of
/// the program there, empty when it is not installed.
struct HostProbe: Codable, Hashable {
    var ok: Bool
    var error: String?
    var hostname: String?
    var home: String?
    var claudePath: String?
    var claudeVersion: String?
    var codexPath: String?
    var codexVersion: String?
    var codexLogin: String?
    var procs: Int?
    var procLimit: Int?
    var secs: Double?
    var at: Double?

    var hasClaude: Bool { !(claudePath ?? "").isEmpty }
    var hasCodex: Bool { !(codexPath ?? "").isEmpty }
    /// Within a fifth of the process limit: a cluster login node starts
    /// refusing new SSH sessions here.
    var nearProcessLimit: Bool {
        guard let p = procs, let l = procLimit, l > 0 else { return false }
        return Double(p) > Double(l) * 0.8
    }
    var checkedAt: Date? { at.map { Date(timeIntervalSince1970: $0) } }

    enum CodingKeys: String, CodingKey {
        case ok, error, hostname, home, claudePath = "claude", claudeVersion = "claude_version",
             codexPath = "codex", codexVersion = "codex_version", codexLogin = "codex_login",
             procs, procLimit = "proc_limit", secs, at
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        error = try? c.decode(String.self, forKey: .error)
        ok = c.lenientBool(.ok) ?? (error == nil)
        hostname = try? c.decode(String.self, forKey: .hostname)
        home = try? c.decode(String.self, forKey: .home)
        claudePath = c.lenientString(.claudePath)
        claudeVersion = c.lenientString(.claudeVersion)
        codexPath = c.lenientString(.codexPath)
        codexVersion = c.lenientString(.codexVersion)
        codexLogin = try? c.decode(String.self, forKey: .codexLogin)
        procs = (try? c.decode(Int.self, forKey: .procs)) ?? c.lenientString(.procs).flatMap { Int($0) }
        procLimit = (try? c.decode(Int.self, forKey: .procLimit)) ?? c.lenientString(.procLimit).flatMap { Int($0) }
        secs = c.lenientDouble(.secs)
        at = c.lenientDouble(.at)
    }
}

/// One folder on a host, listed for browsing.
struct RemoteListing: Codable {
    var path: String?
    var dirs: [String]?
    var files: [String]?
    var error: String?
}

/// Folders worth offering on one machine.
struct FolderPlaces: Codable {
    struct Suggested: Codable, Hashable {
        var path: String
        var why: String?
    }
    var bookmarks: [String]
    var recent: [String]
    /// This Mac only: the workspace, projects, where Claude sessions ran.
    var folders: [Suggested]

    static let empty = FolderPlaces(bookmarks: [], recent: [], folders: [])

    enum CodingKeys: String, CodingKey { case bookmarks, recent, folders }

    init(bookmarks: [String], recent: [String], folders: [Suggested]) {
        self.bookmarks = bookmarks; self.recent = recent; self.folders = folders
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        bookmarks = (try? c.decode([String].self, forKey: .bookmarks)) ?? []
        recent = (try? c.decode([String].self, forKey: .recent)) ?? []
        folders = (try? c.decode([Suggested].self, forKey: .folders)) ?? []
    }
}

/// Where a Claude Code or Codex chat works, read from `/api/claude/info`.
struct ChatWork: Equatable {
    /// A Claude Code or Codex chat at all.
    var engine: Bool
    var codex: Bool
    /// Set once the chat's first answer started a session (Claude Code) or
    /// thread (Codex) — from then on it stays on that machine.
    var session: String?
    var codexThread: String?
    var host: String?
    var cwd: String?
    var cwdPref: String?
    var cwdDefault: String?
    var mode: PermissionMode
    /// What a new chat starts with, from the Mac's Claude Code settings.
    var defaultMode: PermissionMode
    var defaultHost: String?
    var defaultDir: String?

    var started: Bool { session != nil || codexThread != nil }
    var harness: HarnessKind { codex ? .codex : .claude }
    /// The folder it works (or will work) in, if any is known.
    var folder: String? { [cwd, cwdPref, cwdDefault].compactMap { $0 }.first { !$0.isEmpty } }

    init(json o: [String: Any]) {
        func s(_ k: String) -> String? {
            guard let v = o[k] as? String, !v.isEmpty else { return nil }
            return v
        }
        engine = (o["engine"] as? Bool) ?? false
        codex = (o["codex"] as? Bool) ?? false
        session = s("session")
        codexThread = s("codex_thread")
        host = s("host")
        cwd = s("cwd")
        cwdPref = s("cwd_pref")
        cwdDefault = s("cwd_default")
        let settings = o["settings"] as? [String: Any] ?? [:]
        // with no chat named, `prefs` is every chat's; only a flat one is this chat's
        let prefs = o["prefs"] as? [String: Any] ?? [:]
        let fallback = PermissionMode(server: settings["permission_mode"] as? String)
            ?? PermissionMode(server: o["claude_default_mode"] as? String) ?? .ask
        defaultMode = fallback
        mode = PermissionMode(server: prefs["permission_mode"] as? String) ?? fallback
        defaultHost = (settings["default_host"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        defaultDir = (settings["default_dir"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    }
}

/// Paths read better with the home folder folded away and the middle elided:
/// "host: …/project/analysis".
enum PathText {
    static func short(_ path: String?, keep: Int = 2) -> String {
        guard var p = path, !p.isEmpty else { return "" }
        if let r = p.range(of: #"^/(Users|home)/[^/]+"#, options: .regularExpression) {
            p.replaceSubrange(r, with: "~")
        }
        let parts = p.split(separator: "/", omittingEmptySubsequences: true)
        guard parts.count > keep + 1 else { return p }
        return "…/" + parts.suffix(keep).joined(separator: "/")
    }

    static func place(host: String?, folder: String?, keep: Int = 2) -> String {
        let f = short(folder, keep: keep)
        if let h = host, !h.isEmpty { return "\(h): " + (f.isEmpty ? "~" : f) }
        return f.isEmpty ? "This Mac · workspace" : f
    }
}

// ------------------------------------------------------------------ app state

extension AppState {
    /// The last model used in a harness, or its first ready model.
    func suggestedModel(for kind: HarnessKind) -> String? {
        if kind == harnessMode, let d = catalogueID(for: defaultModel), HarnessKind(modelID: d) == kind { return d }
        let recent = (kind == .claude ? harnessRecent : kind == .codex ? codexRecent : [])
            .map(\.id).first { id in models.contains { $0.id == id && $0.isReady } }
        if let recent { return recent }
        let ready = models.filter { $0.isReady && HarnessKind(modelID: $0.id) == kind }
        if kind == .orbit, let local = ready.first(where: { $0.provider == "local" }) { return local.id }
        return ready.first?.id
    }

    func loadHosts() async {
        guard let server else { return }
        guard let hs = try? await server.remoteHosts() else { return }
        remoteHosts = hs
        // a check the Mac already has counts: no need to connect again
        for h in hs { if let p = h.probe, hostProbes[h.host] == nil { hostProbes[h.host] = p } }
    }

    /// Connect to a host once. `refresh` asks the Mac not to answer from its
    /// own recent check — only for an explicit "check again".
    @discardableResult
    func probe(host: String, refresh: Bool = false) async -> HostProbe? {
        guard let server, !probing.contains(host) else { return hostProbes[host] }
        probing.insert(host)
        defer { probing.remove(host) }
        do {
            let p = try await server.probe(host: host, refresh: refresh)
            hostProbes[host] = p
            probeErrors[host] = nil
            return p
        } catch {
            probeErrors[host] = error.localizedDescription
            return nil
        }
    }

    func setHarnessMode(_ kind: HarnessKind) async {
        guard let server else { return }
        harnessBusy = true
        defer { harnessBusy = false }
        do {
            _ = try await server.setHarnessMode(kind)
            harnessMode = kind
            await loadModels()
        } catch { lastError = error.localizedDescription }
    }

    /// Give a new chat its model, machine, folder and permission mode before
    /// anything is sent. Stops at the first thing the Mac refuses.
    func configureChat(_ sid: String, model: String?, harness: HarnessKind, host: String,
                       folder: String, mode: PermissionMode?) async throws {
        guard let server else { throw OrbitServer.Failure.notPaired }
        if let model, !model.isEmpty {
            try await server.selectModel(model, for: sid)
            currentModel = model
        }
        guard harness.isAgent else { return }
        let cwd = folder.trimmingCharacters(in: .whitespacesAndNewlines)
        if !host.isEmpty || !cwd.isEmpty {
            try await server.setWork(sid: sid, host: host, cwd: cwd)
        }
        if let mode { try await server.setPermissionMode(sid: sid, mode: mode) }
    }
}
