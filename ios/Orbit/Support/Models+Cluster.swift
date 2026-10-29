import Foundation

/// The cluster page (`/api/cluster`) and the models served from its GPUs
/// (`/api/servers`). The Mac's page and the phone read the same answers, so
/// these are read leniently from `JSONValue`: a field that is missing or has
/// another type is simply nil, and never costs the whole screen.
/// Sizes are KB, times are unix seconds, durations are seconds.

extension JSONValue {
    /// A non-empty string field.
    func str(_ k: String) -> String? { self[k]?.string.flatMap { $0.isEmpty ? nil : $0 } }
    func dbl(_ k: String) -> Double? { self[k]?.double }
    func integer(_ k: String) -> Int? {
        guard let d = self[k]?.double, d.isFinite, abs(d) < 1e15 else { return nil }
        return Int(d)
    }
    func flag(_ k: String) -> Bool? { self[k]?.bool }
    func list(_ k: String) -> [JSONValue] { self[k]?.array ?? [] }
}

// ------------------------------------------------------------------ the cluster page

/// What `look`, `dismiss`, `restore`, `cancel` and `config` all answer with: the
/// last reading of the cluster, when it was read, the settings and what happened.
struct ClusterLook {
    var snapshot: ClusterSnapshot?
    var at: Double?
    var error: String?
    /// The Mac's own clock, so an age is the Mac's and not the phone's (which may be off).
    var now: Double?
    var nextRefresh: Double?
    var config: ClusterConfig
    var events: [ClusterEvent]
    /// Job names that are model servers: they are started and stopped in Cluster models.
    var modelServerJobs: Set<String>
    /// The usage history kept for each span of days.
    var history: [Int: ClusterHistory]

    init(json v: JSONValue) {
        snapshot = v["snapshot"].flatMap { $0.object == nil ? nil : ClusterSnapshot(json: $0) }
        at = v.dbl("at")
        error = v.str("error")
        now = v.dbl("now")
        nextRefresh = v.dbl("next_refresh")
        config = ClusterConfig(json: v["config"] ?? .null)
        events = v.list("events").map { ClusterEvent(json: $0) }
        modelServerJobs = Set(v["model_server_jobs"]?.strings ?? [])
        var h: [Int: ClusterHistory] = [:]
        for (k, x) in v["history"]?.object ?? [:] {
            if let d = Int(k) { h[d] = ClusterHistory(json: x) }
        }
        history = h
    }

    /// "5 min ago" for a unix-seconds reading, against the Mac's clock.
    func ago(_ t: Double?) -> String {
        guard let t, t > 0 else { return "never" }
        return ClusterFormat.ago(t, now: now ?? Date.now.timeIntervalSince1970)
    }
}

struct ClusterSnapshot {
    var host: ClusterHost?
    var jobs: [ClusterJobFull]
    var recent: [ClusterRecentJob]
    var storage: [ClusterStorage]
    var shared: [ClusterShared]
    var gpus: ClusterGpus?
    var account: ClusterAccount?
    var partitions: [ClusterPartition]
    var problems: [ClusterProblem]
    /// When the slow readings (quotas, limits) were last read.
    var slowAt: Double?

    init(json v: JSONValue) {
        host = v["host"].flatMap { $0.object == nil ? nil : ClusterHost(json: $0) }
        jobs = v.list("jobs").map { ClusterJobFull(json: $0) }
        recent = v.list("recent").map { ClusterRecentJob(json: $0) }
        storage = v.list("storage").map { ClusterStorage(json: $0) }
        shared = v.list("shared").map { ClusterShared(json: $0) }
        gpus = v["gpus"].flatMap { $0.object == nil ? nil : ClusterGpus(json: $0) }
        account = v["account"].flatMap { $0.object == nil ? nil : ClusterAccount(json: $0) }
        partitions = v.list("partitions").map { ClusterPartition(json: $0) }
        problems = v.list("problems").map { ClusterProblem(json: $0) }
        slowAt = v.dbl("slow_at")
    }

    var running: [ClusterJobFull] { jobs.filter(\.isRunning) }
    var waiting: [ClusterJobFull] { jobs.filter(\.isPending) }
    /// GPUs of yours in use now, against the per-user limit.
    var gpusInUse: Int { running.reduce(0) { $0 + ($1.gpus ?? 0) } }
}

/// The login node Orbit looks through.
struct ClusterHost {
    var node: String?
    var processes: Int?
    var processLimit: Int?
    var load: String?
    init(json v: JSONValue) {
        node = v.str("node"); processes = v.integer("processes")
        processLimit = v.integer("process_limit"); load = v.str("load")
    }
}

/// A job in the queue, as `squeue` shows it.
struct ClusterJobFull: Identifiable, Hashable {
    var id: String
    var name: String
    var state: String
    var partition: String?
    var node: String?
    var elapsed: Double?
    var limit: Double?
    var left: Double?
    var cpus: Int?
    var mem: String?
    var gpus: Int?
    var reason: String?
    var submitted: String?
    var startEstimate: String?

    init(json v: JSONValue) {
        id = v.str("id") ?? v.integer("id").map(String.init) ?? ""
        name = v.str("name") ?? ""
        state = v.str("state") ?? ""
        partition = v.str("partition"); node = v.str("node")
        elapsed = v.dbl("elapsed"); limit = v.dbl("limit"); left = v.dbl("left")
        cpus = v.integer("cpus"); mem = v.str("mem"); gpus = v.integer("gpus")
        reason = v.str("reason"); submitted = v.str("submitted"); startEstimate = v.str("start_est")
    }

    var isRunning: Bool { state == "RUNNING" }
    var isPending: Bool { state == "PENDING" }
    var stateLabel: String { ClusterFormat.stateWords(state) }
}

/// A job that ended in the last days, from the scheduler's accounting.
struct ClusterRecentJob: Identifiable, Hashable {
    var id: String
    var name: String
    var state: String
    var partition: String?
    var node: String?
    var elapsed: Double?
    var exit: String?
    var start: String?
    var gpus: Int?

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        name = v.str("name") ?? ""
        state = v.str("state") ?? ""
        partition = v.str("partition"); node = v.str("node")
        elapsed = v.dbl("elapsed"); exit = v.str("exit"); start = v.str("start"); gpus = v.integer("gpus")
    }

    var stateLabel: String { ClusterFormat.stateWords(state) }
    /// Did not finish well: there is a cause to read.
    var wentWrong: Bool { ["FAILED", "OUT_OF_MEMORY", "NODE_FAIL", "TIMEOUT"].contains(state) }
}

/// A quota (home or scratch).
struct ClusterStorage: Identifiable, Hashable {
    var id: String
    var label: String
    var pct: Int?
    var filesPct: Int?
    var usedKB: Double?
    var limitKB: Double?

    init(json v: JSONValue) {
        label = v.str("label") ?? v.str("filesystem") ?? "Disk"
        id = label
        pct = v.integer("pct"); filesPct = v.integer("files_pct")
        usedKB = v.dbl("used_kb")
        let quota = v.dbl("quota_kb") ?? 0
        limitKB = quota > 0 ? quota : v.dbl("limit_kb")
    }

    /// The `which` the Mac measures for this quota, if it can be.
    var place: String? { label == "Home" ? "home" : label == "Scratch" ? "scratch" : nil }
}

/// The lab's shared disk.
struct ClusterShared: Identifiable, Hashable {
    var id: String { mount }
    var mount: String
    var size: String?
    var used: String?
    var avail: String?
    var pct: Int?
    init(json v: JSONValue) {
        mount = v.str("mount") ?? ""
        size = v.str("size"); used = v.str("used"); avail = v.str("avail"); pct = v.integer("pct")
    }
}

struct ClusterGpus {
    var models: [Model]
    var nodes: [Node]
    var free: Int?
    var total: Int?

    struct Model: Identifiable, Hashable {
        var id: String { name + (vram ?? "") }
        var name: String
        var vram: String?
        var nodes: Int?
        var gpus: Int?
        var free: Int?
        init(json v: JSONValue) {
            name = v.str("model") ?? "GPU"; vram = v.str("vram")
            nodes = v.integer("nodes"); gpus = v.integer("gpus"); free = v.integer("free")
        }
    }

    struct Node: Identifiable, Hashable {
        var id: String { name }
        var name: String
        var model: String?
        var free: Int?
        var total: Int?
        var state: String?
        var idleCPUs: String?
        var freeMem: String?
        var partitions: String?
        init(json v: JSONValue) {
            name = v.str("node") ?? "?"; model = v.str("model")
            free = v.integer("free"); total = v.integer("total"); state = v.str("state")
            idleCPUs = v.str("idle_cpus"); freeMem = v.str("free_mem"); partitions = v.str("partitions")
        }
    }

    init(json v: JSONValue) {
        models = v.list("models").map { Model(json: $0) }
        nodes = v.list("nodes").map { Node(json: $0) }
        free = v.integer("free"); total = v.integer("total")
    }
}

/// Your account's limits and the partition jobs run on.
struct ClusterAccount {
    var account: String?
    var fairshare: Double?
    var cpuLimit: Int?
    var gpuLimit: Int?
    var nodeLimit: Int?
    var runningJobLimit: Int?
    var partitionName: String?
    var maxTime: String?
    var partitionCPUs: Int?
    var idleCPUs: Int?
    var idleNodes: Int?
    var partitionNodes: Int?

    init(json v: JSONValue) {
        account = v.str("account"); fairshare = v.dbl("fairshare")
        let lim = v["limits"] ?? .null
        cpuLimit = lim.integer("cpus"); gpuLimit = lim.integer("gpus")
        nodeLimit = lim.integer("nodes"); runningJobLimit = lim.integer("running_jobs")
        let p = v["partition"] ?? .null
        partitionName = p.str("name"); maxTime = p.str("max_time")
        partitionCPUs = p.integer("cpus"); idleCPUs = p.integer("idle_cpus")
        idleNodes = p.integer("idle_nodes"); partitionNodes = p.integer("nodes")
    }
}

struct ClusterPartition: Identifiable, Hashable {
    var id: String { name }
    var name: String
    var up: Bool
    var maxTime: String?
    var cpusIdle: Int?
    var cpusTotal: Int?
    init(json v: JSONValue) {
        name = v.str("partition") ?? "?"; up = v.flag("up") ?? true
        maxTime = v.str("max_time"); cpusIdle = v.integer("cpus_idle"); cpusTotal = v.integer("cpus_total")
    }
}

/// What deserves a look, in plain words.
struct ClusterProblem: Identifiable, Hashable {
    var id: String { key }
    var key: String
    var level: String
    var text: String
    var ids: [String]
    var dismissed: Bool
    init(json v: JSONValue) {
        key = v.str("key") ?? ""
        level = v.str("level") ?? "info"
        text = v.str("text") ?? key
        ids = v["ids"]?.strings ?? []
        dismissed = v.flag("dismissed") ?? false
    }
}

/// One thing that happened: a job submitted, started, finished, failed; a disk filling up.
struct ClusterEvent: Identifiable, Hashable {
    var id: String { "\(t)|\(kind)|\(job ?? "")|\(text)" }
    var t: Double
    var kind: String
    var text: String
    var job: String?
    var detail: String?
    var causeTitle: String?
    var causeFix: String?
    var causeExplained: String?

    init(json v: JSONValue) {
        t = v.dbl("t") ?? 0
        kind = v.str("kind") ?? ""
        text = v.str("text") ?? ""
        job = v.str("job"); detail = v.str("detail")
        let c = v["cause"] ?? .null
        causeTitle = c.str("title"); causeFix = c.str("fix"); causeExplained = c.str("explained")
    }

    /// The ones that are about something going wrong.
    var isTrouble: Bool { ["failed", "error", "pending", "disk"].contains(kind) }
}

/// The cluster page's own settings: what it watches and when it reads again.
struct ClusterConfig {
    var host: String?
    var projectDir: String
    var watch: Bool
    var explain: Bool
    var notify: [String: Bool]
    var refreshOn: Bool
    var refreshEveryHours: Int
    var refreshAt: String
    var remeasure: Bool

    /// The events it can tell you about, in the order the Mac lists them.
    static let notifyKinds: [(key: String, label: String)] = [
        ("started", "a job starts"), ("finished", "a job finishes"), ("failed", "a job fails"),
        ("errors", "a running job prints an error"), ("pending", "a job has waited 4 hours"),
        ("disk", "a disk is filling up"), ("digest", "a summary each morning")]

    init(json v: JSONValue) {
        host = v.str("host")
        projectDir = v.str("project_dir") ?? ""
        watch = v.flag("watch") ?? true
        explain = v.flag("explain") ?? true
        var n: [String: Bool] = [:]
        for (k, x) in v["notify"]?.object ?? [:] { if let b = x.bool { n[k] = b } }
        notify = n
        let r = v["refresh"] ?? .null
        refreshOn = r.flag("on") ?? true
        refreshEveryHours = r.integer("every_h") ?? 24
        refreshAt = r.str("at") ?? "03:00"
        remeasure = r.flag("remeasure") ?? true
    }
}

/// The scheduler's accounting over some days (`history`).
struct ClusterHistory {
    struct Name: Identifiable, Hashable {
        var id: String { name }
        var name: String
        var jobs: Int
        var ok: Int
        var failed: Int
        var medianWait: Double?
        var medianRun: Double?
        var gpuHours: Double
        init(json v: JSONValue) {
            name = v.str("name") ?? "?"; jobs = v.integer("jobs") ?? 0
            ok = v.integer("ok") ?? 0; failed = v.integer("failed") ?? 0
            medianWait = v.dbl("median_wait"); medianRun = v.dbl("median_run")
            gpuHours = v.dbl("gpu_hours") ?? 0
        }
    }

    struct Day: Identifiable, Hashable {
        var id: String { day }
        var day: String
        var jobs: Int
        var gpuHours: Double
        var cpuHours: Double
        init(json v: JSONValue) {
            day = v.str("day") ?? ""; jobs = v.integer("jobs") ?? 0
            gpuHours = v.dbl("gpu_hours") ?? 0; cpuHours = v.dbl("cpu_hours") ?? 0
        }
    }

    var days: Int
    var ran: Int
    var completed: Int
    var failed: Int
    var cancelled: Int
    var gpuHours: Double
    var cpuHours: Double
    var medianWait: Double?
    var byName: [Name]
    var daily: [Day]
    var readAt: Double?

    init(json v: JSONValue) {
        days = v.integer("days") ?? 7
        ran = v.integer("ran") ?? 0; completed = v.integer("completed") ?? 0
        failed = v.integer("failed") ?? 0; cancelled = v.integer("cancelled") ?? 0
        gpuHours = v.dbl("gpu_hours") ?? 0; cpuHours = v.dbl("cpu_hours") ?? 0
        medianWait = v.dbl("median_wait")
        byName = v.list("by_name").map { Name(json: $0) }
        daily = v.list("daily").map { Day(json: $0) }
        readAt = v.dbl("read_at")
    }
}

/// What is directly inside a place on the cluster disk, as the measuring job counted it (`du_status`).
struct ClusterFolder {
    struct Row: Identifiable, Hashable {
        var id: String { path }
        var path: String
        var kb: Double
        var isFolder: Bool
        init(json v: JSONValue) {
            path = v.str("path") ?? ""; kb = v.dbl("kb") ?? 0; isFolder = (v.str("kind") ?? "d") == "d"
        }
        var name: String { path.split(separator: "/").last.map(String.init) ?? path }
    }

    struct Person: Identifiable, Hashable {
        var id: String { owner }
        var owner: String
        var kb: Double
        var folders: [String]
        init(json v: JSONValue) {
            owner = v.str("owner") ?? "?"; kb = v.dbl("kb") ?? 0; folders = v["folders"]?.strings ?? []
        }
    }

    struct File: Identifiable, Hashable {
        var id: String { path }
        var path: String
        var kb: Double
        var mtime: Double?
        init(json v: JSONValue) { path = v.str("path") ?? ""; kb = v.dbl("kb") ?? 0; mtime = v.dbl("mtime") }
        var name: String { path.split(separator: "/").last.map(String.init) ?? path }
    }

    struct Kind: Identifiable, Hashable {
        var id: String { ext }
        var ext: String
        var count: Int
        var kb: Double
        init(json v: JSONValue) { ext = v.str("ext") ?? "?"; count = v.integer("count") ?? 0; kb = v.dbl("kb") ?? 0 }
    }

    var path: String
    var rows: [Row]
    var entries: Int
    var totalEntries: Int
    var totalKB: Double
    var running: Bool
    var done: Bool
    var measuredAt: Double?
    var startedAt: Double?
    var people: [Person]
    var files: [File]
    var kinds: [Kind]
    var fileCount: Int?
    var summaryKB: Double?
    var oldFiles: Int?
    var oldKB: Double?
    var readAt: Double?

    init(json v: JSONValue) {
        path = v.str("path") ?? ""
        rows = v.list("rows").map { Row(json: $0) }
        entries = v.integer("entries") ?? 0; totalEntries = v.integer("total_entries") ?? 0
        totalKB = v.dbl("total_kb") ?? 0
        running = v.flag("running") ?? false; done = v.flag("done") ?? false
        measuredAt = v.dbl("measured_at"); startedAt = v.dbl("started_at")
        people = v.list("people").map { Person(json: $0) }
        files = v.list("files").map { File(json: $0) }
        kinds = v.list("ext").map { Kind(json: $0) }
        let s = v["summary"] ?? .null
        fileCount = s.integer("files"); summaryKB = s.dbl("kb")
        oldFiles = s.integer("old_files"); oldKB = s.dbl("old_kb")
        readAt = v.dbl("read_at")
    }
}

/// How much of what a job asked for it used (`efficiency`).
struct ClusterEfficiency {
    var cpus: Int?
    var cpuEff: Int?
    var memUsedMB: Double?
    var memRequestedMB: Double?
    var memEff: Int?
    var notes: [String]
    init(json v: JSONValue) {
        cpus = v.integer("cpus"); cpuEff = v.integer("cpu_eff")
        memUsedMB = v.dbl("mem_used_mb"); memRequestedMB = v.dbl("mem_requested_mb"); memEff = v.integer("mem_eff")
        notes = v["notes"]?.strings ?? []
    }

    var summary: String {
        var lines: [String] = []
        if let e = cpuEff, let c = cpus { lines.append("CPU used: \(e)% of \(c) CPUs") }
        else { lines.append("CPU used: unknown") }
        if let u = memUsedMB {
            let asked = memRequestedMB.map { " of \(Int($0)) MB asked for" + (memEff.map { " (\($0)%)" } ?? "") } ?? ""
            lines.append("Memory used: \(Int(u)) MB" + asked)
        } else { lines.append("Memory used: unknown") }
        lines += notes
        if cpuEff == nil && memEff == nil {
            lines.append("The scheduler did not record usage for this job (it may have ended too fast).")
        }
        return lines.joined(separator: "\n")
    }
}

/// A node that could start a job asking for this much right now (`where`).
struct ClusterFit {
    struct Node: Identifiable, Hashable {
        var id: String { name }
        var name: String
        var model: String?
        var freeGPUs: Int?
        var freeMem: String?
        init(json v: JSONValue) {
            name = v.str("node") ?? "?"; model = v.str("model")
            freeGPUs = v.integer("free_gpus"); freeMem = v.str("free_mem")
        }
    }

    var nodes: [Node]
    var gpuLimit: Int?
    var overLimit: Bool
    init(json v: JSONValue) {
        nodes = v.list("nodes").map { Node(json: $0) }
        gpuLimit = v.integer("gpu_limit"); overLimit = v.flag("over_limit") ?? false
    }
}

/// One of your processes on the login node.
struct ClusterProcess: Identifiable, Hashable {
    var id: Int { pid }
    var pid: Int
    var age: Double
    var cmd: String
    /// Keeps your login itself alive: stopping it would end the session.
    var system: Bool
    init(json v: JSONValue) {
        pid = v.integer("pid") ?? 0; age = v.dbl("age") ?? 0
        cmd = v.str("cmd") ?? ""; system = v.flag("system") ?? false
    }
}

/// Words and numbers the cluster screens share.
enum ClusterFormat {
    /// squeue's and sacct's states, as words.
    static func stateWords(_ s: String) -> String {
        switch s {
        case "RUNNING": return "running"
        case "PENDING": return "waiting"
        case "COMPLETED": return "finished"
        case "OUT_OF_MEMORY": return "out of memory"
        default: return s.lowercased().replacingOccurrences(of: "_", with: " ")
        }
    }

    /// 93 -> "1 min", 7300 -> "2 h 1 min", 200000 -> "2 d 7 h".
    static func duration(_ t: Double?) -> String {
        guard let t else { return "—" }
        let s = Int(max(0, t.rounded()))
        let d = s / 86400, h = s % 86400 / 3600, m = s % 3600 / 60
        if d > 0 { return "\(d) d \(h) h" }
        if h > 0 { return "\(h) h \(m) min" }
        if m > 0 { return "\(m) min" }
        return "\(s) s"
    }

    /// A size in KB, as the unit that reads best.
    static func size(kb: Double?) -> String {
        guard let kb else { return "—" }
        if kb >= 1_073_741_824 { return String(format: "%.1f TB", kb / 1_073_741_824) }
        if kb >= 1_048_576 { return String(format: "%.1f GB", kb / 1_048_576) }
        return "\(Int((kb / 1024).rounded())) MB"
    }

    static func ago(_ t: Double, now: Double) -> String {
        let d = now - t
        if d < 20 { return "just now" }
        if d < 90 { return "\(Int(d)) s ago" }
        if d < 5400 { return "\(Int((d / 60).rounded())) min ago" }
        if d < 172_800 { return "\(Int((d / 3600).rounded())) h ago" }
        return "\(Int((d / 86400).rounded())) d ago"
    }

    /// squeue's "(ReqNodeNotAvail, UnavailableNodes:g34,n[1010-1017,…])" as its first word: the rest is a node list.
    static func shortReason(_ r: String) -> String {
        let t = r.trimmingCharacters(in: CharacterSet(charactersIn: "()"))
        return String(t.split(separator: ",").first ?? Substring(t))
    }

    /// slurm's "2026-10-28T11:53:53" without the T and the year.
    static func shortTime(_ s: String?) -> String {
        guard let s, s.count >= 16 else { return s ?? "" }
        return String(s.replacingOccurrences(of: "T", with: " ").dropFirst(5).prefix(11))
    }
}

// ------------------------------------------------------------------ models on the cluster's GPUs

/// `/api/servers {op: list}`: the models served from a cluster GPU, and the logins used to reach them.
struct ModelServers {
    var servers: [ModelServer]
    var now: Double?
    var connections: [Connection]

    struct Connection: Identifiable, Hashable {
        var id: Int
        var age: String
        var mine: Bool
        var what: String
        init(json v: JSONValue) {
            id = v.integer("pid") ?? 0; age = v.str("age") ?? ""
            mine = v.flag("mine") ?? false; what = v.str("what") ?? ""
        }
    }

    init(json v: JSONValue) {
        servers = v.list("servers").map { ModelServer(json: $0) }
        now = v.dbl("now")
        connections = v.list("connections").map { Connection(json: $0) }
    }
}

/// One model served from a cluster GPU: what it is served with, its schedule, and what it is doing now.
struct ModelServer: Identifiable {
    var id: String
    var label: String
    var host: String?
    var dir: String?
    /// The name its API answers to.
    var model: String
    var port: Int?
    /// The Orbit provider that reaches it, where the Mac says (otherwise matched by port).
    var provider: String?
    /// Everything it is served with; sent back by key, only what changed.
    var settings: [String: JSONValue]
    var schedule: [ServerSchedule]
    var email: String
    var desktop: Bool
    var events: [String: Bool]
    var status: ServerStatus

    init(json v: JSONValue) {
        id = v.str("id") ?? ""
        label = v.str("label") ?? id
        host = v.str("host"); dir = v.str("dir")
        model = v.str("model") ?? id
        port = v.integer("local_port"); provider = v.str("provider")
        settings = v["settings"]?.object ?? [:]
        schedule = v.list("schedule").map { ServerSchedule(json: $0) }
        let n = v["notify"] ?? .null
        email = n.str("email") ?? ""
        desktop = n.flag("desktop") ?? true
        var e: [String: Bool] = [:]
        for (k, x) in n["events"]?.object ?? [:] { if let b = x.bool { e[k] = b } }
        events = e
        status = ServerStatus(json: v["status"] ?? .null)
    }
}

/// A start and a stop time, on some days.
struct ServerSchedule: Identifiable, Hashable {
    var id: String
    var enabled: Bool
    var start: String
    var stop: String
    /// 0 = Monday.
    var days: Set<Int>
    /// One day only ("2026-10-28"), where set.
    var on: String?

    init(json v: JSONValue) {
        id = v.str("id") ?? UUID().uuidString
        enabled = v.flag("enabled") ?? true
        start = v.str("start") ?? ""; stop = v.str("stop") ?? ""
        let d = (v["days"]?.array ?? []).compactMap(\.int)
        days = d.isEmpty ? Set(0...6) : Set(d)
        on = v.str("on")
    }

    init() {
        id = "new" + String(Int(Date.now.timeIntervalSince1970 * 1000) % 100_000_000)
        enabled = true; start = "08:00"; stop = "22:00"; days = Set(0...6); on = nil
    }

    var json: [String: Any] {
        var o: [String: Any] = ["id": id, "enabled": enabled, "start": start, "stop": stop]
        if let on { o["on"] = on } else { o["days"] = days.sorted() }
        return o
    }
}

/// What the Mac knows about a model server right now.
struct ServerStatus {
    var state: String
    var reason: String?
    var jid: String?
    var node: String?
    var error: String?
    var mailError: String?
    var submitted: Double?
    var ready: Double?
    var left: Double?
    var contextLength: Int?
    var next: (kind: String, at: Double)?
    var renewOn: Bool
    var renewUntil: String?
    var healthOK: Bool?
    var healthSeconds: Double?
    var healthFails: Int?
    var healthError: String?
    var healthAt: Double?
    var placement: String?
    var stats: Stats?
    var bench: Bench?

    /// The model's own counters (no chat text in them).
    struct Stats {
        var off: Bool
        var rows: [(label: String, value: String)]
    }

    struct Bench {
        var at: Double?
        var decodeTPS: Double?
        var promptTokens: Int?
        var prefillTPS: Double?
        var coldSeconds: Double?
        var warmSeconds: Double?
    }

    init(json v: JSONValue) {
        state = v.str("state") ?? "unknown"
        reason = v.str("reason").flatMap { $0 == "None" ? nil : $0 }
        jid = v.str("jid") ?? v.integer("jid").map(String.init)
        node = v.str("node"); error = v.str("error"); mailError = v.str("mail_error")
        submitted = v.dbl("t_submit"); ready = v.dbl("t_ready"); left = v.dbl("left")
        contextLength = v["info"]?.integer("max_model_len")
        if let n = v["next"], let k = n.str("kind"), let a = n.dbl("at") { next = (k, a) }
        renewOn = v["renew"]?.flag("on") ?? false
        renewUntil = v["renew"]?.str("until")
        if let h = v["health"], h.object != nil {
            healthOK = h.flag("ok"); healthSeconds = h.dbl("s"); healthFails = h.integer("fails")
            healthError = h.str("error"); healthAt = h.dbl("at")
        }
        placement = Self.placementNote(v["placement"])
        stats = Self.stats(v["stats"])
        if let b = v["bench"], b.object != nil {
            bench = Bench(at: b.dbl("at"), decodeTPS: b.dbl("decode_tps"), promptTokens: b.integer("prompt_tokens"),
                          prefillTPS: b.dbl("prefill_tps"), coldSeconds: b.dbl("cold_s"), warmSeconds: b.dbl("warm_s"))
        }
    }

    var isBusy: Bool { ["queued", "loading", "ready", "stopping"].contains(state) }
    var isReady: Bool { state == "ready" }

    var stateLabel: String {
        switch state {
        case "ready": return "Ready"
        case "loading": return "Loading the model"
        case "queued": return "Waiting for a GPU"
        case "stopping": return "Stopping"
        case "stopped": return "Stopped"
        case "failed": return "Failed"
        case "unreachable": return "Cluster not reachable"
        default: return "Checking…"
        }
    }

    /// Where the job was placed and why, in a sentence.
    private static func placementNote(_ p: JSONValue?) -> String? {
        guard let p, let c = p["chosen"], let part = c.str("partition") else { return nil }
        var s = "Placed on \(part)"
        if let m = c.integer("mem_gb") { s += " with \(m) GB" }
        switch p.str("how") {
        case "model": s += ", chosen by a model" + (p.str("why").map { ": \($0)" } ?? "")
        default: s += ", the soonest the scheduler offered"
        }
        if let start = c.dbl("start"), let at = p.dbl("at") {
            let mins = max(0, Int(((start - at) / 60).rounded()))
            s += mins < 90 ? " (estimated start in \(mins) min)" : " (estimated start in \(mins / 60) h)"
        }
        return s + "."
    }

    private static func stats(_ x: JSONValue?) -> Stats? {
        guard let x, x.object != nil else { return nil }
        if x.flag("off") == true { return Stats(off: true, rows: []) }
        func pct(_ k: String) -> String? { x.dbl(k).map { "\(Int(($0 * 100).rounded()))%" } }
        func num(_ k: String) -> String? { x.dbl(k).map { $0 == $0.rounded() ? "\(Int($0))" : String(format: "%.1f", $0) } }
        func sec(_ k: String) -> String? { x.dbl(k).map { String(format: "%.1f s", $0) } }
        let all: [(String, String?)] = [
            ("Tokens per second, one answer", num("decode_tps")),
            ("Tokens per second, all answers", num("throughput_tps")),
            ("Until the first word", sec("ttft_s")),
            ("A whole answer, on average", sec("e2e_s")),
            ("Prompt tokens read per second", num("prefill_tps")),
            ("Prompts found in its cache", pct("cache_hit")),
            ("Context memory in use", pct("kv_used")),
            ("Look-ahead guesses accepted", pct("accepted")),
            ("Answering · waiting", [num("running"), num("waiting")].compactMap { $0 }.joined(separator: " · ")),
            ("Answers since it started", num("finished")),
            ("Tokens read", num("prompt_tokens")),
            ("Tokens written", num("generated_tokens"))]
        return Stats(off: false, rows: all.compactMap { l, v in (v?.isEmpty ?? true) ? nil : (l, v!) })
    }
}
