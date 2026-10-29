import Foundation
import SwiftUI

/// Shared projects: a folder the Mac's owner works in together with other people.
/// The Mac keeps all of it; this file is only what the phone needs to list them.
/// Opening one is a web page the Mac itself serves (`/shared/<id>/`), shown in
/// `SharedWebScreen`, so there is nothing here that re-implements the project.

struct SharedProject: Identifiable, Codable, Hashable {
    let id: String
    var name: String
    var members: Int
    var frozen: Bool
    var allowExport: Bool

    enum CodingKeys: String, CodingKey { case id, name, members, frozen, allowExport = "allow_export" }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decode(String.self, forKey: .name)) ?? "Shared project"
        members = (try? c.decode(Int.self, forKey: .members)) ?? 1
        frozen = (try? c.decode(Bool.self, forKey: .frozen)) ?? false
        allowExport = (try? c.decode(Bool.self, forKey: .allowExport)) ?? true
    }
}

struct SharedChat: Identifiable, Codable, Hashable {
    let id: String
    var name: String
    /// A chat shared from the owner's own chats rather than started in the project.
    var imported: Bool?

    var displayName: String { name.isEmpty ? id : name }
}

struct SharedPerson: Identifiable, Codable, Hashable {
    let id: String
    var name: String
    var role: String?
    var state: String?
}

/// What one project looks like right now: who is in it, who is here, its chats.
struct SharedDetail: Codable, Hashable {
    var me: String?
    var people: [SharedPerson] = []
    var online: [String] = []
    var chats: [SharedChat] = []
    var turnMode: String?
    var frozen: Bool = false
    /// Messages from other people (or the models) since this phone last had the project open.
    var unread: Int = 0
    /// More than we counted (a long project the phone had never opened).
    var unreadMore: Bool = false
    var lastActivity: Double?

    var onlineNames: [String] {
        let byID = Dictionary(people.map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
        return online.filter { $0 != me }.compactMap { byID[$0] }
    }
    var meOnline: Bool { me.map(online.contains) ?? false }
}

/// The server's whole answer about shared projects, kept so the tab opens to
/// something when the Mac is asleep.
struct SharedSnapshot: Codable {
    var enabled: Bool
    var running: Bool
    var projects: [SharedProject]
    var details: [String: SharedDetail]
    var saved: Double
}

/// What to show full screen: a project, optionally landing on one of its chats.
struct SharedTarget: Identifiable, Hashable {
    var project: SharedProject
    var chat: String?
    var id: String { project.id + "|" + (chat ?? "") }
}

struct SharedNote: Identifiable {
    let id = UUID()
    var title: String
    var message: String
    var project: SharedProject?
}

/// A chat the owner could add to a shared project, with what would be copied.
struct SharePlan: Identifiable {
    let id = UUID()
    var project: SharedProject
    var chatID: String
    var title: String
    var messages: Int
    var warnings: [String]
}

@MainActor
final class SharedStore: ObservableObject {
    enum Phase: Equatable {
        case idle
        case loading
        case failed(String)
        /// This phone is paired for chats only; the Mac refuses shared projects to it.
        case limited
    }

    /// nil until the Mac has answered once (or a saved answer was found).
    @Published private(set) var enabled: Bool?
    @Published private(set) var running = false
    @Published private(set) var projects: [SharedProject] = []
    @Published private(set) var details: [String: SharedDetail] = [:]
    @Published private(set) var phase: Phase = .idle
    @Published private(set) var lastRefresh: Date?
    /// Set when the answers shown came from the saved copy.
    @Published private(set) var stale = false

    var visible: Bool { enabled == true && !projects.isEmpty }
    var totalUnread: Int { details.values.reduce(0) { $0 + $1.unread } }

    /// A chat waiting for the owner to say yes to sharing it.
    @Published var plan: SharePlan?
    /// What happened to the last share, for an alert.
    @Published var note: SharedNote?

    private var refreshing = false

    init() {
        if let snap = Cache.loadShared() {
            enabled = snap.enabled; running = snap.running
            projects = snap.projects; details = snap.details
            lastRefresh = Date(timeIntervalSince1970: snap.saved)
            stale = true
        }
    }

    func detail(_ pid: String) -> SharedDetail { details[pid] ?? SharedDetail() }

    func clear() {
        enabled = nil; running = false; projects = []; details = [:]
        phase = .idle; lastRefresh = nil; stale = false
        Cache.clearShared()
    }

    // ------------------------------------------------------------ loading

    func refresh(using server: OrbitServer?, quiet: Bool = false) async {
        guard let server, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        if !quiet, projects.isEmpty { phase = .loading }
        do {
            let st = try await server.sharedStatus()
            enabled = st.enabled
            running = st.running
            projects = st.projects
            var fresh: [String: SharedDetail] = [:]
            // a few at a time; each is a handful of tiny requests
            try await withThrowingTaskGroup(of: (String, SharedDetail?).self) { group in
                for p in st.projects {
                    group.addTask { (p.id, try? await server.sharedDetail(p.id, seenSeq: SharedSeen.get(p.id))) }
                }
                for try await (pid, d) in group { if let d { fresh[pid] = d } }
            }
            // a project whose detail failed this time keeps its last known one
            for p in st.projects where fresh[p.id] == nil { fresh[p.id] = details[p.id] }
            details = fresh
            phase = .idle
            stale = false
            lastRefresh = .now
            Cache.saveShared(SharedSnapshot(enabled: st.enabled, running: st.running, projects: st.projects,
                                            details: fresh, saved: Date.now.timeIntervalSince1970))
        } catch OrbitServer.Failure.server(let code, _) where code == 403 {
            phase = .limited
        } catch OrbitServer.Failure.unauthorised {
            phase = .failed("This Mac no longer accepts the pairing — scan the QR again.")
        } catch {
            stale = !projects.isEmpty
            phase = projects.isEmpty ? .failed(error.localizedDescription) : .idle
        }
    }

    // ------------------------------------------------------------ sharing a chat

    /// Look at what sharing would put in front of everyone in the project, before anything is shared.
    func prepareShare(chat: String, into project: SharedProject, using server: OrbitServer?) async {
        guard let server else { return }
        do {
            let pv = try await server.sharePreview(project: project.id, chat: chat)
            let kinds = Array(Set((pv.warnings ?? []).compactMap(\.kind))).sorted()
            plan = SharePlan(project: project, chatID: chat, title: pv.title ?? "this chat",
                             messages: pv.messages ?? 0, warnings: kinds)
        } catch {
            Haptics.tap()
            note = SharedNote(title: "Couldn't look at that chat", message: error.localizedDescription)
        }
    }

    func confirmShare(using server: OrbitServer?) async {
        guard let server, let p = plan else { return }
        plan = nil
        do {
            let title = try await server.shareChat(project: p.project.id, chat: p.chatID,
                                                   confirmSecrets: !p.warnings.isEmpty)
            Haptics.success()
            note = SharedNote(title: "Added to \(p.project.name)",
                              message: "“\(title)” is now a chat in the project. Your own chat is unchanged; take the shared copy out again any time from the project's chat list.",
                              project: p.project)
            await refresh(using: server, quiet: true)
        } catch {
            note = SharedNote(title: "Couldn't share it", message: error.localizedDescription)
        }
    }

    /// The project was just open: everything up to now has been seen.
    func markSeen(_ pid: String, using server: OrbitServer?) async {
        guard let server else { return }
        if let latest = try? await server.sharedLatestSeq(pid) {
            SharedSeen.set(pid, latest)
            if var d = details[pid] { d.unread = 0; d.unreadMore = false; details[pid] = d }
        }
    }
}

/// The last event of each project this phone has looked at, so "new since you
/// were last in" can be counted. It lives on the phone only.
enum SharedSeen {
    private static func key(_ pid: String) -> String { "shared.seen." + pid }
    static func get(_ pid: String) -> Int? {
        UserDefaults.standard.object(forKey: key(pid)) as? Int
    }
    static func set(_ pid: String, _ seq: Int) { UserDefaults.standard.set(seq, forKey: key(pid)) }
    static func ts(_ pid: String) -> Double? { UserDefaults.standard.object(forKey: key(pid) + ".ts") as? Double }
    static func setTS(_ pid: String, _ ts: Double) { UserDefaults.standard.set(ts, forKey: key(pid) + ".ts") }
}
