import Foundation

/// Crew mode. Every call mirrors what the Mac's Crew page sends to `/api/crew`.
/// Starting, resuming and raising a limit make builder and reviewer chats work, which spends
/// tokens, so the screens ask first.
extension OrbitServer {
    private func crewCall(_ body: [String: Any], timeout: TimeInterval = 30) async throws -> JSONValue {
        let data = try await settingsCall("/api/crew", method: "POST", body: body, timeout: timeout)
        guard let v = try? JSONDecoder().decode(JSONValue.self, from: data) else { throw Failure.decoding("crew") }
        if let e = v.str("error") { throw Failure.server(400, e) }
        return v
    }

    func crewRuns() async throws -> [CrewRun] { CrewList(json: try await crewCall(["op": "list"])).runs }

    /// `pause`, `resume` or `stop` a run.
    func crewControl(_ op: String, id: String, extend: Bool = false) async throws {
        var body: [String: Any] = ["op": op, "id": id]
        if extend { body["extend"] = true }
        _ = try await crewCall(body)
    }

    /// A note the builder reads at its next step.
    func crewNote(id: String, text: String) async throws {
        _ = try await crewCall(["op": "note", "id": id, "text": text])
    }

    /// Raise or lower the limits (0 = none). A finished run starts again.
    func crewLimits(id: String, hours: Double, maxRounds: Int, maxTokens: Int) async throws {
        _ = try await crewCall(["op": "limits", "id": id, "hours": hours, "max_rounds": maxRounds, "max_tokens": maxTokens])
    }

    func crewDelete(id: String) async throws { _ = try await crewCall(["op": "delete", "id": id]) }

    /// Start a crew: a new builder chat on `builder`, a reviewer on `reviewer` (or none), working in `folder`
    /// (empty: a new folder the Mac makes for it).
    func crewStart(title: String, brief: String, folder: String, builder: String, reviewer: String,
                   hours: Double, maxRounds: Int) async throws {
        var body: [String: Any] = ["op": "start", "title": title, "brief": brief, "builders": [["model": builder]],
                                   "hours": hours, "max_rounds": maxRounds]
        if !folder.isEmpty { body["folder"] = folder }
        if !reviewer.isEmpty { body["reviewers"] = [["model": reviewer]] }
        _ = try await crewCall(body, timeout: 60)
    }
}
