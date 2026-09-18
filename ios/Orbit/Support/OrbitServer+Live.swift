import Foundation

extension OrbitServer {
    /// Everything the Mac holds about the step being written, for following an answer
    /// by polling: its text and thinking, the tool calls so far, and what it is doing.
    struct LiveDetail {
        var running: Bool
        var content: String
        var thinking: String
        var step: Int?
        var status: String
        var tools: [[String: Any]]
    }

    func liveDetail(_ sid: String) async throws -> LiveDetail {
        let data = try await fetchRaw("/api/live/\(sid)")
        let o = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        return LiveDetail(running: (o["running"] as? Bool) ?? false,
                          content: (o["content"] as? String) ?? "",
                          thinking: (o["thinking"] as? String) ?? "",
                          step: (o["step"] as? Int) ?? (o["step"] as? Double).map { Int($0) },
                          status: (o["status"] as? String) ?? "",
                          tools: (o["tools"] as? [[String: Any]]) ?? [])
    }
}
