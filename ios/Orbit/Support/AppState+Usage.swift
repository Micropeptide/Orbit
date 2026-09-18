import Foundation

/// Allowance and spend for the model picker, cheaper hours, and what happens
/// when a plan's limit stops an answer.
extension AppState {

    /// Read every provider's accounts and spend. A picker opening twice within
    /// a minute reuses the first answer; `force` is for an explicit refresh.
    func loadUsage(force: Bool = false) async {
        guard let server else { return }
        if !force, let at = usage.overviewAt, Date().timeIntervalSince(at) < 60 { return }
        guard let o = try? await server.harness() else { return }
        usage.overview = o
        usage.overviewAt = Date()
    }

    /// Whether each Codex route can answer — the ChatGPT sign-in above all,
    /// which the model list alone cannot tell apart from "no models".
    func loadCodexStatus(providers: [String]) async {
        guard let server else { return }
        for pid in providers where usage.codex[pid] == nil {
            if let r = try? await server.codexModels(provider: pid) { usage.codex[pid] = r }
        }
    }

    func loadOffpeak() async {
        guard let server, let list = try? await server.offpeak() else { return }
        usage.offpeak = list
    }

    /// Ask the provider for its current model list, then re-read everything
    /// the picker shows. Returns a line to tell the person how it went.
    func refreshProviderModels(_ pid: String) async -> String {
        guard let server else { return OrbitServer.Failure.notPaired.localizedDescription }
        usage.refreshing.insert(pid)
        defer { usage.refreshing.remove(pid) }
        do {
            let r = try await server.harnessRefresh(provider: pid)
            usage.codex[pid] = nil
            await loadUsage(force: true)
            await loadModels()
            let label = usage.provider(pid)?.label ?? pid
            return "\(label): \(r.count) models" + (r.note.map { " — \($0)" } ?? "")
        } catch {
            return error.localizedDescription
        }
    }

    /// The cheaper-hours state of the model the open chat uses, if it has any.
    var currentOffpeak: OffPeak? {
        models.first { $0.id == effectiveModelID }?.offpeak
    }

    /// `notice {kind:'limit'}`: a plan's allowance stopped this answer. A
    /// highlighted line in the answer, and a notification — if Orbit carries on
    /// by itself after the reset, that is hours away, when the phone is long
    /// in a pocket.
    func noteUsageLimit(_ msg: String) {
        liveTools.append("⏸ " + msg)
        notifyIfBackgrounded(title: "Usage limit", body: msg, sid: liveSid)
        // the account is used up now: the picker should say so next time it opens
        usage.overviewAt = nil
    }
}
