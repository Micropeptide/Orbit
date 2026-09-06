import SwiftUI
import UserNotifications

@main
struct OrbitApp: App {
    @StateObject private var state = AppState()
    @Environment(\.scenePhase) private var phase
    @State private var router = NotificationRouter()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .onOpenURL { url in
                    _ = state.pair(from: url)      // orbit://pair?… from the QR
                }
                .task {
                    // tapping "answer ready" opens that chat
                    router.open = { sid in state.deepLink = sid }
                    UNUserNotificationCenter.current().delegate = router
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

/// Routes a tapped notification to the chat it announced.
final class NotificationRouter: NSObject, UNUserNotificationCenterDelegate {
    var open: ((String) -> Void)?

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        if let sid = response.notification.request.content.userInfo["sid"] as? String {
            Task { @MainActor in self.open?(sid) }
        }
        done()
    }
}
