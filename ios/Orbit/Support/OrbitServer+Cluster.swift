import Foundation

/// The cluster page and the models served from its GPUs. Every call mirrors what
/// the Mac's web page sends to `/api/cluster` and `/api/servers`.
///
/// Reading the cluster is an SSH connection and the cluster limits how often it
/// may be reached, so the page opens on the Mac's last reading (`cached`) and
/// only `force` connects. Starting, stopping and cancelling are real: they
/// change jobs on the cluster's GPUs.
extension OrbitServer {

    // ------------------------------------------------------------ the cluster page

    private func clusterCall(_ op: String, _ extra: [String: Any] = [:],
                             timeout: TimeInterval = 30) async throws -> JSONValue {
        var body = extra
        body["op"] = op
        let data = try await settingsCall("/api/cluster", method: "POST", body: body, timeout: timeout)
        guard let v = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw Failure.decoding("cluster/\(op)")
        }
        if let e = v.str("error") { throw Failure.server(400, e) }
        return v
    }

    /// The whole picture. `cached` is the Mac's last reading, at once; `force` reads
    /// the cluster again; `slow` also re-reads quotas and limits, which are slow.
    func clusterLook(cached: Bool = false, force: Bool = false, slow: Bool = false) async throws -> ClusterLook {
        var extra: [String: Any] = [:]
        if cached { extra["cached"] = true }
        if force { extra["force"] = true }
        if slow { extra["slow"] = true }
        return ClusterLook(json: try await clusterCall("look", extra, timeout: 120))
    }

    /// Put a warning away; it comes back if it changes.
    func clusterDismiss(key: String) async throws -> ClusterLook {
        ClusterLook(json: try await clusterCall("dismiss", ["key": key]))
    }

    func clusterRestore(key: String) async throws -> ClusterLook {
        ClusterLook(json: try await clusterCall("restore", ["key": key]))
    }

    /// Cancel one of your jobs. Answers with a fresh look.
    func clusterCancelJob(id: String) async throws -> ClusterLook {
        ClusterLook(json: try await clusterCall("cancel", ["id": id], timeout: 120))
    }

    /// The cluster's own explanation: `why` a job waits, or what `diagnose` found when it went wrong.
    func clusterExplain(id: String, kind: String) async throws -> String {
        try await clusterCall("explain", ["id": id, "kind": kind], timeout: 90).str("text") ?? ""
    }

    /// The end of a job's output file.
    func clusterOutput(id: String, lines: Int = 120) async throws -> String {
        try await clusterCall("output", ["id": id, "lines": lines], timeout: 60).str("text") ?? ""
    }

    func clusterEfficiency(id: String) async throws -> ClusterEfficiency {
        ClusterEfficiency(json: try await clusterCall("efficiency", ["id": id], timeout: 60))
    }

    /// What a chat needs to help with one job: its record, the diagnosis and the end of its output.
    func clusterAskText(id: String) async throws -> String {
        try await clusterCall("ask", ["id": id], timeout: 90).str("text") ?? ""
    }

    /// Which GPU nodes could start a job asking for this right now. Answers from the last look; reads nothing.
    func clusterWhere(gpus: Int, memGB: Int, cpus: Int, model: String) async throws -> ClusterFit {
        ClusterFit(json: try await clusterCall(
            "where", ["gpus": gpus, "mem_gb": memGB, "cpus": cpus, "model": model]))
    }

    /// Usage over the last `days`. The kept reading unless `refresh`, which asks the scheduler again.
    func clusterHistory(days: Int, refresh: Bool = false) async throws -> ClusterHistory {
        ClusterHistory(json: try await clusterCall("history", ["days": days, "refresh": refresh], timeout: 120))
    }

    /// What a measuring job has counted so far in a place (`home`, `scratch`, `mine`, `lab`) or a folder under one.
    /// The kept reading unless `refresh`.
    func clusterFolder(_ which: String, refresh: Bool = false) async throws -> ClusterFolder {
        ClusterFolder(json: try await clusterCall("du_status", ["which": which, "refresh": refresh], timeout: 90))
    }

    /// Start the small batch job that measures a place (never on the login node). The one real submit
    /// the cluster page can make; the caller confirms first.
    func clusterMeasure(_ which: String) async throws {
        _ = try await clusterCall("du_start", ["which": which], timeout: 90)
    }

    func clusterProcesses() async throws -> [ClusterProcess] {
        try await clusterCall("processes", timeout: 60).list("processes").map { ClusterProcess(json: $0) }
    }

    func clusterStopProcess(pid: Int) async throws -> [ClusterProcess] {
        try await clusterCall("stop_process", ["pid": pid], timeout: 60).list("processes").map { ClusterProcess(json: $0) }
    }

    /// Change what the page watches and when it reads again; only the keys given change.
    func clusterSaveConfig(_ changes: [String: Any]) async throws -> ClusterLook {
        ClusterLook(json: try await clusterCall("config", changes))
    }

    // ------------------------------------------------------------ models on the cluster's GPUs

    private func serversCall(_ op: String, _ extra: [String: Any] = [:],
                             timeout: TimeInterval = 60) async throws -> JSONValue {
        var body = extra
        body["op"] = op
        let data = try await settingsCall("/api/servers", method: "POST", body: body, timeout: timeout)
        guard let v = try? JSONDecoder().decode(JSONValue.self, from: data) else {
            throw Failure.decoding("servers/\(op)")
        }
        if let e = v.str("error") { throw Failure.server(400, e) }
        return v
    }

    /// The servers and what each is doing. Answers from what the Mac already knows: no SSH.
    func modelServers() async throws -> ModelServers {
        ModelServers(json: try await serversCall("list", timeout: 30))
    }

    /// Save a server's name, settings (only the ones changed), schedule or notices.
    @discardableResult
    func saveModelServer(id: String, label: String? = nil, settings: [String: Any]? = nil,
                         schedule: [ServerSchedule]? = nil,
                         notify: [String: Any]? = nil) async throws -> ModelServers {
        var extra: [String: Any] = ["id": id]
        if let label { extra["label"] = label }
        if let settings { extra["settings"] = settings }
        if let schedule { extra["schedule"] = schedule.map(\.json) }
        if let notify { extra["notify"] = notify }
        return ModelServers(json: try await serversCall("save", extra))
    }

    /// `start`, `stop` or `restart`: submits or cancels the server's job on the cluster.
    @discardableResult
    func modelServerAction(_ op: String, id: String) async throws -> ModelServers {
        ModelServers(json: try await serversCall(op, ["id": id], timeout: 120))
    }

    /// Three short requests: writing speed, and reading speed cold and cached. Answers with the list.
    func modelServerSpeedTest(id: String) async throws -> ModelServers {
        ModelServers(json: try await serversCall("speed_test", ["id": id], timeout: 180))
    }

    /// The end of the newest server log kept on the cluster, and its name.
    func modelServerLog(id: String, lines: Int = 150) async throws -> (name: String, text: String) {
        let v = try await serversCall("log", ["id": id, "lines": lines], timeout: 90)
        return (v.str("name") ?? "", v.str("text") ?? "")
    }

    /// Close Orbit's own logins to the cluster. Safe: the next look opens a new one and a
    /// running model keeps running. `chats` also ends chats running there, mid-answer.
    func closeClusterLogins(id: String, chats: Bool) async throws -> Int {
        try await serversCall("close_connections", ["id": id, "chats": chats]).integer("closed") ?? 0
    }

    /// Which Orbit provider reaches the server on each local port (`8012` -> `"cluster"`):
    /// a provider whose address is that port on this Mac, as the Mac's own list shows it.
    func clusterProviderPorts() async throws -> [Int: String] {
        let data = try await settingsCall("/api/models", timeout: 30)
        let v = try JSONDecoder().decode(JSONValue.self, from: data)
        var out: [Int: String] = [:]
        for (pid, p) in v["providers"]?.object ?? [:] {
            guard let url = p.str("base_url"), let u = URL(string: url),
                  let host = u.host, ["127.0.0.1", "localhost"].contains(host), let port = u.port else { continue }
            out[port] = pid
        }
        return out
    }
}

// ---------------------------------------------------------------- Settings → Helpers

extension OrbitServer {
    private func helpersCall(_ body: [String: Any], timeout: TimeInterval = 30) async throws -> JSONValue {
        let data = try await settingsCall("/api/sciencebridge", method: "POST", body: body, timeout: timeout)
        guard let v = try? JSONDecoder().decode(JSONValue.self, from: data) else { throw Failure.decoding("sciencebridge") }
        if let e = v.str("error") { throw Failure.server(400, e) }
        return v
    }

    func helperStatus() async throws -> HelperStatus {
        HelperStatus(json: try await helpersCall(["op": "status"]))
    }

    /// Turn the door on or off. On opens a local address for apps on the Mac; nothing is reachable without an app's token.
    func helperSetEnabled(_ on: Bool) async throws -> HelperStatus {
        HelperStatus(json: try await helpersCall(["op": "configure", "enabled": on]))
    }

    func helperInbox() async throws -> HelperInbox {
        HelperInbox(json: try await helpersCall(["op": "inbox"]))
    }

    /// Answer a job that waits for your yes.
    func helperDecide(job: String, approve: Bool) async throws {
        let v = try await helpersCall(["op": "decide", "job": job, "approve": approve])
        if v.flag("ok") == false { throw Failure.server(400, v.str("error") ?? "it could not start") }
    }

    func helperCancel(job: String) async throws { _ = try await helpersCall(["op": "cancel", "job": job]) }
    func helperForget() async throws { _ = try await helpersCall(["op": "forget"]) }
    func helperMoreRounds(thread: String) async throws { _ = try await helpersCall(["op": "thread_more", "thread": thread]) }
    func helperEnd(thread: String) async throws { _ = try await helpersCall(["op": "thread_end", "thread": thread]) }

    func helperSaveApp(_ c: HelperClient) async throws -> HelperStatus {
        HelperStatus(json: try await helpersCall(["op": "configure", "client": c.id, "settings": c.settingsJSON]))
    }

    func helperAddApp(name: String) async throws -> HelperStatus {
        HelperStatus(json: try await helpersCall(["op": "configure", "add_client": name]))
    }

    func helperRemoveApp(id: String) async throws -> HelperStatus {
        HelperStatus(json: try await helpersCall(["op": "configure", "remove_client": id]))
    }
}
