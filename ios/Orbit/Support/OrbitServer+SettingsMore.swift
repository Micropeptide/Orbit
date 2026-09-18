import Foundation

/// The rest of the Mac's Settings the phone reaches: a full export and
/// restore, SSH machines' defaults, the pairing QR, the bin, and a project
/// saved with a folder that does not exist yet.
extension OrbitServer {

    private func object(_ data: Data) throws -> JSONValue {
        let v: JSONValue
        do { v = try JSONDecoder().decode(JSONValue.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
        if let e = v["error"]?.string, !e.isEmpty { throw Failure.server(400, e) }
        return v
    }

    // ------------------------------------------------------------ backup

    /// Archive Orbit's whole setup into the workspace. Returns its size and path on the Mac.
    func exportSetup() async throws -> (bytes: Int, path: String) {
        let v = try object(try await settingsCall("/api/backup", method: "POST", body: [:], timeout: 300))
        return (v["bytes"]?.int ?? 0, v["path"]?.string ?? "")
    }

    /// Restore an archive (a path on the Mac). Returns how many files came back.
    func importSetup(path: String) async throws -> Int {
        let v = try object(try await settingsCall("/api/restore", method: "POST", body: ["path": path],
                                                  timeout: 300))
        return v["restored"]?.int ?? 0
    }

    // ------------------------------------------------------------ machines over SSH

    /// The folder new chats on a host start in ("" = its home folder).
    func saveRemoteHost(_ host: String, defaultDir: String) async throws {
        _ = try object(try await settingsCall("/api/remote/save", method: "POST",
                                              body: ["host": host, "default_dir": defaultDir]))
    }

    // ------------------------------------------------------------ phone access

    /// The pairing QR as a PNG, or nil while the Mac has no address to put in it.
    func pairingQR() async throws -> Data? {
        do { return try await settingsCall("/api/remote/qr?ts=\(Int(Date().timeIntervalSince1970))") }
        catch Failure.server(let code, _) where code == 404 { return nil }
    }

    // ------------------------------------------------------------ bin

    /// Delete one binned item for good. Returns how many went (0 or 1).
    @discardableResult
    func purgeTrash(name: String) async throws -> Int {
        let v = try object(try await settingsCall("/api/trash/purge", method: "POST", body: ["name": name]))
        return v["purged"]?.int ?? 0
    }

    // ------------------------------------------------------------ projects

    /// Save a project and learn whether its folder exists on the Mac yet.
    func saveProjectNotingFolder(_ p: ProjectDetail) async throws -> (id: String, folderMissing: Bool) {
        let body: [String: Any] = [
            "id": p.id.isEmpty ? NSNull() : p.id, "name": p.name, "description": p.description,
            "instructions": p.instructions, "color": p.color, "folder": p.folder,
            "trust_tools": p.trustTools,
        ]
        let v = try object(try await settingsCall("/api/projects/save", method: "POST", body: body))
        return (v["id"]?.string ?? p.id, v["project"]?["folder_missing"]?.bool ?? false)
    }

    // ------------------------------------------------------------ interface

    /// Restart the interface, and whether the Mac put it off until answers finish.
    func restartInterface() async throws -> (deferred: Bool, message: String) {
        let v = try object(try await settingsCall("/api/restart_ui", method: "POST", body: [:]))
        return (v["deferred"]?.bool ?? false, v["msg"]?.string ?? "restarting the interface…")
    }
}
