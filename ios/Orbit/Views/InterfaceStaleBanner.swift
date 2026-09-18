import SwiftUI

/// Orbit's code on the Mac changed after the interface started: what runs is
/// out of date until it restarts. The web page shows the same banner; here it
/// sits under the connection banner, with the restart one tap away.
struct InterfaceStaleBanner: View {
    @EnvironmentObject var state: AppState
    @ObservedObject private var status = InterfaceStatus.shared

    var body: some View {
        // a stack even when empty, so the check below runs on every screen that shows it
        VStack(spacing: 0) {
            if state.reachable == true, let files = status.staleFiles, !status.dismissed {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                    VStack(alignment: .leading, spacing: 1) {
                        Text("Orbit on the Mac is out of date")
                            .font(.footnote.weight(.semibold))
                        Text(status.message ?? (files.isEmpty ? "Its code changed since it started."
                             : files.prefix(3).joined(separator: ", ") + " changed since it started."))
                            .font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                    }
                    Spacer()
                    if status.restarting {
                        ProgressView().controlSize(.mini)
                    } else {
                        Button("Restart") { Task { await status.restart(state.server) } }
                            .font(.caption.weight(.semibold))
                            .buttonStyle(.bordered)
                        Button { status.dismissed = true } label: { Image(systemName: "xmark") }
                            .font(.caption).buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("Hide")
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .background(.thinMaterial)
                .overlay(Divider(), alignment: .bottom)
            }
        }
        .task(id: state.reachable) { await status.check(state.server) }
    }
}

/// One check shared by every banner, at most every few minutes.
@MainActor
final class InterfaceStatus: ObservableObject {
    static let shared = InterfaceStatus()

    /// nil = current (or not known); otherwise the files that changed.
    @Published var staleFiles: [String]?
    @Published var message: String?
    @Published var restarting = false
    @Published var dismissed = false
    private var checkedAt: Date?

    func check(_ server: OrbitServer?, force: Bool = false) async {
        guard let server else { return }
        if !force, let at = checkedAt, Date().timeIntervalSince(at) < 300 { return }
        checkedAt = Date()
        guard let c = try? await server.codeStatus() else { return }
        staleFiles = c.stale == true ? (c.files ?? []) : nil
        if staleFiles == nil { message = nil; dismissed = false }
    }

    /// Restart the interface. The Mac waits for running answers first and says so.
    func restart(_ server: OrbitServer?) async {
        guard let server else { return }
        restarting = true
        defer { restarting = false }
        do {
            let r = try await server.restartInterface()
            message = r.message
            if r.deferred { return }
            // it comes straight back under launchd; look again once it has
            try? await Task.sleep(nanoseconds: 6_000_000_000)
            await check(server, force: true)
        } catch {
            message = error.localizedDescription
        }
    }
}
