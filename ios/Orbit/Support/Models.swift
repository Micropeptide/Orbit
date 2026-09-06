import Foundation

/// The shapes Orbit's HTTP API speaks. Kept deliberately close to the JSON so
/// there is one obvious place to look when the server changes.

struct Pairing: Codable, Equatable {
    var url: String          // http://host:port, no trailing slash
    var token: String
    var name: String         // the Mac's name, for the UI

    var base: URL? { URL(string: url) }
}

struct ChatSummary: Identifiable, Codable, Hashable {
    let id: String
    var title: String?
    var n: Int
    var mtime: Double
    var pinned: Bool?
    var archived: Bool?
    var project: String?
    var tags: [String]?

    var displayTitle: String { (title?.isEmpty == false ? title! : "New chat") }
    var date: Date { Date(timeIntervalSince1970: mtime) }

    enum CodingKeys: String, CodingKey {
        case id, title, n, mtime, pinned, archived, project, tags
    }

    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        n = (try? c.decode(Int.self, forKey: .n)) ?? 0
        mtime = (try? c.decode(Double.self, forKey: .mtime)) ?? 0
        pinned = try? c.decode(Bool.self, forKey: .pinned)
        archived = try? c.decode(Bool.self, forKey: .archived)
        project = try? c.decode(String.self, forKey: .project)
        tags = try? c.decode([String].self, forKey: .tags)
    }
}

struct ChatList: Codable {
    var items: [ChatSummary]
    var total: Int?
}

/// One turn as the server stores it. `model` is the byline: which model wrote it.
struct Message: Identifiable, Codable, Hashable {
    var id = UUID()
    var role: String
    var text: String
    var images: [String]?
    var plots: [String]?
    var tools: [String]?
    var model: String?
    /// Reasoning, when the model exposes it. Not persisted server-side today.
    var thinking: String?

    var isUser: Bool { role == "user" }

    enum CodingKeys: String, CodingKey { case role, text, images, plots, tools, model }
}

struct ChatDetail: Codable {
    var sid: String
    var title: String?
    var messages: [Message]
    var running: Bool?
    var context: ContextState?
}

struct ContextState: Codable, Hashable {
    var used: Int
    var max: Int
    var pct: Double
    var basis: String?
}

struct ModelInfo: Identifiable, Codable, Hashable {
    var id: String
    var label: String?
    var model: String
    var provider: String
    var provider_label: String?
    var ready: Bool?
    var context: Int?
    var note: String?

    var display: String { label ?? model }
    var isReady: Bool { ready ?? true }
}

struct ModelList: Codable {
    var models: [ModelInfo]
    var current: String?
    var `default`: String?
}

struct ProjectInfo: Identifiable, Hashable {
    var id: String
    var name: String
    var color: String?
    var instructions: String?
}

/// Events the chat stream emits. One case per `k` the server sends.
enum StreamEvent {
    case model(String)               // which model is answering
    case thinking(String)            // reasoning delta
    case content(String)             // answer delta
    case tool(name: String, args: String)
    case toolResult(name: String, output: String)
    case status(String)              // cold start, compaction, trimming
    case blocked(reason: String)
    case approval(name: String, reason: String, id: String?)
    case error(String)
    case end(sid: String?, title: String?)
}


/// A hit from searching every conversation, not just their titles.
struct SearchHit: Identifiable, Codable, Hashable {
    var sid: String
    var title: String?
    var role: String
    var index: Int
    var snippet: String
    var mtime: Double

    var id: String { "\(sid)-\(index)" }
    var chatTitle: String { (title?.isEmpty == false ? title! : "New chat") }
}
