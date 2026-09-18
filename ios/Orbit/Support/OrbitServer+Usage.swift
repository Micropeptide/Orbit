import Foundation

/// Allowance, spend and cheaper hours: the calls behind the model picker's
/// figures. Reading only — nothing here changes the Mac.
extension OrbitServer {

    /// One provider's models as Codex reaches them, and whether that route is
    /// ready (`chatgpt` = the ChatGPT account Codex signs in with).
    func codexModels(provider: String) async throws -> CodexProviderModels {
        let data = try await settingsCall("/api/codex/models?provider=\(OrbitServer.escaped(provider))",
                                          timeout: 60)
        do { return try JSONDecoder().decode(CodexProviderModels.self, from: data) }
        catch { throw Failure.decoding("\(error)") }
    }

    /// Every provider's cheaper hours, with where each stands right now.
    func offpeak() async throws -> [OffpeakPolicy] {
        let data = try await settingsCall("/api/offpeak")
        do { return try JSONDecoder().decode(OffpeakList.self, from: data).policies }
        catch { throw Failure.decoding("\(error)") }
    }
}
