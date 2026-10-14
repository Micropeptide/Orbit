import SwiftUI
import UserNotifications

/// Owns the app's state and its notification handling from launch itself.
///
/// Both used to be set up in the first screen's `.task`. Allow or Deny on a notification
/// launches the app in the background with no screen at all, so that never ran: the
/// answer was dropped and the run stayed blocked. A tap that cold-launched the app could
/// also arrive before anyone was listening for it.
@MainActor
final class AppDelegate: NSObject, UIApplicationDelegate {
    let state = AppState()
    let router = NotificationRouter()

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        let state = self.state
        // tapping a notification opens its chat -- from whichever tab you were on
        router.open = { sid in state.tab = "chats"; state.deepLink = sid }
        // and an approval can be allowed or denied from the notification itself
        router.answer = { id, allow in await state.answerApproval(id: id, allow: allow) }
        // and replied to: a message into that chat, or an answer to its question
        router.reply = { sid, text in await state.replyFromNotification(sid: sid, text: text) }
        router.answerQuestion = { id, text in await state.answerFromNotification(questionID: id, text: text) }
        router.goalOffer = { sid, yes in await state.answerGoalOffer(sid: sid, accept: yes) }
        UNUserNotificationCenter.current().delegate = router
        Notifications.register()
        return true
    }
}

@main
struct OrbitApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @Environment(\.scenePhase) private var phase
    private var state: AppState { delegate.state }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(state)
                .onOpenURL { url in
                    state.handle(url: url)         // orbit://pair, chat/<id>, new?text=, a tab (Links.swift)
                }
                .task {
                    #if DEBUG
                    // Development only: pair without the camera or the system's
                    // "Open in Orbit?" prompt. Never compiled into a release.
                    if let u = ProcessInfo.processInfo.environment["ORBIT_PAIR_URL"],
                       let url = URL(string: u) { _ = state.pair(from: url, confirmed: true) }
                    #endif
                    await state.refreshEverything()
                    #if DEBUG
                    await state.runDebugScript()
                    #endif
                }
                .onChange(of: phase) { old, new in
                    state.backgrounded = (new != .active)
                    LiveClock.shared.awake(new == .active)
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
                        // A run waiting on an approval is blocked until you answer it,
                        // and you have just walked away from the phone. It is announced
                        // now rather than only when you were already elsewhere.
                        state.announceWaitingApproval()
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
    /// An answer that landed: reply to it from the notification.
    static let answerCategory = "orbit.answer"
    static let reply = "orbit.answer.reply"
    /// A question the answer is waiting on: answer it from the notification.
    static let questionCategory = "orbit.question"
    static let answerQuestion = "orbit.question.answer"
    /// An answer left work undone: keep going until it is done, or not.
    static let offerCategory = "orbit.goaloffer"
    static let offerAccept = "orbit.goaloffer.accept"
    static let offerDecline = "orbit.goaloffer.decline"

    /// Registered once at launch: an approval can be answered from the Lock Screen,
    /// which is where you are when a run stops to ask.
    static func register() {
        // Allow needs the phone unlocked: from the Lock Screen, anyone holding it could
        // otherwise approve a command, past Orbit's own Face ID lock. Deny needs nothing.
        let yes = UNNotificationAction(identifier: allow, title: "Allow once",
                                       options: [.authenticationRequired])
        let no = UNNotificationAction(identifier: deny, title: "Deny",
                                      options: [.destructive])
        // typing a reply needs the phone unlocked too: it sends work to the Mac
        let replyAction = UNTextInputNotificationAction(identifier: reply, title: "Reply",
                                                        options: [.authenticationRequired],
                                                        textInputButtonTitle: "Send",
                                                        textInputPlaceholder: "Message")
        let answerAction = UNTextInputNotificationAction(identifier: answerQuestion, title: "Answer",
                                                         options: [.authenticationRequired],
                                                         textInputButtonTitle: "Send",
                                                         textInputPlaceholder: "Your answer")
        UNUserNotificationCenter.current().setNotificationCategories([
            UNNotificationCategory(identifier: approvalCategory, actions: [yes, no],
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: answerCategory, actions: [replyAction],
                                   intentIdentifiers: [], options: []),
            UNNotificationCategory(identifier: questionCategory, actions: [answerAction],
                                   intentIdentifiers: [], options: []),
            // starting work on the Mac from the Lock Screen needs the phone unlocked
            UNNotificationCategory(identifier: offerCategory, actions: [
                UNNotificationAction(identifier: offerAccept, title: "Keep going until done",
                                     options: [.authenticationRequired]),
                UNNotificationAction(identifier: offerDecline, title: "No thanks", options: []),
            ], intentIdentifiers: [], options: []),
        ])
    }
}

/// Routes a tapped notification to the chat it announced, and answers an approval
/// from the notification's own buttons.
final class NotificationRouter: NSObject, UNUserNotificationCenterDelegate {
    var open: (@MainActor (String) -> Void)?
    /// (approval id, allow) — answered without opening the app.
    var answer: (@MainActor (String, Bool) async -> Void)?
    /// (chat id, text) — a reply typed on an "answer ready" notification.
    var reply: (@MainActor (String, String) async -> Void)?
    /// (question id, text) — an answer typed on a question's notification.
    var answerQuestion: (@MainActor (String, String) async -> Void)?
    /// (chat id, yes) — the offer to keep going, answered from its notification.
    var goalOffer: (@MainActor (String, Bool) async -> Void)?

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let approvalID = info["approvalID"] as? String ?? ""
        let action = response.actionIdentifier
        let sid = info["sid"] as? String
        let typed = (response as? UNTextInputNotificationResponse)?.userText ?? ""
        let questionID = info["questionID"] as? String ?? ""
        Task { @MainActor in
            switch action {
            // Done only once the answer has reached the Mac: called at once, iOS could
            // suspend the app before the request went out, and "Allow" did nothing.
            case Notifications.allow where !approvalID.isEmpty:
                await self.answer?(approvalID, true)
            case Notifications.deny where !approvalID.isEmpty:
                await self.answer?(approvalID, false)
            case Notifications.reply where sid != nil:
                await self.reply?(sid!, typed)
            case Notifications.answerQuestion where !questionID.isEmpty:
                await self.answerQuestion?(questionID, typed)
            case Notifications.offerAccept where sid != nil:
                await self.goalOffer?(sid!, true)
            case Notifications.offerDecline where sid != nil:
                await self.goalOffer?(sid!, false)
            default:
                if let sid { self.open?(sid) }
            }
            done()
        }
    }
}
