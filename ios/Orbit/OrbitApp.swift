import SwiftUI

@main
struct OrbitApp: App {
    @StateObject private var state = AppState()
    @Environment(\.scenePhase) private var phase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .onOpenURL { url in
                    _ = state.pair(from: url)      // orbit://pair?… from the QR
                }
                .task {
                    #if DEBUG
                    // Development only: pair without the camera or the system's
                    // "Open in Orbit?" prompt. Never compiled into a release.
                    if let u = ProcessInfo.processInfo.environment["ORBIT_PAIR_URL"],
                       let url = URL(string: u) { _ = state.pair(from: url) }
                    #endif
                    await state.refreshEverything()
                    #if DEBUG
                    await state.runDebugScript()
                    #endif
                }
                .onChange(of: phase) { _, new in
                    state.backgrounded = (new != .active)
                    switch new {
                    case .active:
                        // coming back from the lock screen should show the truth,
                        // not whatever was on screen twenty minutes ago
                        state.endBackgroundGrace()
                        Task { await state.refreshEverything() }
                    case .background:
                        // hold the app awake briefly so an answer in flight can
                        // finish and announce itself
                        if state.streaming { state.beginBackgroundGrace() }
                    default: break
                    }
                }

        }
    }
}
