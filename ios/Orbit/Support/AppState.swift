import Foundation
import SwiftUI
import PhotosUI

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
    @Published var lastError: String?

    // content -------------------------------------------------------------
    @Published var chats: [ChatSummary] = []
    @Published var openChat: ChatDetail?
    @Published var messages: [Message] = []
    @Published var models: [ModelInfo] = []
    @Published var currentModel: String?
    @Published var runningChats: Set<String> = []
    /// Set to push a conversation onto the stack — used by deep links today and
    /// by notification taps later.
    @Published var deepLink: String?

    // what is going up with the next message
    @Published var attachments: [Attachment] = []
    @Published var uploading = false

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
        pairing = Pairing(url: base.hasSuffix("/") ? String(base.dropLast()) : base,
                          token: token, name: map["name"] ?? "Mac")
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
        streamTask?.cancel(); pollTask?.cancel()
        Keychain.clear()
        Cache.clear()
        pairing = nil
        chats = []; messages = []; openChat = nil; reachable = nil
    }

    // ------------------------------------------------------------ loading

    func refreshEverything() async {
        await checkReachable()
        guard reachable == true else { return }
        await loadChats()
        await loadModels()
    }

    func checkReachable() async {
        guard let server else { reachable = false; return }
        do {
            _ = try await server.health()
            reachable = true
            lastError = nil
        } catch {
            reachable = false
            lastError = error.localizedDescription
        }
    }

    func loadChats() async {
        guard let server else { return }
        do {
            let list = try await server.chats()
            chats = list
            Cache.saveChats(list)
            lastError = nil
        } catch {
            lastError = error.localizedDescription
            if chats.isEmpty { chats = Cache.loadChats() }   // offline: show what we have
        }
    }

    func loadModels() async {
        guard let server else { return }
        if let m = try? await server.models() {
            models = m.models
            currentModel = m.current ?? m.default
        }
    }

    func refreshRunning() async {
        guard let server else { return }
        if let r = try? await server.running() { runningChats = Set(r) }
    }

    func open(_ id: String) async {
        guard let server else { return }
        // show the cached copy immediately; the network fills it in
        if let cached = Cache.loadMessages(id), !cached.isEmpty {
            messages = cached
            openChat = ChatDetail(sid: id, title: chats.first { $0.id == id }?.title,
                                  messages: cached)
        }
        do {
            let d = try await server.chat(id)
            openChat = d
            messages = d.messages
            Cache.saveMessages(d.messages, for: id)
            await loadModels()
            if d.running == true { await rejoin(id) }
        } catch {
            lastError = error.localizedDescription
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
        beginLive()

        streamTask = Task {
            do {
                for try await ev in await server.send(sid: sid, message: text,
                                                      attachments: going.map(\.payload)) {
                    if Task.isCancelled { break }
                    apply(ev)
                }
            } catch {
                lastError = error.localizedDescription
                liveStatus = ""
            }
            finishLive(sid: sid)
        }
    }

    private func beginLive() {
        streaming = true
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        liveModel = models.first { $0.id == currentModel }?.display ?? ""
        pendingApproval = nil
    }

    private func apply(_ ev: StreamEvent) {
        switch ev {
        case .content(let t):  liveText += t; liveStatus = ""
        case .thinking(let t): liveThinking += t
        case .model(let m):    liveModel = m
        case .tool(let n, let a): liveTools.append(a.isEmpty ? n : "\(n)(\(a))")
        case .toolResult:      break
        case .status(let s):   liveStatus = s
        case .blocked(let r):  liveTools.append("refused: \(r)")
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

    private func finishLive(sid: String) {
        if !liveText.isEmpty || !liveThinking.isEmpty {
            messages.append(Message(role: "assistant", text: liveText,
                                    tools: liveTools.isEmpty ? nil : liveTools,
                                    model: liveModel.isEmpty ? nil : liveModel,
                                    thinking: liveThinking.isEmpty ? nil : liveThinking))
            Cache.saveMessages(messages, for: sid)
        }
        streaming = false
        liveText = ""; liveThinking = ""; liveTools = []; liveStatus = ""
        Task { await loadChats() }
    }

    /// Reconnect to an answer already running on the Mac.
    func rejoin(_ sid: String) async {
        guard let server else { return }
        streaming = true
        liveStatus = "picking up an answer already running"
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
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
        guard let server, let sid = openChat?.sid else { return }
        try? await server.stop(sid)
        streamTask?.cancel(); pollTask?.cancel()
        finishLive(sid: sid)
    }

    // ------------------------------------------------------------ actions

    func newChat() async -> String? {
        guard let server else { return nil }
        guard let sid = try? await server.newChat() else { return nil }
        openChat = ChatDetail(sid: sid, title: nil, messages: [])
        messages = []
        await loadChats()
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
        chats.removeAll { $0.id == id }
        Cache.saveChats(chats)
        if openChat?.sid == id { openChat = nil; messages = [] }
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
        guard let sid else { return }
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

    static func == (a: Attachment, b: Attachment) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }
}

extension AppState {
    func attach(photo item: PhotosPickerItem) async {
        guard let server else { return }
        uploading = true
        defer { uploading = false }
        do {
            guard let data = try await item.loadTransferable(type: Data.self) else { return }
            let name = "photo-\(Int(Date.now.timeIntervalSince1970)).jpg"
            let out = try await server.upload(data: data, filename: name, mime: "image/jpeg")
            addAttachment(from: out, fallbackName: name)
        } catch {
            lastError = "Couldn't attach that photo. \(error.localizedDescription)"
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

    private func addAttachment(from out: [String: Any], fallbackName: String) {
        let kind = (out["kind"] as? String) ?? "file"
        let name = (out["name"] as? String) ?? fallbackName
        var payload: [String: String] = ["kind": kind, "name": name]
        for key in ["path", "data_url", "url"] {
            if let v = out[key] as? String { payload[key] = v }
        }
        attachments.append(Attachment(name: name, kind: kind, payload: payload))
    }
}
