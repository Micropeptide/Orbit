import Foundation

/// Files named in chats and kept in the workspace: finding a file by name,
/// paging, renaming, and the folder a chat works in.
extension OrbitServer {

    /// Which of these names are real files where the chat works, and that folder.
    func resolvePathsWithFolder(sid: String, _ names: [String]) async throws
        -> (cwd: String?, host: String?, items: [String: ResolvedPath]) {
        struct R: Codable { var cwd: String?; var host: String?; var items: [String: ResolvedPath]? }
        let data = try await post("/api/paths/resolve", ["sid": sid, "paths": names])
        let r = try? JSONDecoder().decode(R.self, from: data)
        return (r?.cwd, r?.host, r?.items ?? [:])
    }

    /// Files with this name anywhere the chat can see, for a path that does not exist.
    func findFiles(sid: String, name: String) async throws -> [ResolvedPath] {
        struct R: Codable { var items: [ResolvedPath]? }
        var req = try authorisedRequest("/api/file/find", method: "POST", body: ["sid": sid, "name": name])
        req.timeoutInterval = 60           // a search of the disk takes a moment
        let data = try await perform(req)
        return (try? JSONDecoder().decode(R.self, from: data))?.items ?? []
    }

    /// One page of the Files list, with how many there are in all.
    func filesPage(offset: Int, limit: Int) async throws -> FilesPage {
        struct F: Codable { var items: [RemoteFile]; var total: Int? }
        let r = try await get("/api/files?offset=\(offset)&limit=\(limit)", as: F.self)
        return FilesPage(items: r.items, total: r.total ?? (offset + r.items.count))
    }

    /// Rename a workspace file in its own folder. The Mac refuses a clash or a path outside.
    func renameFile(rel: String, to name: String) async throws {
        struct R: Codable { var ok: Bool? }
        let data = try await post("/api/files/rename", ["rel": rel, "name": name])
        guard (try? JSONDecoder().decode(R.self, from: data))?.ok == true else {
            throw Failure.server(400, "the Mac could not rename it — is that name taken?")
        }
    }

    /// Bytes of a workspace file, for copying its contents or a typed preview.
    func workspaceBytes(rel: String) async throws -> Data {
        let escaped = rel.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? rel
        return try await fetchRaw("/api/ws/\(escaped)")
    }
}
