import Foundation

/// A read-only copy of what the Mac holds, so the app opens to your chats
/// instead of a spinner when the Mac is asleep or you are off the tailnet.
///
/// Deliberately dumb: plain JSON files, last-write-wins, no merge logic. The Mac
/// is the source of truth; this never becomes a second database to reconcile.
enum Cache {
    private static var dir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask)[0]
            .appendingPathComponent("Orbit", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        // conversations are personal; keep them out of iCloud backups by default
        var url = base
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
        return base
    }()

    private static func file(_ name: String) -> URL {
        dir.appendingPathComponent(name)
    }

    // ------------------------------------------------------------ chat list

    static func saveChats(_ chats: [ChatSummary]) {
        write(chats, to: "chats.json")
    }

    static func loadChats() -> [ChatSummary] {
        read("chats.json", as: [ChatSummary].self) ?? []
    }

    // ------------------------------------------------------------ messages

    static func saveMessages(_ messages: [Message], for sid: String) {
        write(messages, to: "chat-\(safe(sid)).json")
    }

    static func loadMessages(_ sid: String) -> [Message]? {
        read("chat-\(safe(sid)).json", as: [Message].self)
    }

    /// Keep the on-disk copy from growing without bound: the most recent chats
    /// are the ones you open on a phone.
    static func prune(keeping ids: [String], limit: Int = 40) {
        let keep = Set(ids.prefix(limit).map { "chat-\(safe($0)).json" })
        let names = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        for n in names where n.hasPrefix("chat-") && !keep.contains(n) {
            try? FileManager.default.removeItem(at: file(n))
        }
    }

    static func clear() {
        try? FileManager.default.removeItem(at: dir)
    }

    // ------------------------------------------------------------ plumbing

    private static func safe(_ s: String) -> String {
        s.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "..", with: "_")
    }

    private static func write<T: Encodable>(_ value: T, to name: String) {
        guard let data = try? JSONEncoder().encode(value) else { return }
        try? data.write(to: file(name), options: .atomic)
    }

    private static func read<T: Decodable>(_ name: String, as: T.Type) -> T? {
        guard let data = try? Data(contentsOf: file(name)) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }
}
