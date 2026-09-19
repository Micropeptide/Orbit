import Foundation

/// Everything that talks to the Mac.
///
/// One rule throughout: the Mac is the source of truth. This app never invents
/// state and never writes a conversation locally that the Mac has not accepted —
/// the cache is a copy for reading offline, not a second database to reconcile.
actor OrbitServer {
    private var pairing: Pairing
    private let session: URLSession

    init(pairing: Pairing) {
        self.pairing = pairing
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 30
        cfg.timeoutIntervalForResource = 3600      // a long answer is not a stall
        cfg.waitsForConnectivity = true
        cfg.httpAdditionalHeaders = ["Accept": "application/json"]
        self.session = URLSession(configuration: cfg)
    }

    func update(pairing: Pairing) { self.pairing = pairing }

    // ------------------------------------------------------------ plumbing

    enum Failure: LocalizedError {
        case notPaired
        case unauthorised
        case offline(String)
        case server(Int, String)
        case decoding(String)

        var errorDescription: String? {
            switch self {
            case .notPaired:      return "Not paired with a Mac yet."
            case .unauthorised:   return "This Mac no longer accepts the pairing — scan the QR again."
            case .offline(let s): return "Can't reach your Mac. \(s)"
            case .server(let c, let m): return "Your Mac answered \(c): \(m)"
            case .decoding(let s): return "Unexpected answer from your Mac: \(s)"
            }
        }
    }

    func request(_ path: String, method: String = "GET",
                         body: [String: Any]? = nil) throws -> URLRequest {
        guard let base = pairing.base,
              let url = URL(string: path, relativeTo: base) else { throw Failure.notPaired }
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.setValue("Bearer \(pairing.token)", forHTTPHeaderField: "Authorization")
        // Host is set by URLSession from the URL; the Mac checks it against the
        // addresses it knows it is reachable as, so leave it alone.
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return r
    }

    func run(_ req: URLRequest) async throws -> Data {
        do {
            let (data, resp) = try await session.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if code == 401 { throw Failure.unauthorised }
            guard (200..<300).contains(code) else {
                // the Mac explains a refusal as {"error": "..."}; show just that
                if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let e = obj["error"] as? String, !e.isEmpty {
                    throw Failure.server(code, String(e.prefix(200)))
                }
                let msg = String(data: data, encoding: .utf8)?
                    .prefix(200).trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                throw Failure.server(code, msg)
            }
            return data
        } catch let e as Failure {
            throw e
        } catch {
            throw Failure.offline((error as NSError).localizedDescription)
        }
    }

    func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        let data = try await run(try request(path))
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    @discardableResult
    func post(_ path: String, _ body: [String: Any] = [:]) async throws -> Data {
        try await run(try request(path, method: "POST", body: body))
    }

    // ------------------------------------------------------------ reading

    func health() async throws -> Bool {
        var req = try request("/api/running")
        req.timeoutInterval = 6          // a wrong address must fail fast, not in 30 s
        _ = try await run(req)
        return true
    }

    /// The addresses the Mac currently answers on, so a paired phone keeps
    /// learning them without rescanning.
    func alternates() async throws -> (url: String?, alts: [String], name: String?) {
        struct R: Codable { var url: String?; var alts: [String]?; var mac_name: String? }
        let r = try await get("/api/remote", as: R.self)
        return (r.url, r.alts ?? [], r.mac_name)
    }

    func chats(limit: Int = 100) async throws -> [ChatSummary] {
        try await get("/api/sessions?limit=\(limit)", as: ChatList.self).items
    }

    func chat(_ id: String) async throws -> ChatDetail {
        try await get("/api/session/\(id)", as: ChatDetail.self)
    }

    /// Read a chat without making it the Mac's open one — for caching in the
    /// background, which must not move what the desktop is looking at.
    func peek(_ id: String) async throws -> ChatDetail {
        try await get("/api/peek/\(id)", as: ChatDetail.self)
    }

    /// Has this chat changed on the Mac? Cheap enough to ask every few seconds.
    func stamp(_ id: String) async throws -> (n: Int, running: Bool) {
        struct S: Codable { var n: Int; var running: Bool }
        let s = try await get("/api/stamp/\(id)", as: S.self)
        return (s.n, s.running)
    }

    func trash() async throws -> [TrashItem] {
        try await get("/api/trash", as: [TrashItem].self)
    }

    func restore(name: String) async throws -> Bool {
        struct R: Codable { var ok: Bool? }
        return (try? JSONDecoder().decode(R.self, from: try await post("/api/trash/restore", ["name": name])))?.ok ?? false
    }

    func models() async throws -> ModelList {
        try await get("/api/models", as: ModelList.self)
    }

    func projects() async throws -> [ProjectInfo] {
        struct P: Codable { var name: String; var color: String?; var instructions: String? }
        let data = try await run(try request("/api/projects"))
        let dict = (try? JSONDecoder().decode([String: P].self, from: data)) ?? [:]
        return dict.map { ProjectInfo(id: $0.key, name: $0.value.name, color: $0.value.color,
                                      instructions: $0.value.instructions) }
                   .sorted { $0.name < $1.name }
    }

    func setDefaultModel(_ id: String) async throws {
        try await post("/api/model/default", ["id": id])
    }

    // ------------------------------------------------------------ autonomy

    struct AutonomySettings: Codable {
        var autonomy_mode: String?
        var shell_enabled: Bool?
        var write_any: Bool?
        var cluster_write: Bool?
        var computer_use_enabled: Bool?
    }

    /// `/api/settings` merges whatever you post and hands back everything —
    /// posting nothing is how you read it.
    func autonomy() async throws -> AutonomySettings {
        struct R: Codable { var settings: AutonomySettings }
        let data = try await post("/api/settings", ["settings": [String: Any]()])
        return try JSONDecoder().decode(R.self, from: data).settings
    }

    @discardableResult
    func setAutonomy(_ changes: [String: Any]) async throws -> AutonomySettings {
        struct R: Codable { var settings: AutonomySettings }
        let data = try await post("/api/settings", ["settings": changes])
        return try JSONDecoder().decode(R.self, from: data).settings
    }

    func running() async throws -> [String] {
        struct R: Codable { var running: [String] }
        return try await get("/api/running", as: R.self).running
    }

    /// Live buffer for a chat that is generating — used to rejoin an answer that
    /// started on the Mac or before the app was reopened.
    /// `step` counts the steps the answer has moved past: the buffer holds only
    /// the one being written (nil from a Mac that predates this).
    func live(_ sid: String) async throws -> (running: Bool, content: String, thinking: String, step: Int?) {
        struct L: Codable {
            var known: Bool?; var running: Bool?; var content: String?
            var thinking: String?; var status: String?; var step: Int?
        }
        let l = try await get("/api/live/\(sid)", as: L.self)
        return (l.running ?? false, l.content ?? "", l.thinking ?? "", l.step)
    }

    /// Any authenticated GET returning bytes — images, thumbnails, downloads.
    func fetchRaw(_ path: String) async throws -> Data {
        try await run(try request(path))
    }

    /// Search inside every conversation, not just their titles.
    func search(_ q: String) async throws -> [SearchHit] {
        let escaped = OrbitServer.escaped(q)
        return try await get("/api/searchchats?q=\(escaped)", as: [SearchHit].self)
    }

    func files(limit: Int = 300) async throws -> [RemoteFile] {
        struct F: Codable { var items: [RemoteFile] }
        return try await get("/api/files?limit=\(limit)", as: F.self).items
    }

    func deleteFile(rel: String) async throws {
        try await post("/api/files/delete", ["rel": rel])
    }

    /// Pull a file down to a temporary location so QuickLook can show it.
    /// Named properly, because QuickLook decides the viewer from the extension.
    func download(rel: String, name: String) async throws -> URL {
        let escaped = rel.addingPercentEncoding(
            withAllowedCharacters: .urlPathAllowed) ?? rel
        let data = try await run(try request("/api/ws/\(escaped)"))
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-preview", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent(name)
        try data.write(to: url, options: .atomic)
        return url
    }

    /// Upload one attachment. The Mac answers with the descriptor the chat
    /// endpoint expects, so the caller just passes it straight through.
    func upload(data: Data, filename: String, mime: String) async throws -> [String: Any] {
        guard let base = pairing.base,
              let url = URL(string: "/api/upload", relativeTo: base) else { throw Failure.notPaired }
        let boundary = "orbit.\(UUID().uuidString)"
        var body = Data()
        func add(_ s: String) { body.append(s.data(using: .utf8)!) }
        add("--\(boundary)\r\n")
        add("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        add("Content-Type: \(mime)\r\n\r\n")
        body.append(data)
        add("\r\n--\(boundary)--\r\n")

        var r = URLRequest(url: url)
        r.httpMethod = "POST"
        r.setValue("Bearer \(pairing.token)", forHTTPHeaderField: "Authorization")
        r.setValue("multipart/form-data; boundary=\(boundary)",
                   forHTTPHeaderField: "Content-Type")
        r.httpBody = body
        r.timeoutInterval = 120
        let out = try await run(r)
        guard let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any]
        else { throw Failure.decoding("upload") }
        if let e = obj["error"] as? String { throw Failure.server(400, e) }
        return obj
    }

    // ------------------------------------------------------------ local model

    struct ServerStatus: Codable {
        var running: Bool
        var model: String?
        var memory_gb: Double?
    }

    func serverStatus() async throws -> ServerStatus {
        try await get("/api/status", as: ServerStatus.self)
    }

    enum ServerAction: String { case start, stop, restart }

    /// Start, stop or restart the model server on the Mac. A start can take
    /// ~15 s while the weights load, so the timeout is generous.
    func serverAction(_ a: ServerAction) async throws -> String {
        struct R: Codable { var msg: String? }
        var req = try request("/api/server/\(a.rawValue)", method: "POST", body: [:])
        req.timeoutInterval = 300
        let data = try await run(req)
        return (try? JSONDecoder().decode(R.self, from: data))?.msg ?? "done"
    }

    /// Point the Mac at a different model folder and restart it.
    func switchLocalModel(_ folder: String) async throws -> String {
        struct R: Codable { var ok: Bool?; var serving: String?; var error: String? }
        var req = try request("/api/model/local_switch", method: "POST", body: ["name": folder])
        req.timeoutInterval = 300
        let data = try await run(req)
        let r = try JSONDecoder().decode(R.self, from: data)
        if let e = r.error { throw Failure.server(400, e) }
        return "now serving \(r.serving ?? folder)"
    }

    // ------------------------------------------------------------ backup

    func backupStatus() async throws -> BackupStatus {
        try await get("/api/backup/status", as: BackupStatus.self)
    }

    /// Write an archive now. Returns its file name.
    func backupNow() async throws -> String {
        struct R: Codable { var name: String?; var error: String? }
        var req = try request("/api/backup/now", method: "POST", body: [:])
        req.timeoutInterval = 120
        let r = try JSONDecoder().decode(R.self, from: try await run(req))
        if let e = r.error { throw Failure.server(400, e) }
        return r.name ?? "done"
    }

    func setBackup(_ changes: [String: Any]) async throws -> BackupStatus {
        try JSONDecoder().decode(BackupStatus.self, from: try await post("/api/backup/settings", changes))
    }

    /// Put back whatever the archive has that the Mac no longer does. Adds only.
    func restoreMissing(from name: String) async throws -> Int {
        struct R: Codable { var n: Int?; var error: String? }
        let r = try JSONDecoder().decode(R.self, from: try await post("/api/backup/restore_missing", ["name": name]))
        if let e = r.error { throw Failure.server(400, e) }
        return r.n ?? 0
    }

    // ------------------------------------------------------------ writing

    func newChat() async throws -> String {
        struct N: Codable { var sid: String }
        let data = try await post("/api/new")
        return try JSONDecoder().decode(N.self, from: data).sid
    }

    func rename(_ id: String, to title: String) async throws {
        try await post("/api/session/rename", ["id": id, "title": title])
    }

    func delete(_ id: String) async throws {
        try await post("/api/delete", ["id": id])
    }

    func setFlag(_ id: String, pinned: Bool? = nil, archived: Bool? = nil) async throws {
        var body: [String: Any] = ["id": id]
        if let pinned { body["pinned"] = pinned }
        if let archived { body["archived"] = archived }
        try await post("/api/session/flag", body)
    }

    func selectModel(_ modelID: String, for sid: String) async throws {
        try await post("/api/model/select", ["id": modelID, "sid": sid])
    }

    func stop(_ sid: String) async throws {
        try await post("/api/cancel", ["sid": sid])
    }

    /// A note for an answer that is still running: the Mac hands it to the
    /// model at its next step. False when that answer has already finished.
    func interject(sid: String, message: String) async throws -> Bool {
        struct R: Codable { var ok: Bool? }
        let data = try await post("/api/interject", ["sid": sid, "message": message])
        return (try? JSONDecoder().decode(R.self, from: data).ok) ?? false
    }

    /// Cut the conversation back to before the given user message (ordinal
    /// among user messages, which is how the Mac counts).
    func truncate(_ sid: String, atUserIndex index: Int, check: String? = nil) async throws {
        var body: [String: Any] = ["id": sid, "index": index]
        // the Mac refuses if the message at that index does not start like this
        if let check, !check.isEmpty { body["check"] = String(check.prefix(80)) }
        try await post("/api/truncate", body)
    }

    func addToKnowledge(rel: String) async throws {
        try await post("/api/knowledge/from_upload", ["rel": rel])
    }

    func compact(_ sid: String) async throws {
        try await post("/api/compact", ["sid": sid])
    }

    // ------------------------------------------------------------ streaming

    /// Send a message and stream the answer.
    ///
    /// The server speaks server-sent events; `URLSession.bytes` gives us the body
    /// as it arrives, so this is a plain line reader rather than a dependency.
    func send(sid: String, message: String,
              attachments: [[String: String]] = [],
              effort: String? = nil) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var body: [String: Any] = ["sid": sid, "message": message]
                    if !attachments.isEmpty { body["attachments"] = attachments }
                    if let effort { body["effort"] = effort }       // "xhigh" for retry deeper
                    var req = try request("/api/chat", method: "POST", body: body)
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    req.timeoutInterval = 3600

                    let (bytes, resp) = try await session.bytes(for: req)
                    let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                    if code == 401 { throw Failure.unauthorised }
                    guard (200..<300).contains(code) else {
                        throw Failure.server(code, "the chat endpoint refused")
                    }
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        guard line.hasPrefix("data: ") else { continue }
                        let payload = String(line.dropFirst(6))
                        if let ev = Self.parse(payload) {
                            continuation.yield(ev)
                            if case .end = ev { break }
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// One SSE payload to an event. Unknown kinds are ignored rather than
    /// surfaced as noise — the server adds new ones as it grows.
    nonisolated static func parse(_ json: String) -> StreamEvent? {
        guard let data = json.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let kind = obj["k"] as? String else { return nil }
        let p = obj["p"]
        // Claude Code's hooks report on every step: they fold into one line per answer
        if kind == "notice", let msg = (p as? [String: Any])?["msg"] as? String ?? p as? String,
           msg.range(of: #"^hook\s"#, options: [.regularExpression, .caseInsensitive]) != nil {
            return .extra(.hook(msg))
        }

        func str(_ key: String) -> String {
            ((p as? [String: Any])?[key] as? String) ?? ""
        }

        switch kind {
        case "content_delta":  return .content(p as? String ?? "")
        case "thinking_delta": return .thinking(p as? String ?? "")
        case "model":          return .model(str("label").isEmpty ? str("id") : str("label"))
        // a call and its result pair up by id, so each row can say what came back
        case "tool":
            return .tool(ToolRun(event: (p as? [String: Any]) ?? [:], finished: false))
        case "tool_result":
            let d = (p as? [String: Any]) ?? [:]
            return .toolResult(ToolRun(event: d, finished: true), diff: ShownDiff(d["diff"]))
        case "server_starting":
            let msg = str("msg")
            return .status(msg.isEmpty ? "starting the model" : msg)
        case "server_ready":   return .status("")
        case "squeezed", "autocompact_done", "stagnation", "round_limit", "interjection", "retry",
             "sources", "weak_claims", "injection", "skill_hint", "long_running",
             "plan_nudge", "fail_streak", "ultrathink":
            return TranscriptEvent.parse(kind: kind, p).map { .extra($0) }
        case "autocompact":    return .status("summarising earlier turns")
        case "blocked":        return .blocked(reason: str("reason"))
        case "auto_approved":  return .autoApproved(name: str("name"), reason: str("reason"))
        // "approval_request" carries the id /api/approve answers to; the bare
        // "approval" event before it never did, so a prompt on the phone could
        // not actually be answered
        case "approval_request":
            if let full = ApprovalPrompt(p as? [String: Any]) { return .approvalPrompt(full) }
            return .approval(name: str("name"), reason: str("reason"),
                             id: (p as? [String: Any])?["id"] as? String)
        case "approval":       return nil
        // Claude Code and Codex say what they are doing before the first token —
        // "starting Codex on <host>" can take a while over SSH
        case "status":         return .status(p as? String ?? str("msg"))
        case "notice":
            let msg = p as? String ?? str("msg")
            // a plan's allowance ran out: its own event, so it can stand out and notify
            if str("kind") == "limit" { return .usageLimit(msg) }
            return msg.isEmpty ? nil : .notice(msg)
        // chat actions: a question mid-answer, and an answer that hit its limit
        case "question":
            return AskQuestion(p as? [String: Any]).map { .question($0) }
        case "queued":         return .status("waiting for another chat to finish")
        case "dequeued":       return .status("its turn — starting")
        // the chat was already answering: the Mac queued this message, and starts it
        // by itself once the answer running now is done
        case "queued_message":
            let d = p as? [String: Any]
            if str("why") == "scheduled" {
                let item = d?["item"] as? [String: Any]
                let at = (item?["at"] as? Double) ?? (item?["at"] as? String).flatMap(Double.init)
                let when = at.map { When.describe(Date(timeIntervalSince1970: $0)) } ?? "later"
                let rep = Repeat(server: item?["repeat"] as? String)
                return .content("Scheduled for \(when)" + (rep == .once ? "." : " · \(rep.label.lowercased())."))
            }
            return .content("Queued — it starts by itself when the answer running now is done.")
        // the chosen model failed and another took over
        case "fallback":
            let d = p as? [String: Any]
            let to = [str("to_label"), str("to")].first { !$0.isEmpty } ?? "another model"
            let after = (d?["after"] as? Int) ?? (d?["after"] as? String).flatMap(Int.init)
            var line = "switched to \(to)"
            if let after { line += " after \(after) failure\(after == 1 ? "" : "s")" }
            let why = str("why")
            if !why.isEmpty { line += " (\(why.prefix(80)))" }
            return .notice(line)
        case "interjected":    return .content("Sent in — it reads this at its next step.")
        case "subtask":
            let d = str("description")
            return .status(d.isEmpty ? "a helper is working" : "helper: \(d)")
        case "subagent":
            let d = (p as? [String: Any]) ?? [:]
            let args = ToolText.stringify((d["args"] as? [String: Any]) ?? [:])
            let num = { (k: String) -> Int in (d[k] as? Int) ?? (d[k] as? Double).map { Int($0) } ?? 0 }
            return .subagentStep(parent: str("parent"), step: .init(name: str("name"), args: args),
                                 tools: num("tools"), tokens: num("tokens"), description: str("description"))
        case "subagent_done":
            let d = (p as? [String: Any]) ?? [:]
            guard let info = SubagentInfo(any: d["subagent"]) else { return nil }
            return .subagentDone(parent: str("parent"), info: info)
        case "error", "stream_error":
            return .error(p as? String ?? str("error"))
        case "end":
            return .end(sid: str("sid").isEmpty ? nil : str("sid"),
                        title: str("title").isEmpty ? nil : str("title"))
        default: return nil
        }
    }

    /// Answer an approval prompt raised mid-answer.
    func approve(_ id: String, allow: Bool) async throws {
        try await post("/api/approve", ["id": id, "allow": allow])
    }

    // ------------------------------------------------------------ queue and send later

    /// One chat's waiting messages. Every op answers with the queue as it now is.
    @discardableResult
    func queue(sid: String, op: String, _ extra: [String: Any] = [:]) async throws -> QueueState {
        struct R: Codable { var ok: Bool?; var queue: QueueState?; var error: String? }
        var body = extra
        body["sid"] = sid
        body["op"] = op
        let data = try await post("/api/queue", body)
        let r = try? JSONDecoder().decode(R.self, from: data)
        if let e = r?.error { throw Failure.server(400, e) }
        return r?.queue ?? .empty
    }

    /// Put a message in a chat's queue to go out at `at`, optionally repeating.
    @discardableResult
    func sendLater(sid: String, text: String, attachments: [[String: String]] = [],
                   at: Date, repeat rep: Repeat) async throws -> QueueState {
        try await queue(sid: sid, op: "add", ["text": text, "attachments": attachments,
                                              "at": at.timeIntervalSince1970, "repeat": rep.server])
    }

    /// Change a waiting message. `update` does it in one go on a Mac that has
    /// it; an older Mac gets `schedule` and `edit`, which cannot change the model.
    func updateQueued(sid: String, id: String, text: String?, at: Date??,
                      repeat rep: Repeat?, model: String?) async throws {
        var body: [String: Any] = ["id": id]
        if let text { body["text"] = text }
        if let at { body["at"] = at.map { $0.timeIntervalSince1970 } ?? NSNull() }
        if let rep { body["repeat"] = rep.server }
        if let model { body["model"] = model }
        do {
            try await queue(sid: sid, op: "update", body)
            return
        } catch Failure.server(let code, let msg) where code == 400 && msg.contains("unknown op") {
            // fall through to the older pair
        }
        if let text { try await queue(sid: sid, op: "edit", ["id": id, "text": text]) }
        if at != nil || rep != nil {
            var b: [String: Any] = ["id": id]
            if let at { b["at"] = at.map { $0.timeIntervalSince1970 } ?? NSNull() }
            if let rep { b["repeat"] = rep.server }
            try await queue(sid: sid, op: "schedule", b)
        }
    }

    // ------------------------------------------------------------ scheduled

    /// Everything that happens later: messages waiting for their time in any
    /// chat, and the Mac's scheduled tasks. Falls back to the two older
    /// endpoints on a Mac that predates `/api/scheduled`.
    func scheduled() async throws -> (messages: [ScheduledMessage], tasks: [ScheduledTask]) {
        struct Both: Codable { var messages: [ScheduledMessage]?; var tasks: [ScheduledTask]? }
        if let data = try? await post("/api/scheduled", [:]),
           let r = try? JSONDecoder().decode(Both.self, from: data),
           let m = r.messages, let t = r.tasks {
            return (m, t)
        }
        struct Sends: Codable { var items: [ScheduledMessage]? }
        struct Jobs: Codable { var jobs: [ScheduledTask]? }
        let sendsData = try await post("/api/scheduled_sends", [:])
        let sends = (try? JSONDecoder().decode(Sends.self, from: sendsData))?.items ?? []
        let jobs = (try? await get("/api/schedule", as: Jobs.self))?.jobs ?? []
        return (sends, jobs)
    }

    /// Create or change a task. A partial `job` is merged into the saved one.
    func saveTask(_ job: [String: Any]) async throws {
        struct R: Codable { var error: String? }
        let data = try await post("/api/schedule/save", ["job": job])
        if let e = (try? JSONDecoder().decode(R.self, from: data))?.error { throw Failure.server(400, e) }
    }

    func runTask(_ id: String) async throws {
        try await post("/api/schedule/run", ["id": id])
    }

    func deleteTask(_ id: String) async throws {
        try await post("/api/schedule/delete", ["id": id])
    }

    // ------------------------------------------------------------ harness and hosts

    /// Which harness new chats use: Orbit's own agent, Claude Code or Codex.
    func setHarnessMode(_ kind: HarnessKind) async throws -> String? {
        struct R: Codable { var ok: Bool?; var `default`: String?; var error: String? }
        let r = try? JSONDecoder().decode(R.self, from: try await post("/api/harness/mode", ["engine": kind.rawValue]))
        if let e = r?.error { throw Failure.server(400, e) }
        return r?.default
    }

    /// The SSH hosts in the Mac's ssh config, with the last check of each if
    /// the Mac has one. Reading this does not connect to any of them.
    func remoteHosts() async throws -> [RemoteHost] {
        struct R: Codable { var hosts: [RemoteHost] }
        return try await get("/api/remote/hosts", as: R.self).hosts
    }

    /// Connect to a host and see what it offers. Slow (up to a minute), and a
    /// cluster may block an address that connects too often — call it only when
    /// someone asks.
    func probe(host: String, refresh: Bool = false) async throws -> HostProbe {
        var body: [String: Any] = ["host": host]
        if refresh { body["refresh"] = true }
        var req = try request("/api/remote/probe", method: "POST", body: body)
        req.timeoutInterval = 120
        let data = try await run(req)
        do { return try JSONDecoder().decode(HostProbe.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    /// Folders inside one folder on a host.
    func listRemote(host: String, path: String) async throws -> RemoteListing {
        var req = try request("/api/remote/ls", method: "POST", body: ["host": host, "path": path])
        req.timeoutInterval = 90
        let r = try JSONDecoder().decode(RemoteListing.self, from: try await run(req))
        if let e = r.error { throw Failure.server(400, e) }
        return r
    }

    /// Bookmarked and recently used folders on a machine ("" = this Mac).
    func folderPlaces(host: String) async throws -> FolderPlaces {
        let h = OrbitServer.escaped(host)
        return try await get("/api/claude/folders?host=\(h)", as: FolderPlaces.self)
    }

    /// Star or unstar a folder. Answers with the machine's bookmarks as they now are.
    func bookmark(host: String, path: String, on: Bool) async throws -> [String] {
        struct R: Codable { var bookmarks: [String]?; var error: String? }
        let r = try JSONDecoder().decode(R.self, from: try await post("/api/folders/bookmark",
                                                                      ["host": host, "path": path, "on": on]))
        if let e = r.error { throw Failure.server(400, e) }
        return r.bookmarks ?? []
    }

    /// Where a Claude Code or Codex chat works, and how much it may do unasked.
    func chatWork(sid: String) async throws -> ChatWork {
        let s = OrbitServer.escaped(sid)
        let data = try await run(try request("/api/claude/info?sid=\(s)"))
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw Failure.decoding("claude/info") }
        return ChatWork(json: obj)
    }

    /// Set the machine ("" = this Mac) and folder a chat works in. The Mac
    /// checks that a folder on itself exists.
    func setWork(sid: String, host: String, cwd: String, addDirs: [String]? = nil) async throws {
        var body: [String: Any] = ["sid": sid, "host": host, "cwd": cwd]
        if let addDirs { body["add_dirs"] = addDirs }
        struct R: Codable { var error: String? }
        let data = try await post("/api/claude/cwd", body)
        if let e = (try? JSONDecoder().decode(R.self, from: data))?.error { throw Failure.server(400, e) }
    }

    func setPermissionMode(sid: String, mode: PermissionMode) async throws {
        struct R: Codable { var error: String? }
        let data = try await post("/api/claude/mode", ["sid": sid, "mode": mode.rawValue])
        if let e = (try? JSONDecoder().decode(R.self, from: data))?.error { throw Failure.server(400, e) }
    }

    // ------------------------------------------------------------ file links

    /// Which of these names in an answer are real files where the chat works.
    func resolvePaths(sid: String, _ names: [String]) async throws -> [String: ResolvedPath] {
        struct R: Codable { var items: [String: ResolvedPath]? }
        let data = try await post("/api/paths/resolve", ["sid": sid, "paths": names])
        return (try? JSONDecoder().decode(R.self, from: data))?.items ?? [:]
    }

    /// `preview` gives a page-ready link to a file; `render` turns a document,
    /// spreadsheet or archive into an image or page first.
    func fileAction(sid: String, path: String, action: String) async throws -> (url: String, kind: String?) {
        struct R: Codable { var ok: Bool?; var url: String?; var kind: String?; var error: String? }
        var req = try request("/api/file/action", method: "POST",
                              body: ["sid": sid, "path": path, "action": action])
        req.timeoutInterval = 120          // rendering a document, or fetching over ssh, takes a while
        let data = try await run(req)
        let r = try JSONDecoder().decode(R.self, from: data)
        guard r.ok == true, let url = r.url else {
            throw Failure.server(400, r.error ?? "the Mac could not show this file")
        }
        return (url, r.kind)
    }

    // ------------------------------------------------------------ for extensions

    /// An authorised request, for endpoints defined in `OrbitServer+*.swift` files.
    func authorisedRequest(_ path: String, method: String = "GET",
                           body: [String: Any]? = nil) throws -> URLRequest {
        try request(path, method: method, body: body)
    }

    /// Run a request built by `authorisedRequest`, with the usual error mapping.
    func perform(_ req: URLRequest) async throws -> Data {
        try await run(req)
    }

    /// A link the Mac handed out, made absolute. `/fs/` links carry their own permission.
    func absolute(_ path: String) -> URL? {
        guard let base = pairing.base else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    /// Bytes behind a preview link, saved under the file's own name for sharing.
    func downloadPreview(_ path: String, name: String) async throws -> URL {
        guard let url = absolute(path) else { throw Failure.notPaired }
        let data = try await run(URLRequest(url: url))
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("orbit-share-\(UUID().uuidString.prefix(8))", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let out = dir.appendingPathComponent(name.isEmpty ? url.lastPathComponent : name)
        try data.write(to: out, options: .atomic)
        return out
    }

    // ------------------------------------------------------------ settings and administration

    /// One authenticated call for OrbitServer+Settings.swift, which lives in its
    /// own file and so cannot reach the private helpers above.
    @discardableResult
    func settingsCall(_ path: String, method: String = "GET", body: [String: Any]? = nil,
                      timeout: TimeInterval? = nil) async throws -> Data {
        var req = try request(path, method: method, body: method == "GET" ? nil : (body ?? [:]))
        if let timeout { req.timeoutInterval = timeout }
        return try await run(req)
    }
}
