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
                    // and an approval can be allowed or denied from the notification,
                    // without unlocking into the app at all
                    router.answer = { id, allow in
                        Task { await state.answerApproval(id: id, allow: allow) }
                    }
                    UNUserNotificationCenter.current().delegate = router
                    Notifications.register()
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
                .onChange(of: phase) { old, new in
                    state.backgrounded = (new != .active)
                    switch new {
                    case .active:
                        state.markOpenChatSeen()
                        // coming back from the lock screen should show the truth,
                        // not whatever was on screen twenty minutes ago
                        state.endBackgroundGrace()
                        // back from the background only (an alert, Control Center or Face ID passes
                        // through "inactive" and leaves the stream alive); coming back runs
                        // background -> inactive -> active, so remember the trip rather than `old`
                        let fromBackground = state.wentToBackground
                        state.wentToBackground = false
                        Task {
                            await state.refreshEverything()
                            if fromBackground { await state.resyncLive() }   // the stream rarely survives the lock screen
                        }
                    case .background:
                        state.wentToBackground = true
                        // hold the app awake briefly so an answer in flight can
                        // finish and announce itself
                        if state.streaming { state.beginBackgroundGrace() }
                    default: break
                    }
                }

        }
    }
}

/// The one place that says what a notification can carry and what its buttons do.
enum Notifications {
    static let approvalCategory = "orbit.approval"
    static let allow = "orbit.approval.allow"
    static let deny = "orbit.approval.deny"

    /// Registered once at launch: an approval can be answered from the Lock Screen,
    /// which is where you are when a run stops to ask.
    static func register() {
        let yes = UNNotificationAction(identifier: allow, title: "Allow once", options: [])
        let no = UNNotificationAction(identifier: deny, title: "Deny",
                                      options: [.destructive])
        UNUserNotificationCenter.current().setNotificationCategories([
            UNNotificationCategory(identifier: approvalCategory, actions: [yes, no],
                                   intentIdentifiers: [], options: [])
        ])
    }
}

/// Routes a tapped notification to the chat it announced, and answers an approval
/// from the notification's own buttons.
final class NotificationRouter: NSObject, UNUserNotificationCenterDelegate {
    var open: ((String) -> Void)?
    /// (approval id, allow) — answered without opening the app.
    var answer: ((String, Bool) -> Void)?

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let approvalID = info["approvalID"] as? String ?? ""
        switch response.actionIdentifier {
        case Notifications.allow where !approvalID.isEmpty:
            Task { @MainActor in self.answer?(approvalID, true) }
        case Notifications.deny where !approvalID.isEmpty:
            Task { @MainActor in self.answer?(approvalID, false) }
        default:
            if let sid = info["sid"] as? String {
                Task { @MainActor in self.open?(sid) }
            }
        }
        done()
    }
}
