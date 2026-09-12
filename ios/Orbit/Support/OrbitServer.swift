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

    private func request(_ path: String, method: String = "GET",
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

    private func run(_ req: URLRequest) async throws -> Data {
        do {
            let (data, resp) = try await session.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if code == 401 { throw Failure.unauthorised }
            guard (200..<300).contains(code) else {
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

    private func get<T: Decodable>(_ path: String, as: T.Type) async throws -> T {
        let data = try await run(try request(path))
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    @discardableResult
    private func post(_ path: String, _ body: [String: Any] = [:]) async throws -> Data {
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
    func alternates() async throws -> (url: String?, alts: [String]) {
        struct R: Codable { var url: String?; var alts: [String]? }
        let r = try await get("/api/remote", as: R.self)
        return (r.url, r.alts ?? [])
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
    func live(_ sid: String) async throws -> (running: Bool, content: String, thinking: String) {
        struct L: Codable {
            var known: Bool?; var running: Bool?; var content: String?
            var thinking: String?; var status: String?
        }
        let l = try await get("/api/live/\(sid)", as: L.self)
        return (l.running ?? false, l.content ?? "", l.thinking ?? "")
    }

    /// Any authenticated GET returning bytes — images, thumbnails, downloads.
    func fetchRaw(_ path: String) async throws -> Data {
        try await run(try request(path))
    }

    /// Search inside every conversation, not just their titles.
    func search(_ q: String) async throws -> [SearchHit] {
        let escaped = q.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? q
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
              attachments: [[String: String]] = []) -> AsyncThrowingStream<StreamEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var body: [String: Any] = ["sid": sid, "message": message]
                    if !attachments.isEmpty { body["attachments"] = attachments }
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

        func str(_ key: String) -> String {
            ((p as? [String: Any])?[key] as? String) ?? ""
        }

        switch kind {
        case "content_delta":  return .content(p as? String ?? "")
        case "thinking_delta": return .thinking(p as? String ?? "")
        case "model":          return .model(str("label").isEmpty ? str("id") : str("label"))
        case "tool":
            let args = ((p as? [String: Any])?["args"] as? [String: Any]) ?? [:]
            let rendered = args.map { "\($0.key)=\(String(describing: $0.value).prefix(40))" }
                               .sorted().joined(separator: ", ")
            return .tool(name: str("name"), args: rendered)
        case "tool_result":    return .toolResult(name: str("name"), output: str("output"))
        case "server_starting":
            let msg = str("msg")
            return .status(msg.isEmpty ? "starting the model" : msg)
        case "server_ready":   return .status("")
        case "squeezed":       return .status("trimming older tool output")
        case "autocompact":    return .status("summarising earlier turns")
        case "autocompact_done", "stagnation": return .status("")
        case "blocked":        return .blocked(reason: str("reason"))
        case "auto_approved":  return .autoApproved(name: str("name"), reason: str("reason"))
        // "approval_request" carries the id /api/approve answers to; the bare
        // "approval" event before it never did, so a prompt on the phone could
        // not actually be answered
        case "approval_request":
            return .approval(name: str("name"), reason: str("reason"),
                             id: (p as? [String: Any])?["id"] as? String)
        case "approval":       return nil
        case "interjection":   return .status("reading your note")
        case "queued":         return .status("waiting for another chat to finish")
        case "dequeued":       return .status("its turn — starting")
        case "retry":          return .status("model error — retrying")
        case "subtask":
            let d = str("description")
            return .status(d.isEmpty ? "a helper is working" : "helper: \(d)")
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
}
