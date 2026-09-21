import Foundation
import SwiftUI
import PhotosUI
import UserNotifications

/// The one object the views watch.
///
/// It owns the pairing, the chat list, the open conversation and the live
/// stream. Anything that touches the network goes through `server`; anything
/// that must survive a cold launch goes through `Cache`.
@MainActor
final class AppState: ObservableObject {

    // pairing -------------------------------------------------------------
    @Published var pairing: Pairing? { didSet { rebuildServer() } }
    @Published var reachable: Bool? = nil          // nil = not checked yet
    @Published var latencyMS: Int?                 // round trip of the last health check
    /// Which tab is showing — so a deep link from Files can land in Chats.
    @Published var tab = "chats"
    @Published var lastError: String?

    // content -------------------------------------------------------------
    @Published var chats: [ChatSummary] = []
    @Published var openChat: ChatDetail?
    @Published var messages: [Message] = []
    @Published var models: [ModelInfo] = []
    @Published var currentModel: String?
    /// What a brand-new chat answers with, set on the Mac.
    @Published var defaultModel: String?
    @Published var runningChats: Set<String> = []
    /// Set to push a conversation onto the stack — used by deep links today and
    /// by notification taps later.
    @Published var deepLink: String?

    // what is going up with the next message
    @Published var attachments: [Attachment] = []
    @Published var uploading = false
    @Published var localServer = LocalServer()
    // the Mac's automatic backup
    @Published var backup: BackupStatus?
    @Published var backupBusy = false
    @Published var backupNote: String?
    // how much it can do without asking first
    @Published var autonomy: OrbitServer.AutonomySettings?
    @Published var autonomyBusy = false
    // Claude Code and Codex: which harness new chats use, and the SSH hosts
    @Published var harnessMode: HarnessKind = .orbit
    @Published var harnessBusy = false
    @Published var harnessRecent: [RecentModel] = []
    @Published var codexRecent: [RecentModel] = []
    @Published var remoteHosts: [RemoteHost] = []
    /// The last check of each host. Connecting is slow and a cluster may block
    /// an address that does it often, so a result is reused rather than redone.
    @Published var hostProbes: [String: HostProbe] = [:]
    @Published var probeErrors: [String: String] = [:]
    @Published var probing: Set<String> = []
    /// Whether the app is in the background, so a finished answer can announce itself.
    var backgrounded = false
    /// Set when the app went to the background, cleared when it is back in front.
    var wentToBackground = false
    var graceTask: UIBackgroundTaskIdentifier = .invalid

    // the answer in flight --------------------------------------------------
    @Published var streaming = false
    @Published var liveText = ""
    @Published var liveThinking = ""
    @Published var liveTools: [String] = []
    @Published var liveStatus = ""
    @Published var liveModel = ""
    /// The current step's tool calls, running and finished. `liveTools` keeps
    /// the notices (auto-approved, blocked, a switch of model).
    @Published var liveRuns: [ToolRun] = []
    /// Steps of this answer already over: each is its thinking, its words and
    /// the tools it then called, the way the saved chat splits them.
    @Published var liveSteps: [Message] = []
    /// Notes sent into a running answer, by chat, until the Mac's saved copy shows them.
    var pendingNotes: [String: [Message]] = [:]
    /// For the status line: when the answer began, its word for the work,
    /// roughly how much has come back, and since when it has been thinking.
    /// Read by a timer, so they need not publish.
    var liveStartedAt = Date()
    var liveVerb = "Working"
    var liveChars = 0
    var liveThinkingSince: Date?
    /// When this step's thinking began, and how long it took once words came.
    private var stepThinkStart: Date?
    @Published var liveThoughtSecs: Double?
    /// Each chat's todo list, from the plan tool.
    @Published var plans: [String: [PlanStep]] = [:]
    /// File edits shown while answers ran here, per chat, for /diff.
    @Published var shownDiffs: [String: [ShownDiff]] = [:]
    @Published var pendingApproval: (name: String, reason: String, id: String)?
    /// Which chat the open approval belongs to, so it can be announced if you leave.
    var pendingApprovalChat: String?
    /// Questions, approvals, plan mode, temporary chat, row status (AppState+Chat.swift).
    @Published var chatExtras = ChatExtras()
    /// The list's paging, /tasks and the first-pairing tips (AppState+Work.swift).
    @Published var work = WorkExtras()
    /// Allowance, spend and cheaper hours for the model picker (AppState+Usage.swift).
    @Published var usage = UsageState()

    private(set) var server: OrbitServer?
    private var streamTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    /// Which chat's answer a poll loop is following right now (nil when none is running).
    private var pollingSid: String?
    /// Watches the open chat for changes made elsewhere — the Mac's browser,
    /// another phone — and pulls them in. The count of raw messages on the
    /// Mac is the thing compared; it moves when anyone sends or answers.
    private var watchTask: Task<Void, Never>?
    private var watchedCount: Int?

    init() {
        pairing = Keychain.load()
        rebuildServer()
        chats = Cache.loadChats()
    }

    private func rebuildServer() {
        if let p = pairing {
            server = OrbitServer(pairing: p)
            Keychain.save(p)
        } else {
            server = nil
        }
        FileLinks.shared.server = server
    }

    var isPaired: Bool { pairing != nil }

    // ------------------------------------------------------------ pairing

    /// Accept `orbit://pair?url=…&token=…&name=…`, from a QR scan or a tapped link.
    @discardableResult
    func pair(from url: URL) -> Bool {
        guard url.scheme == "orbit", url.host == "pair",
              let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems
        else { return false }
        let map = Dictionary(items.compactMap { i in i.value.map { (i.name, $0) } },
                             uniquingKeysWith: { a, _ in a })
        guard let base = map["url"], let token = map["token"], !base.isEmpty, !token.isEmpty
        else { return false }
        let alts = (map["alts"] ?? "").split(separator: ",").map(String.init)
            .map { $0.hasSuffix("/") ? String($0.dropLast()) : $0 }
            .filter { !$0.isEmpty }
        pairing = Pairing(url: base.hasSuffix("/") ? String(base.dropLast()) : base,
                          token: token, name: map["name"] ?? "Mac",
                          alts: alts.isEmpty ? nil : alts)
        Task { await refreshEverything() }
        return true
    }

    func pairManually(host: String, token: String, name: String = "Mac") {
        var h = host.trimmingCharacters(in: .whitespaces)
        if !h.hasPrefix("http") { h = "http://" + h }
        if h.hasSuffix("/") { h = String(h.dropLast()) }
        pairing = Pairing(url: h, token: token.trimmingCharacters(in: .whitespaces), name: name)
        Task { await refreshEverything() }
    }

    func unpair() {
        detachLive()
        resetComposerExtras()
        watchTask?.cancel(); watchTask = nil
        Keychain.clear()
        Cache.clear()
        pairing = nil
        chats = []; messages = []; openChat = nil; reachable = nil; queue = .empty
        models = []; projects = []; attachments = []
        currentModel = nil; defaultModel = nil; deepLink = nil
        remoteHosts = []; hostProbes = [:]; probeErrors = [:]; harnessMode = .orbit
        work = WorkExtras()
        localServer = LocalServer()
    }

    /// `currentModel` as the catalogue knows it. A stored local id can drift
    /// from the catalogue's (the Mac names the local model differently when its
    /// server is stopped); anything `local:` still means the local model.
    var effectiveModelID: String? { catalogueID(for: currentModel) }

    func catalogueID(for id: String?) -> String? {
        guard let id else { return nil }
        if models.contains(where: { $0.id == id }) { return id }
        if id.hasPrefix("local:") {
            return models.first { $0.provider == "local" && $0.id.hasPrefix("local:") }?.id ?? id
        }
        return id
    }

    var currentModelName: String {
        models.first { $0.id == effectiveModelID }?.display ?? "model"
    }

    // ------------------------------------------------------------ loading

    func refreshEverything() async {
        await checkReachable()
        guard reachable == true else { return }
        await loadChats()
        await loadModels()
        await loadProjects()
    }

    func checkReachable() async {
        guard let server, let p = pairing else { reachable = false; return }
        do {
            let t0 = Date()
            _ = try await server.health()
            latencyMS = Int(Date().timeIntervalSince(t0) * 1000)
            reachable = true
            lastError = nil
            await learnAlternates()
        } catch {
            // The address in the QR is not always the one that works from here
            // (no MagicDNS on this phone, a new DHCP lease). Try the others the
            // Mac listed and keep whichever answers.
            var candidates = p.alts ?? []
            // a Mac fronted by Tailscale Serve answers over https at its MagicDNS
            // name; a phone paired before that was set up can find it unaided
            if p.url.hasPrefix("http://"), let host = URL(string: p.url)?.host, host.hasSuffix(".ts.net") {
                candidates += ["https://\(host):8443", "https://\(host)"]
            }
            for alt in candidates where alt != p.url {
                let probe = OrbitServer(pairing: Pairing(url: alt, token: p.token, name: p.name, alts: p.alts))
                if (try? await probe.health()) == true {
                    var swapped = p
                    swapped.url = alt
                    swapped.alts = Array(Set((p.alts ?? []) + [p.url])).sorted()
                    pairing = swapped                // rebuilds the client, saved to the Keychain
                    reachable = true
                    lastError = nil
                    return
                }
            }
            reachable = false
            lastError = error.localizedDescription
        }
    }

    /// Once connected, remember every address the Mac answers on.
    private func learnAlternates() async {
        guard let server, var p = pairing else { return }
        guard let found = try? await server.alternates() else { return }
        var all = Set(found.alts)
        if let u = found.url, !u.isEmpty { all.insert(u) }
        all.remove(p.url)
        let list = all.sorted()
        var changed = false
        if list != (p.alts ?? []) { p.alts = list.isEmpty ? nil : list; changed = true }
        // the Mac's own name, which a phone paired from an older QR only knew as a host name
        if let n = found.name, !n.isEmpty, n != p.name { p.name = n; changed = true }
        if changed { pairing = p }
    }

    /// The Mac, the way to name it on screen: its own name, or "your Mac" when all the
    /// phone has is a network host name ("vpn-10-0-0-1…", an IP address).
    var macDisplayName: String {
        guard let raw = pairing?.name, !raw.isEmpty else { return "your Mac" }
        if raw.range(of: #"^\S*\d+[-.]\d+\S*$"#, options: .regularExpression) != nil { return "your Mac" }
        return raw
    }

    /// The last "has anything changed?" answer, so a poll that has not moved costs one
    /// tiny call instead of the whole list.
    private static var chatsStamp = ""

    /// Reload the list only if the Mac says it has changed. `force` skips the check.
    func loadChatsIfChanged(force: Bool = false) async {
        guard let server else { return }
        var seen: String?
        if !force, let stamp = try? await server.chatsStamp() {
            if stamp == Self.chatsStamp, !chats.isEmpty { return }
            seen = stamp
        }
        let before = lastError
        await loadChats()
        // Only once the list actually arrived. Storing it first meant one timed-out
        // page on cellular froze the list for good: every later poll saw the same
        // stamp and returned without trying again.
        if let seen, lastError == before { Self.chatsStamp = seen }
    }

    func loadChats() async {
        guard let server else { return }
        do {
            let page = try await server.chatPage(limit: work.chatLimit)
            let list = keepingExternal(page.items)
            work.chatTotal = page.total
            chats = list
            Cache.saveChats(list)
            lastError = nil
            Task { await prefetch(list) }
        } catch {
            lastError = error.localizedDescription
            if chats.isEmpty { chats = Cache.loadChats() }   // offline: show what we have
        }
    }

    func loadModels() async {
        guard let server else { return }
        if let m = try? await server.models() {
            models = m.models
            defaultModel = m.default
            // a chat with no choice of its own answers with the default, and the
            // default with nothing configured is the local model — say so, rather
            // than showing a chip that reads "model"
            let chosen = [m.current, m.default].compactMap { $0 }.first { !$0.isEmpty }
            currentModel = chosen ?? m.models.first { $0.provider == "local" && $0.isReady }?.id
            harnessRecent = m.harness_recent ?? []
            codexRecent = m.codex_recent ?? []
            if m.harness_mode == true { harnessMode = .claude }
            else if m.codex_mode == true { harnessMode = .codex }
            else if m.harness_mode == false || m.codex_mode == false { harnessMode = .orbit }
            else { harnessMode = HarnessKind(modelID: m.default) }     // a Mac that predates the flags
        }
    }

    /// The last few conversations, fetched quietly so they open offline too.
    /// Reads through `peek`, which does not move what the Mac has open.
    private func prefetch(_ list: [ChatSummary]) async {
        guard let server else { return }
        for c in list.filter({ $0.archived != true && $0.external != true }).prefix(8) {
            if let d = Cache.messagesDate(c.id), d.timeIntervalSince1970 >= c.mtime { continue }
            if let detail = try? await server.peek(c.id) {
                Cache.saveMessages(detail.messages, for: c.id)
            }
        }
    }

    func refreshRunning() async {
        guard let server else { return }
        if let r = try? await server.running() { runningChats = Set(r) }
    }

    /// Stop watching whatever is streaming, without stopping it on the Mac.
    private func detachLive() {
        streamTask?.cancel(); pollTask?.cancel()
        watchTask?.cancel(); watchTask = nil
        flushTask?.cancel(); flushTask = nil; pendingText = ""
        streaming = false; liveSid = nil
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        liveRuns = []; liveSteps = []; liveThinkingSince = nil; stepThinkStart = nil; liveThoughtSecs = nil
        pendingApproval = nil
        chatExtras.question = nil; chatExtras.approval = nil
    }

    func open(_ id: String) async {
        guard let server, !id.isEmpty else { return }
        if streaming, liveSid != nil, liveSid != id {
            // leave the old answer running on the Mac; just stop watching it here
            detachLive()
        }
        if openChat?.sid != id {
            queue = .empty
            // These describe one chat, and only a *successful* load used to replace
            // them: opening a chat from the cache, or when the Mac is briefly out of
            // reach, left the last chat's plan mode and easy mode on screen — and
            // tapping the menu then wrote that answer onto a chat that never set it.
            chatExtras.planMode = false
            chatExtras.prefs = [:]
            chatExtras.easyMode = false
        }
        markSeen(id)
        // show the cached copy immediately; the network fills it in
        if let cached = Cache.loadMessages(id), !cached.isEmpty {
            messages = cached
            openChat = ChatDetail(sid: id, title: chats.first { $0.id == id }?.title,
                                  messages: cached)
        }
        do {
            let d = try await server.chat(id)
            // you may have moved on while it loaded: this chat is no longer the one on screen
            guard openChat == nil || openChat?.sid == id else { return }
            if streaming, let live = liveSid, live != id { detachLive() }
            openChat = d
            chatExtras.planMode = d.plan_mode ?? false
            chatExtras.prefs = d.prefs ?? [:]
            chatExtras.easyMode = d.easy_mode ?? false
            var fresh = d.messages
            // Mid-answer the Mac may not have written the question yet (it starts
            // the model server first). Keep the one we showed rather than losing it.
            if liveSid == id, streaming, let mine = messages.last, mine.isUser,
               fresh.last?.isUser != true {
                fresh.append(mine)
            }
            messages = withPendingNotes(fresh, sid: id)
            Cache.saveMessages(fresh, for: id)
            learnPlan(id, from: fresh)
            await loadModels()
            // already attached (SSE or poll) when it is the chat we are watching
            if d.running == true, liveSid != id, openChat?.sid == id { await rejoin(id) }
            watch(id, loaded: d.n)
            await loadQueue()
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Poll the Mac every few seconds while this chat is on screen. A change
    /// made from the Mac's own browser shows up here without leaving the chat;
    /// an answer started there is joined mid-stream.
    private func watch(_ id: String, loaded: Int?) {
        watchTask?.cancel()
        watchedCount = loaded
        watchTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                guard let self, !Task.isCancelled, self.openChat?.sid == id,
                      !self.backgrounded, let server = self.server else { continue }
                guard let s = try? await server.stamp(id), self.openChat?.sid == id else { continue }
                if self.streaming {
                    self.watchedCount = s.n                                  // our own turn moves it
                    // a stream silent for well over a long tool call while the Mac still answers
                    // has died without saying so: follow the answer by polling instead
                    if s.running, self.liveSid == id, self.streamTask != nil,
                       Date().timeIntervalSince(self.lastLiveEvent) > 75 {
                        await self.resyncLive()
                    }
                    // nothing is listening (a poll that gave up) yet the answer is marked live
                    if !s.running, self.liveSid == id, self.streamTask == nil, self.pollingSid != id {
                        self.finishLive(sid: id)
                    }
                    continue
                }
                if s.running, self.liveSid == nil {
                    await self.rejoin(id)                                   // someone else's turn
                } else if let seen = self.watchedCount, s.n != seen {
                    // changed elsewhere: read it without moving what the Mac has open
                    if let d = try? await server.peek(id) {
                        self.messages = self.withPendingNotes(d.messages, sid: id)
                        self.learnPlan(id, from: d.messages)
                        if let t = d.title { self.openChat?.title = t }
                        Cache.saveMessages(d.messages, for: id)
                    }
                    Task { await self.loadChatsIfChanged() }
                }
                // a waiting message may have gone out, or been added on the Mac
                if s.n != self.watchedCount || !(self.queue.items.isEmpty) { await self.loadQueue() }
                self.watchedCount = s.n
            }
        }
    }

    // ------------------------------------------------------------ sending

    func send(_ text: String, effort: String? = nil) async {
        guard let server, let sid = openChat?.sid,
              !(text.isEmpty && attachments.isEmpty) else { return }
        let going = attachments
        attachments = []
        let label = going.isEmpty ? text
            : ([text] + going.map { "📎 \($0.name)" })
                .filter { !$0.isEmpty }.joined(separator: "\n")
        messages.append(Message(role: "user", text: label))
        // each new request starts a fresh plan on the Mac; "continue" carries the old one on
        if !text.lowercased().hasPrefix("continue") { plans[sid] = nil }
        beginLive(for: sid)

        streamTask = Task {
            var dropped = false
            do {
                for try await ev in await server.send(sid: sid, message: text,
                                                      attachments: going.map(\.payload),
                                                      effort: effort) {
                    if Task.isCancelled { break }
                    // a chat you have since left keeps generating on the Mac;
                    // its tokens must not land in the one you are looking at
                    guard liveSid == sid else { break }
                    apply(ev)
                }
            } catch {
                if Task.isCancelled { return }       // handed over to polling, stopped, or left
                // A dropped connection is not a failed answer: the Mac carries on.
                // Rejoin through the live buffer rather than reporting an error.
                if liveSid == sid, (try? await server.live(sid).running) == true {
                    dropped = true
                } else if liveSid == sid {
                    lastError = error.localizedDescription
                    liveStatus = ""
                }
            }
            if Task.isCancelled { return }
            if dropped { await rejoin(sid) }
            else if liveSid == sid {
                let failed = lastError != nil
                finishLive(sid: sid)
                // whether the Mac kept the message is its call; ask rather than guess
                if failed { await open(sid) }
            }
        }
    }

    /// Which chat the live buffer belongs to. Events for any other chat are ignored.
    private(set) var liveSid: String?
    /// When the answer last showed a sign of life (a stream event or a poll), so a stream
    /// that hangs without failing -- a phone that slept, a network that changed -- is noticed.
    var lastLiveEvent = Date()

    /// Stop reading the stream and follow the answer by polling the Mac instead: for a
    /// stream that went quiet while the Mac still answers, and after coming back from the
    /// background, where the stream has usually died without saying so.
    func resyncLive() async {
        guard let server, streaming, let sid = liveSid else { return }
        // a stream that spoke moments ago is alive: leave it be (it carries what polling cannot --
        // sources, warnings, notices, alerts)
        if streamTask != nil, Date().timeIntervalSince(lastLiveEvent) < 10 { return }
        let running = (try? await server.liveDetail(sid).running) == true
        guard liveSid == sid, openChat?.sid == sid else { return }     // you moved on meanwhile
        streamTask?.cancel(); streamTask = nil
        guard running else {
            // it finished while we were not listening: show what it wrote
            finishLive(sid: sid)
            return
        }
        // start the polled view from what the Mac has saved, so steps the stream already
        // showed are not drawn twice
        flushText()
        liveSteps = []; liveText = ""; liveThinking = ""; liveRuns = []; liveTools = []
        if let d = try? await server.peek(sid), liveSid == sid, openChat?.sid == sid {
            messages = withPendingNotes(d.messages, sid: sid)
        }
        await rejoin(sid)
    }
    private var pendingText = ""
    private var flushTask: Task<Void, Never>?

    private func beginLive(for sid: String) {
        askForNotificationsIfUseful()
        // one listener per answer: an old stream or poll left over would draw into this one
        streamTask?.cancel(); pollTask?.cancel(); pollTask = nil
        lastLiveEvent = Date()
        liveSid = sid
        streaming = true
        flushTask?.cancel(); flushTask = nil
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        liveRuns = []; liveSteps = []
        startStatusLine()
        pendingText = ""
        liveModel = models.first { $0.id == currentModel }?.display ?? ""
        pendingApproval = nil
        chatExtras.question = nil; chatExtras.approval = nil; chatExtras.roundLimit = nil
    }

    /// Tokens arrive faster than a phone can re-render Markdown. Batch them and
    /// publish about twenty times a second — indistinguishable to the eye, and
    /// the parser runs 20 times a second instead of 200.
    private func queueText(_ t: String) {
        pendingText += t
        guard flushTask == nil else { return }
        flushTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 50_000_000)
            guard let self, !Task.isCancelled else { return }
            self.liveText += self.pendingText
            self.pendingText = ""
            self.liveStatus = ""
            self.flushTask = nil
        }
    }

    private func flushText() {
        flushTask?.cancel(); flushTask = nil
        if !pendingText.isEmpty { liveText += pendingText; pendingText = "" }
    }

    /// Change one tool call of the running answer, wherever it is shown now: among the
    /// calls still in progress, or in a step already finished.
    private func updateRun(_ id: String, _ change: (inout ToolRun) -> Void) {
        guard !id.isEmpty else { return }
        if let i = liveRuns.lastIndex(where: { $0.id == id }) {
            change(&liveRuns[i]); return
        }
        for si in liveSteps.indices.reversed() {
            if let ri = liveSteps[si].tool_runs?.lastIndex(where: { $0.id == id }) {
                change(&liveSteps[si].tool_runs![ri]); return
            }
        }
    }

    private func apply(_ ev: StreamEvent) {
        lastLiveEvent = Date()
        alert(for: ev)          // questions, approvals, errors: tell you if you are elsewhere
        switch ev {
        case .content(let t):
            nextStep()
            liveChars += t.count
            // words have begun: the thinking before them is over
            if let s = stepThinkStart, liveThoughtSecs == nil { liveThoughtSecs = Date().timeIntervalSince(s) }
            liveThinkingSince = nil
            queueText(t)
        case .thinking(let t):
            nextStep()
            liveChars += t.count
            if liveThinking.isEmpty { stepThinkStart = Date(); liveThoughtSecs = nil }
            if liveThinkingSince == nil { liveThinkingSince = Date() }
            liveThinking += t
        case .model(let m):    liveModel = m
        case .tool(let run):
            flushText()
            liveRuns.append(run)
        case .toolResult(let r, let diff):
            if let i = liveRuns.lastIndex(where: { $0.id == r.id && !$0.done })
                ?? liveRuns.lastIndex(where: { $0.name == r.name && !$0.done }) {
                liveRuns[i].complete(with: r)
            } else {
                liveRuns.append(r)          // an older Mac: a result with no call before it
            }
            if let sid = liveSid {
                if r.name == "plan", let out = r.output {
                    let steps = PlanStep.parse(out)
                    if !steps.isEmpty { plans[sid] = steps }
                }
                if let diff { shownDiffs[sid, default: []].append(diff) }
            }
        case .subagentStep(let parent, let step, let tools, let tokens, let description):
            // under the Agent row it belongs to, whether that call is still running or
            // (a background agent) has already come back
            updateRun(parent) { r in
                var sa = r.subagent ?? SubagentInfo()
                sa.description = description.isEmpty ? sa.description : description
                sa.steps.append(step)
                if sa.steps.count > 80 { sa.steps.removeFirst(sa.steps.count - 80) }
                sa.tools = max(tools, sa.tools)
                sa.tokens = max(tokens, sa.tokens)
                r.subagent = sa
            }
            liveStatus = (description.isEmpty ? "subagent" : description) + ": " + step.line
        case .subagentDone(let parent, let info):
            updateRun(parent) { r in
                var sa = info
                if sa.steps.isEmpty { sa.steps = r.subagent?.steps ?? [] }
                r.subagent = sa
                r.background = false
                if r.done { r.finish() }
            }
        case .status(let s):   liveStatus = s
        case .blocked(let r):  liveTools.append("refused: \(r)")
        case .autoApproved(let n, let r): liveTools.append("✓ auto-approved \(n) — \(r)")
        case .approval(let n, let r, let id):
            pendingApproval = (n, r, id ?? "")
        case .notice(let n):   liveTools.append("↪ " + n)
        case .question(let q): chatExtras.question = q
        case .approvalPrompt(let a):
            chatExtras.approval = a
            pendingApproval = (a.name, a.reason, a.id)
            // An approval is the thing that stops a run, and being stopped is exactly
            // what happens while you are somewhere else. Answer it from the Lock Screen.
            notifyApproval(a)
        case .roundLimit(let why): chatExtras.roundLimit = why
        case .usageLimit(let msg): noteUsageLimit(msg)
        case .error(let e):    lastError = e
        case .extra(let e):    applyExtra(e)
        case .end(_, let title):
            if let title, var c = openChat {
                c.title = title
                openChat = c
                if let i = chats.firstIndex(where: { $0.id == c.sid }) { chats[i].title = title }
            }
        }
    }

    /// A long answer finishing while you are in another app is exactly when you
    /// want to be told. iOS gives a backgrounded app a short grace period; we
    /// hold it open, keep reading the stream, and post a local notification when
    /// the answer lands. If iOS suspends us first the answer is still safe on
    /// the Mac — you just find it there instead of being tapped on the shoulder.
    /// An approval still waiting when you leave the app. It arrived while you were
    /// looking at it, so nothing announced it — and then you locked the phone and the
    /// run stayed blocked with nothing to say so.
    func announceWaitingApproval() {
        guard let a = chatExtras.approval else { return }
        postApproval(a)
    }

    /// The approval, with Allow and Deny on the notification itself.
    func notifyApproval(_ a: ApprovalPrompt) {
        guard let sid = liveSid ?? openChat?.sid else { return }
        pendingApprovalChat = sid
        guard backgrounded else { return }
        postApproval(a)
    }

    private func postApproval(_ a: ApprovalPrompt) {
        guard let sid = pendingApprovalChat ?? liveSid ?? openChat?.sid else { return }
        let c = UNMutableNotificationContent()
        // the chat that asked, which is not always the chat you have open
        let name = (openChat?.sid == sid ? openChat?.title : nil)
            ?? chats.first { $0.id == sid }?.title ?? "Orbit"
        c.title = name + " needs your approval"
        c.body = String((a.reason.isEmpty ? a.name : a.reason).prefix(240))
        c.sound = .default
        c.categoryIdentifier = Notifications.approvalCategory
        c.userInfo = ["sid": sid, "approvalID": a.id]
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: "approval-" + a.id, content: c, trigger: nil))
    }

    /// Answer an approval by its id alone — what a notification action has to go on.
    func answerApproval(id: String, allow: Bool) async {
        guard !id.isEmpty else { return }
        // A cold launch from the notification runs this before the pairing has built a
        // server, and the action was silently dropped: you believe you allowed it and
        // the run stays blocked. Wait a moment for one.
        for _ in 0..<40 where server == nil {
            try? await Task.sleep(for: .milliseconds(100))
        }
        guard let server else {
            toast("Couldn't reach the Mac to answer that")
            return
        }
        do {
            try await server.approve(id, reply: ApprovalReply(allow: allow))
            toast(allow ? "Allowed" : "Denied")
        } catch {
            toast("That approval had already been answered")
        }
        clearApproval(id)
    }

    /// The prompt is answered: take it off the screen and off the Lock Screen.
    func clearApproval(_ id: String) {
        if chatExtras.approval?.id == id { chatExtras.approval = nil }
        if pendingApproval?.id == id { pendingApproval = nil }
        let n = UNUserNotificationCenter.current()
        n.removeDeliveredNotifications(withIdentifiers: ["approval-" + id])
        n.removePendingNotificationRequests(withIdentifiers: ["approval-" + id])
    }

    func notifyIfBackgrounded(title: String, body: String, sid: String? = nil) {
        guard backgrounded else { return }
        let c = UNMutableNotificationContent()
        c.title = title
        c.body = String(body.prefix(240))
        c.sound = .default
        if let sid { c.userInfo = ["sid": sid] }     // tapping it opens that chat
        UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }

    /// Asked the first time an answer is actually generating — the only moment
    /// the permission means anything to you. Asking at launch is a prompt with
    /// no context attached, which is how you teach someone to tap Don't Allow.
    private static var askedForNotifications = false

    func askForNotificationsIfUseful() {
        guard !Self.askedForNotifications else { return }
        Self.askedForNotifications = true
        UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    // ------------------------------------------------------------ steps and the status line

    private static let statusVerbs = ["Working", "Pondering", "Brewing", "Churning", "Cooking", "Crunching",
        "Percolating", "Puzzling", "Simmering", "Spelunking", "Synthesising", "Tinkering", "Wrangling",
        "Orbiting", "Noodling", "Whirring", "Mulling", "Sifting", "Assembling", "Unravelling",
        "Untangling", "Composing"]

    private func startStatusLine() {
        liveStartedAt = Date()
        liveVerb = Self.statusVerbs.randomElement() ?? "Working"
        liveChars = 0
        liveThinkingSince = nil
        stepThinkStart = nil
        liveThoughtSecs = nil
    }

    /// The current step as a message: its words, its thinking, then the tools it called.
    private func currentStep() -> Message? {
        guard !liveText.isEmpty || !liveThinking.isEmpty || !liveRuns.isEmpty || !liveTools.isEmpty else { return nil }
        var m = Message(role: "assistant", text: liveText,
                        tools: liveTools.isEmpty ? nil : liveTools,
                        model: liveModel.isEmpty ? nil : liveModel,
                        thinking: liveThinking.isEmpty ? nil : liveThinking)
        m.tool_runs = liveRuns.isEmpty ? nil : liveRuns.map { r in
            var r = r
            r.markStopped()
            return r
        }
        m.thoughtSecs = liveThoughtSecs ?? stepThinkStart.map { Date().timeIntervalSince($0) }
        return m
    }

    /// New words or thinking after tool calls begin a new step, so each step's
    /// text sits with the tools it went on to call.
    private func nextStep() {
        guard !liveRuns.isEmpty || !liveTools.isEmpty else { return }
        flushText()
        if let step = currentStep() { liveSteps.append(step) }
        liveText = ""; liveThinking = ""; liveRuns = []; liveTools = []
        stepThinkStart = nil; liveThoughtSecs = nil
    }

    private func finishLive(sid: String) {
        flushText()
        // only the answer this screen is watching: finishing another chat's answer used to add
        // its steps to the chat on screen and cache them under the wrong chat
        guard liveSid == sid else { return }
        liveSid = nil
        let steps = liveSteps + [currentStep()].compactMap { $0 }
        if !steps.isEmpty {
            messages.append(contentsOf: steps)
            Cache.saveMessages(messages, for: sid)
        }
        let answered = steps.map(\.text).filter { !$0.isEmpty }.joined(separator: "\n\n")
        streaming = false
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        liveRuns = []; liveSteps = []; liveThinkingSince = nil; stepThinkStart = nil; liveThoughtSecs = nil
        chatExtras.question = nil; chatExtras.approval = nil; pendingApproval = nil
        if !answered.isEmpty {
            notifyIfBackgrounded(title: openChat?.title ?? "Orbit", body: answered, sid: sid)
        }
        // the Mac may have started the next queued message: draw it and follow its answer
        Task { await loadChats(); await reloadSaved(sid); await followQueue(after: sid) }
    }

    /// Reconnect to an answer already running on the Mac.
    func rejoin(_ sid: String) async {
        guard let server else { return }
        if !streaming { startStatusLine() }
        liveSid = sid
        streaming = true
        liveStatus = "picking up an answer already running"
        lastLiveEvent = Date()
        pollTask?.cancel()
        pollTask = Task {
            var step = -1                       // not seen yet; the Mac leaves "step" out for the first
            var misses = 0
            var gaveUp = false
            pollingSid = sid
            defer { if pollingSid == sid { pollingSid = nil } }
            while !Task.isCancelled, liveSid == sid {
                // one failed poll (a phone between networks) is not the end of the answer
                guard let s = try? await server.liveDetail(sid) else {
                    misses += 1
                    if misses >= 8 { gaveUp = true; break }
                    try? await Task.sleep(nanoseconds: 1_500_000_000)
                    continue
                }
                guard !Task.isCancelled, liveSid == sid else { break }
                misses = 0
                lastLiveEvent = Date()
                // The Mac keeps only the step being written. When it moves on,
                // the finished step is in the saved chat: read that again, or
                // its text would vanish from the screen until the answer ends.
                let n = s.step ?? 0
                if step >= 0, n != step, let d = try? await server.peek(sid), liveSid == sid {
                    messages = withPendingNotes(d.messages, sid: sid)
                }
                step = n
                await pickUpPrompts(sid)            // a question or approval raised elsewhere
                liveText = s.content
                liveThinking = s.thinking
                // the calls this step has made so far: without them a Claude Code answer
                // busy running tools looked frozen
                liveRuns = s.tools.map { ToolRun(event: $0, finished: $0["ok"] != nil && !($0["ok"] is NSNull)) }
                if s.content.isEmpty, !s.status.isEmpty { liveStatus = s.status }
                liveChars = max(liveChars, s.content.count + s.thinking.count)
                if s.content.isEmpty, !s.thinking.isEmpty {
                    if liveThinkingSince == nil { liveThinkingSince = Date() }
                } else {
                    liveThinkingSince = nil
                }
                if !s.content.isEmpty { liveStatus = "" }
                if !s.running {
                    finishLive(sid: sid)            // it reloads the saved chat and follows the queue
                    break
                }
                try? await Task.sleep(nanoseconds: 700_000_000)
            }
            // polling gave up (no network for a while): don't leave the chat stuck "answering" --
            // the watch loop joins the answer again if it is still running when the Mac answers
            if gaveUp, liveSid == sid { finishLive(sid: sid) }
        }
    }

    /// Send a note while an answer is running — it is read at the next step,
    /// and the answer carries on with it in mind. If the answer finished in the
    /// meantime, the note goes as an ordinary message instead of being lost.
    func steer(_ text: String) async {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let server, !t.isEmpty, let sid = liveSid ?? openChat?.sid else { return }
        messages.append(Message(role: "user", text: t, note: true))
        liveStatus = "note queued — it reads this at its next step"
        let taken = (try? await server.interject(sid: sid, message: t)) ?? false
        if !taken {
            if let i = messages.lastIndex(where: { $0.isUser && $0.text == t && $0.note == true }) {
                messages.remove(at: i)
            }
            for _ in 0..<40 where streaming { try? await Task.sleep(nanoseconds: 150_000_000) }
            if !streaming { await send(t) }
        }
    }

    func stopGenerating() async {
        guard let server, let sid = liveSid ?? openChat?.sid else { return }
        try? await server.stop(sid)
        streamTask?.cancel(); pollTask?.cancel()
        finishLive(sid: sid)
    }

    // ------------------------------------------------------------ projects

    @Published var projects: [ProjectInfo] = []

    func loadProjects() async {
        guard let server else { return }
        if let p = try? await server.projects() { projects = p }
    }

    func setDefaultModel(_ id: String) async {
        guard let server else { return }
        try? await server.setDefaultModel(id)
        defaultModel = id
        await loadModels()
    }

    // ------------------------------------------------------------ actions

    func newChat() async -> String? {
        guard let server else { return nil }
        // in the project the chat list shows (none from "All"), as the web starts one
        guard let sid = try? await server.newChat(project: composerExtras.projectFilter) else { return nil }
        openChat = ChatDetail(sid: sid, title: nil, messages: [])
        messages = []
        await loadChats()
        await loadModels()
        return sid
    }

    func choose(model: ModelInfo) async {
        guard let server, let sid = openChat?.sid else { return }
        try? await server.selectModel(model.id, for: sid)
        currentModel = model.id
    }

    func delete(_ id: String) async {
        guard let server else { return }
        try? await server.delete(id)
        forgetUnseen(id)
        if liveSid == id { detachLive() }
        chats.removeAll { $0.id == id }
        Cache.saveChats(chats)
        if openChat?.sid == id { openChat = nil; messages = [] }
    }

    func rename(_ id: String, to title: String) async {
        guard let server else { return }
        let clean = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }
        do {
            try await server.rename(id, to: clean)
            if let i = chats.firstIndex(where: { $0.id == id }) { chats[i].title = clean }
            if openChat?.sid == id { openChat?.title = clean }
            Cache.saveChats(chats)
        } catch { lastError = error.localizedDescription }
    }

    func setArchived(_ id: String, _ on: Bool) async {
        guard let server else { return }
        try? await server.setFlag(id, archived: on)
        if let i = chats.firstIndex(where: { $0.id == id }) { chats[i].archived = on }
        Cache.saveChats(chats)
        await loadChats()
    }

    /// A conversation as Markdown, for the share sheet.
    func markdown(for id: String) -> String {
        let title = chats.first { $0.id == id }?.displayTitle ?? "Chat"
        var out = ["# \(title)", ""]
        for m in messages {
            out.append(m.isUser ? "## You" : "## \(m.model ?? "Orbit")")
            out.append("")
            out.append(m.text)
            out.append("")
        }
        return out.joined(separator: "\n")
    }

    // ------------------------------------------------------------ queue

    /// The open chat's waiting messages: queued behind a running answer, or
    /// scheduled for later.
    @Published var queue: QueueState = .empty
    /// The context gauge, unseen news per chat, the chat list's project (AppState+Queue).
    @Published var composerExtras = ComposerExtras()

    func loadQueue() async {
        guard let server, let sid = openChat?.sid else { queue = .empty; return }
        if let q = try? await server.queue(sid: sid, op: "get"), openChat?.sid == sid { queue = q }
    }

    /// Send the draft (and anything attached) at a later time.
    func sendLater(_ text: String, at: Date, repeat rep: Repeat) async -> Bool {
        guard let server, let sid = openChat?.sid,
              !(text.isEmpty && attachments.isEmpty) else { return false }
        do {
            queue = try await server.sendLater(sid: sid, text: text,
                                               attachments: attachments.map(\.payload),
                                               at: at, repeat: rep)
            attachments = []
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    /// `now`, `remove`, `order` and friends on the open chat's queue.
    func queueOp(_ op: String, _ extra: [String: Any] = [:]) async {
        guard let server, let sid = openChat?.sid else { return }
        do {
            queue = try await server.queue(sid: sid, op: op, extra)
            // sending one now may have started an answer: pick it up
            if op == "now" {
                try? await Task.sleep(nanoseconds: 600_000_000)
                if !streaming, (try? await server.live(sid).running) == true { await rejoin(sid) }
            }
        } catch { lastError = error.localizedDescription }
    }

    func updateQueued(_ item: QueueItem, text: String?, at: Date??, repeat rep: Repeat?,
                      model: String?) async {
        guard let server, let sid = openChat?.sid else { return }
        do {
            try await server.updateQueued(sid: sid, id: item.id, text: text, at: at,
                                          repeat: rep, model: model)
        } catch { lastError = error.localizedDescription }
        await loadQueue()
    }

    /// Text the composer should pick up — set by "edit and resend".
    @Published var draftPrefill: String?

    /// A new chat with a workspace file already attached, opened in the Chats tab.
    func askAbout(file: RemoteFile) async {
        guard let sid = await newChat() else { return }
        attachments = [Attachment(name: file.name, kind: "file",
                                  payload: ["kind": "file", "name": file.name, "rel": file.rel])]
        draftPrefill = "About the attached file: "
        tab = "chats"
        deepLink = sid
    }

    private func userOrdinal(of message: Message) -> Int? {
        guard let i = messages.firstIndex(where: { $0.id == message.id }) else { return nil }
        return messages[..<i].filter(\.isUser).count
    }

    /// Remove this user message and everything after it on the Mac, then put its
    /// text back in the composer to be changed.
    func editAndResend(_ message: Message) async {
        guard let server, let sid = openChat?.sid, message.isUser,
              let ord = userOrdinal(of: message) else { return }
        forgetExtras(from: message)
        do {
            try await server.truncate(sid, atUserIndex: ord, check: message.text)
            await open(sid)
            draftPrefill = message.text
        } catch { lastError = error.localizedDescription }
    }

    /// Ask again from the last user message, discarding the answer it got.
    func regenerate() async {
        guard let last = messages.last(where: \.isUser) else { return }
        guard let server, let sid = openChat?.sid, let ord = userOrdinal(of: last) else { return }
        forgetExtras(from: last)
        do {
            try await server.truncate(sid, atUserIndex: ord, check: last.text)
            await open(sid)
            await send(last.text)
        } catch { lastError = error.localizedDescription }
    }

    /// Summarise the older turns of the open chat on the Mac and reload it.
    func compactCurrent() async {
        guard let server, let sid = openChat?.sid else { return }
        liveStatus = "compacting…"
        do {
            try await server.compact(sid)
            await open(sid)
            lastError = nil
        } catch { lastError = error.localizedDescription }
        liveStatus = ""
    }

    func setPinned(_ id: String, _ on: Bool) async {
        guard let server else { return }
        try? await server.setFlag(id, pinned: on)
        if let i = chats.firstIndex(where: { $0.id == id }) { chats[i].pinned = on }
        await loadChats()
    }

    func answer(approval allow: Bool) async {
        guard let server, let p = pendingApproval, !p.id.isEmpty else { return }
        try? await server.approve(p.id, allow: allow)
        pendingApproval = nil
    }
}

#if DEBUG
extension AppState {
    /// Drives the app from environment variables so the whole path — open a
    /// chat, send, stream, save — can be exercised without a human tapping.
    /// `ORBIT_OPEN_CHAT` is a chat id, `first`, or `new`.
    /// Compiled out of release builds.
    func runDebugScript() async {
        let env = ProcessInfo.processInfo.environment
        guard let want = env["ORBIT_OPEN_CHAT"] else { return }
        // "new" opens a fresh chat — its home page — the way the compose button does
        let sid = want == "new" ? await newChat() : want == "first" ? chats.first?.id : want
        guard let sid, !sid.isEmpty else { return }
        await open(sid)
        deepLink = sid
        if let text = env["ORBIT_SEND"], !text.isEmpty {
            await send(text)
        }
    }
}
#endif


// ------------------------------------------------------------------ attachments

/// A file already uploaded to the Mac and waiting to go with the next message.
struct Attachment: Identifiable, Hashable {
    let id = UUID()
    var name: String
    var kind: String                 // "image" or "file"
    var payload: [String: String]    // exactly what /api/chat expects back
    var thumbnail: UIImage? = nil

    static func == (a: Attachment, b: Attachment) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

extension AppState {
    func attach(photo item: PhotosPickerItem) async {
        do {
            guard let data = try await item.loadTransferable(type: Data.self),
                  let image = UIImage(data: data) else {
                lastError = "That photo couldn't be read."; return
            }
            await attach(image: image)
        } catch {
            lastError = "Couldn't attach that photo. \(error.localizedDescription)"
        }
    }

    /// A 12-megapixel HEIC is 4 MB the model will never look at closely. Send
    /// a 1600-pixel JPEG instead: quick over Tailscale, still plenty to read.
    func attach(image: UIImage) async {
        guard let server else { return }
        uploading = true
        defer { uploading = false }
        let small = image.downscaled(maxSide: 1600)
        guard let jpeg = small.jpegData(compressionQuality: 0.85) else { return }
        let name = "photo-\(Int(Date.now.timeIntervalSince1970)).jpg"
        do {
            let out = try await server.upload(data: jpeg, filename: name, mime: "image/jpeg")
            addAttachment(from: out, fallbackName: name, thumbnail: small.downscaled(maxSide: 120))
        } catch {
            lastError = "Couldn't upload that photo. \(error.localizedDescription)"
        }
    }

    func attach(fileAt url: URL) async {
        guard let server else { return }
        uploading = true
        defer { uploading = false }
        // a file from the Files app arrives security-scoped
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            let out = try await server.upload(data: data, filename: url.lastPathComponent,
                                              mime: "application/octet-stream")
            addAttachment(from: out, fallbackName: url.lastPathComponent)
        } catch {
            lastError = "Couldn't attach that file. \(error.localizedDescription)"
        }
    }

    private func addAttachment(from out: [String: Any], fallbackName: String,
                               thumbnail: UIImage? = nil) {
        let kind = (out["kind"] as? String) ?? "file"
        let name = (out["name"] as? String) ?? fallbackName
        var payload: [String: String] = ["kind": kind, "name": name]
        for key in ["path", "data_url", "url"] {
            if let v = out[key] as? String { payload[key] = v }
        }
        attachments.append(Attachment(name: name, kind: kind, payload: payload,
                                      thumbnail: thumbnail))
    }
}

// ------------------------------------------------------ background grace period

import UIKit

extension AppState {
    /// Ask iOS to keep us running a little longer so a streaming answer can land.
    /// Roughly 30 seconds; not a promise, which is why the Mac remains the one
    /// that actually holds the answer.
    func beginBackgroundGrace() {
        guard graceTask == .invalid else { return }
        graceTask = UIApplication.shared.beginBackgroundTask(withName: "orbit.answer") {
            [weak self] in self?.endBackgroundGrace()
        }
    }

    func endBackgroundGrace() {
        guard graceTask != .invalid else { return }
        UIApplication.shared.endBackgroundTask(graceTask)
        graceTask = .invalid
    }
}


extension UIImage {
    func downscaled(maxSide: CGFloat) -> UIImage {
        let longest = max(size.width, size.height)
        guard longest > maxSide else { return self }
        let scale = maxSide / longest
        let target = CGSize(width: size.width * scale, height: size.height * scale)
        return UIGraphicsImageRenderer(size: target).image { _ in
            draw(in: CGRect(origin: .zero, size: target))
        }
    }
}

// ------------------------------------------------------------- the local model

/// What the Mac's model server is doing, and the knobs to change it.
struct LocalServer: Equatable {
    var running = false
    var model: String?
    var memoryGB: Double?
    var installed: [String] = []          // model folders on the Mac
    var serving: String?                  // the folder currently configured
    var busy = false                      // a start/stop/switch in flight
    var note: String?                     // last message from the Mac
}

extension AppState {
    func refreshServer() async {
        guard let server else { return }
        if let st = try? await server.serverStatus() {
            localServer.running = st.running
            localServer.model = st.model
            localServer.memoryGB = st.memory_gb
        }
        await loadModels()
        do {
            let serving = models.first { $0.provider == "local" && $0.id.hasPrefix("local:") }
            localServer.serving = serving?.display
            localServer.installed = models
                .filter { $0.provider == "local" }
                .map { $0.id.hasPrefix("local-dir:") ? String($0.id.dropFirst("local-dir:".count))
                                                     : $0.display }
        }
    }

    func serverAction(_ action: OrbitServer.ServerAction) async {
        guard let server else { return }
        localServer.busy = true
        localServer.note = action == .stop ? "stopping…" : "loading weights — about 15 seconds"
        defer { localServer.busy = false }
        do {
            let msg = try await server.serverAction(action)
            localServer.note = msg
        } catch {
            localServer.note = error.localizedDescription
        }
        await refreshServer()
    }

    func switchLocalModel(_ folder: String) async {
        guard let server else { return }
        localServer.busy = true
        localServer.note = "switching to \(folder) — the server restarts"
        defer { localServer.busy = false }
        do {
            let msg = try await server.switchLocalModel(folder)
            localServer.note = msg
        } catch {
            localServer.note = error.localizedDescription
        }
        await refreshServer()
    }
}

// --------------------------------------------------------------------- backup

extension AppState {
    func refreshBackup() async {
        guard let server else { return }
        if let b = try? await server.backupStatus() { backup = b }
    }

    func backupNow() async {
        guard let server else { return }
        backupBusy = true
        defer { backupBusy = false }
        do { backupNote = "wrote \(try await server.backupNow())" }
        catch { backupNote = error.localizedDescription }
        await refreshBackup()
    }

    func setBackup(enabled: Bool) async {
        guard let server else { return }
        do { backup = try await server.setBackup(["enabled": enabled]) }
        catch { backupNote = error.localizedDescription }
    }

    func restoreMissing(from entry: BackupEntry) async {
        guard let server else { return }
        backupBusy = true
        defer { backupBusy = false }
        do {
            let n = try await server.restoreMissing(from: entry.name)
            backupNote = n == 0 ? "nothing was missing" : "put back \(n) file\(n == 1 ? "" : "s")"
            await loadChats()
        } catch { backupNote = error.localizedDescription }
    }
}

// --------------------------------------------------------------------- autonomy

extension AppState {
    func refreshAutonomy() async {
        guard let server else { return }
        if let a = try? await server.autonomy() { autonomy = a }
    }

    /// "ask" | "auto" | "full" — the confirm dialog for "full" lives in the view,
    /// since only it knows whether the person actually said yes.
    func setAutonomyMode(_ mode: String) async {
        guard let server else { return }
        autonomyBusy = true
        defer { autonomyBusy = false }
        do { autonomy = try await server.setAutonomy(["autonomy_mode": mode]) }
        catch { lastError = error.localizedDescription }
    }

    /// Sees the screen and drives the mouse/keyboard on the Mac — off by default,
    /// and separate from Full access on purpose. The confirm dialog lives in the view.
    func setComputerUse(_ on: Bool) async {
        guard let server else { return }
        autonomyBusy = true
        defer { autonomyBusy = false }
        do { autonomy = try await server.setAutonomy(["computer_use_enabled": on]) }
        catch { lastError = error.localizedDescription }
    }
}
