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
    /// Whether the app is in the background, so a finished answer can announce itself.
    var backgrounded = false
    var graceTask: UIBackgroundTaskIdentifier = .invalid

    // the answer in flight --------------------------------------------------
    @Published var streaming = false
    @Published var liveText = ""
    @Published var liveThinking = ""
    @Published var liveTools: [String] = []
    @Published var liveStatus = ""
    @Published var liveModel = ""
    @Published var pendingApproval: (name: String, reason: String, id: String)?

    private(set) var server: OrbitServer?
    private var streamTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
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
        watchTask?.cancel(); watchTask = nil
        Keychain.clear()
        Cache.clear()
        pairing = nil
        chats = []; messages = []; openChat = nil; reachable = nil
        models = []; projects = []; attachments = []
        currentModel = nil; defaultModel = nil; deepLink = nil
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
        if list != (p.alts ?? []) { p.alts = list.isEmpty ? nil : list; pairing = p }
    }

    func loadChats() async {
        guard let server else { return }
        do {
            let list = try await server.chats()
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
        }
    }

    /// The last few conversations, fetched quietly so they open offline too.
    /// Reads through `peek`, which does not move what the Mac has open.
    private func prefetch(_ list: [ChatSummary]) async {
        guard let server else { return }
        for c in list.filter({ $0.archived != true }).prefix(8) {
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
        pendingApproval = nil
    }

    func open(_ id: String) async {
        guard let server, !id.isEmpty else { return }
        if streaming, liveSid != nil, liveSid != id {
            // leave the old answer running on the Mac; just stop watching it here
            detachLive()
        }
        // show the cached copy immediately; the network fills it in
        if let cached = Cache.loadMessages(id), !cached.isEmpty {
            messages = cached
            openChat = ChatDetail(sid: id, title: chats.first { $0.id == id }?.title,
                                  messages: cached)
        }
        do {
            let d = try await server.chat(id)
            openChat = d
            var fresh = d.messages
            // Mid-answer the Mac may not have written the question yet (it starts
            // the model server first). Keep the one we showed rather than losing it.
            if liveSid == id, streaming, let mine = messages.last, mine.isUser,
               fresh.last?.isUser != true {
                fresh.append(mine)
            }
            messages = fresh
            Cache.saveMessages(fresh, for: id)
            await loadModels()
            // already attached (SSE or poll) when it is the chat we are watching
            if d.running == true, liveSid != id { await rejoin(id) }
            watch(id, loaded: d.n)
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
                guard let s = try? await server.stamp(id) else { continue }
                if self.streaming { self.watchedCount = s.n; continue }   // our own turn moves it
                if s.running, self.liveSid == nil {
                    await self.rejoin(id)                                   // someone else's turn
                } else if let seen = self.watchedCount, s.n != seen {
                    // changed elsewhere: read it without moving what the Mac has open
                    if let d = try? await server.peek(id) {
                        self.messages = d.messages
                        if let t = d.title { self.openChat?.title = t }
                        Cache.saveMessages(d.messages, for: id)
                    }
                    Task { await self.loadChats() }
                }
                self.watchedCount = s.n
            }
        }
    }

    // ------------------------------------------------------------ sending

    func send(_ text: String) async {
        guard let server, let sid = openChat?.sid,
              !(text.isEmpty && attachments.isEmpty) else { return }
        let going = attachments
        attachments = []
        let label = going.isEmpty ? text
            : ([text] + going.map { "📎 \($0.name)" })
                .filter { !$0.isEmpty }.joined(separator: "\n")
        messages.append(Message(role: "user", text: label))
        beginLive(for: sid)

        streamTask = Task {
            var dropped = false
            do {
                for try await ev in await server.send(sid: sid, message: text,
                                                      attachments: going.map(\.payload)) {
                    if Task.isCancelled { break }
                    // a chat you have since left keeps generating on the Mac;
                    // its tokens must not land in the one you are looking at
                    guard liveSid == sid else { break }
                    apply(ev)
                }
            } catch {
                // A dropped connection is not a failed answer: the Mac carries on.
                // Rejoin through the live buffer rather than reporting an error.
                if liveSid == sid, (try? await server.live(sid).running) == true {
                    dropped = true
                } else if liveSid == sid {
                    lastError = error.localizedDescription
                    liveStatus = ""
                }
            }
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
    private var pendingText = ""
    private var flushTask: Task<Void, Never>?

    private func beginLive(for sid: String) {
        askForNotificationsIfUseful()
        liveSid = sid
        streaming = true
        flushTask?.cancel(); flushTask = nil
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        pendingText = ""
        liveModel = models.first { $0.id == currentModel }?.display ?? ""
        pendingApproval = nil
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

    private func apply(_ ev: StreamEvent) {
        switch ev {
        case .content(let t):  queueText(t)
        case .thinking(let t): liveThinking += t
        case .model(let m):    liveModel = m
        case .tool(let n, let a): liveTools.append(a.isEmpty ? n : "\(n)(\(a))")
        case .toolResult:      break
        case .status(let s):   liveStatus = s
        case .blocked(let r):  liveTools.append("refused: \(r)")
        case .autoApproved(let n, let r): liveTools.append("✓ auto-approved \(n) — \(r)")
        case .approval(let n, let r, let id):
            pendingApproval = (n, r, id ?? "")
        case .error(let e):    lastError = e
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
            .requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    private func finishLive(sid: String) {
        flushText()
        guard liveSid == sid || liveSid == nil else { return }
        liveSid = nil
        if !liveText.isEmpty || !liveThinking.isEmpty {
            messages.append(Message(role: "assistant", text: liveText,
                                    tools: liveTools.isEmpty ? nil : liveTools,
                                    model: liveModel.isEmpty ? nil : liveModel,
                                    thinking: liveThinking.isEmpty ? nil : liveThinking))
            Cache.saveMessages(messages, for: sid)
        }
        let answered = liveText
        streaming = false
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        if !answered.isEmpty {
            notifyIfBackgrounded(title: openChat?.title ?? "Orbit", body: answered, sid: sid)
        }
        Task { await loadChats() }
    }

    /// Reconnect to an answer already running on the Mac.
    func rejoin(_ sid: String) async {
        guard let server else { return }
        liveSid = sid
        streaming = true
        liveStatus = "picking up an answer already running"
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled, liveSid == sid {
                guard let s = try? await server.live(sid) else { break }
                liveText = s.content
                liveThinking = s.thinking
                if !s.content.isEmpty { liveStatus = "" }
                if !s.running {
                    finishLive(sid: sid)
                    await open(sid)
                    break
                }
                try? await Task.sleep(nanoseconds: 700_000_000)
            }
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
        guard let sid = try? await server.newChat() else { return nil }
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
    /// Compiled out of release builds.
    func runDebugScript() async {
        let env = ProcessInfo.processInfo.environment
        guard let want = env["ORBIT_OPEN_CHAT"] else { return }
        let sid = want == "first" ? chats.first?.id : want
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
}
