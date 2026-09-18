import Foundation
import SwiftUI
import UserNotifications

/// The message queue as the web runs it, on the shared state: a message sent while
/// an answer runs waits its turn; when an answer ends and the Mac starts the next
/// queued one, the phone draws that message and follows its answer. Also the
/// alerts for news in chats you are not looking at, the context gauge, and the
/// small actions behind the composer's extra commands.
extension AppState {

    // ------------------------------------------------------------ queue

    /// Whether a message from the box should wait in the queue rather than start:
    /// while the chat answers, and while messages are already waiting (paused after
    /// Stop, say) — a new one must not jump ahead of them.
    var sendingQueues: Bool {
        streaming || queue.items.contains { !$0.isScheduled }
    }

    /// Queue a message, with whatever is attached. True when the Mac took it.
    func enqueue(_ text: String) async -> Bool {
        guard let server, let sid = openChat?.sid,
              !(text.isEmpty && attachments.isEmpty) else { return false }
        let going = attachments
        attachments = []
        do {
            queue = try await server.enqueue(sid: sid, text: text, attachments: going.map(\.payload))
            toast(streaming ? "Queued — it starts when this answer is done · hold Send to steer instead"
                            : queuedNote(queue))
            // nothing was running: the Mac may start it straight away
            if !streaming {
                try? await Task.sleep(nanoseconds: 600_000_000)
                await followQueue(after: sid)
            }
            return true
        } catch {
            attachments = going
            lastError = error.localizedDescription
            return false
        }
    }

    private func queuedNote(_ q: QueueState) -> String {
        q.paused == true ? "Queued — the queue is paused after Stop; resume it to go on" : "Queued"
    }

    /// After an answer ends: the Mac may already have started the next queued
    /// message. Draw the message it took, then follow its answer.
    func followQueue(after sid: String) async {
        guard let server else { return }
        // The Mac frees the chat a moment before it starts the next message, so
        // "not running" straight after an answer ends is not the last word: while
        // messages still wait, look again for a few seconds.
        for attempt in 0..<7 {
            await loadQueue()
            if queue.running == true { break }
            guard attempt < 6, openChat?.sid == sid, !streaming, liveSid == nil,
                  queue.items.contains(where: { !$0.isScheduled && queue.paused != true }) else { return }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        guard queue.running == true, openChat?.sid == sid, !streaming, liveSid == nil else { return }
        guard let live = try? await server.liveUser(sid), live.running,
              openChat?.sid == sid, !streaming, liveSid == nil else { return }
        if let user = live.user, !user.isEmpty,
           !(messages.last?.isUser == true && messages.last?.text == user) {
            var m = Message(role: "user", text: user)
            m.t = Date.now.timeIntervalSince1970
            messages.append(m)
        }
        await rejoin(sid)
    }

    /// Send a waiting message now. While it answers, the message goes in as a note
    /// the answer reads at its next step; otherwise it starts, and is followed.
    func sendQueuedNow(_ item: QueueItem) async {
        guard let server, let sid = openChat?.sid else { return }
        do {
            let r = try await server.queueNow(sid: sid, id: item.id)
            queue = r.queue
            if r.interjected {
                messages.append(Message(role: "user", text: item.text, note: true))
                liveStatus = "sent in — it reads this at its next step"
            } else if !streaming {
                try? await Task.sleep(nanoseconds: 500_000_000)
                await followQueue(after: sid)
            }
        } catch { lastError = error.localizedDescription }
    }

    /// Resume a paused queue, and follow the answer it starts.
    func resumeQueue() async {
        guard let sid = openChat?.sid else { return }
        await queueOp("resume")
        try? await Task.sleep(nanoseconds: 600_000_000)
        await followQueue(after: sid)
    }

    /// Remove every queued message; scheduled ones stay.
    func clearQueued() async {
        guard let server, let sid = openChat?.sid else { return }
        for item in queue.items where !item.isScheduled {
            if let q = try? await server.queue(sid: sid, op: "remove", ["id": item.id]) { queue = q }
        }
        await loadQueue()
    }

    /// Move a queued message to where another one is; scheduled ones keep their
    /// place after the queued ones, as the web orders them.
    func moveQueued(_ id: String, before target: String?) async {
        let queued = queue.items.filter { !$0.isScheduled }.map(\.id)
        let scheduled = queue.items.filter(\.isScheduled).map(\.id)
        guard queued.contains(id), id != target else { return }
        var ids = queued.filter { $0 != id }
        if let target, let at = ids.firstIndex(of: target) { ids.insert(id, at: at) } else { ids.append(id) }
        guard ids != queued else { return }
        Haptics.tap()
        await queueOp("order", ["ids": ids + scheduled])
    }

    /// `/later <when> <message>`: the words after the time go out then.
    func sendLaterParsed(_ rest: String) async -> Bool {
        guard let p = LaterParser.parse(rest), !p.text.isEmpty else { return false }
        if await sendLater(p.text, at: p.at, repeat: p.rep) {
            toast("Scheduled — " + When.describe(p.at)
                  + (p.rep == .once ? "" : " · " + p.rep.label.lowercased()))
            await loadChats()
        }
        return true
    }

    // ------------------------------------------------------------ files into the message

    /// Attach a file already on the Mac: an image goes as its picture, anything else
    /// by its path. A file on another machine cannot travel; its path goes in the box.
    func attachExisting(_ info: ResolvedPath) async {
        guard let path = info.path else { return }
        if let host = info.host, !host.isEmpty {
            toast("That file is on \(host) — its path went in the box instead")
            insertInDraft(path)
            return
        }
        var payload = ["kind": "file", "name": info.displayName, "path": path]
        var kind = "file"
        var thumb: UIImage?
        if info.category == "image", let url = info.url, (info.size ?? 0) < 15_000_000, let server,
           let data = try? await server.fetchRaw(url), let image = UIImage(data: data) {
            let small = image.downscaled(maxSide: 1600)
            if let jpeg = small.jpegData(compressionQuality: 0.85) {
                payload = ["kind": "image", "name": info.displayName,
                           "data_url": "data:image/jpeg;base64," + jpeg.base64EncodedString()]
                kind = "image"
                thumb = small.downscaled(maxSide: 120)
            }
        }
        attachments.append(Attachment(name: info.displayName, kind: kind, payload: payload, thumbnail: thumb))
        toast("Attached \(info.displayName)")
    }

    /// Put text at the end of the open chat's draft, with a space before it.
    func insertInDraft(_ text: String) {
        guard let sid = openChat?.sid else { return }
        let current = Drafts.load(sid)
        let sep = current.isEmpty || current.hasSuffix(" ") || current.hasSuffix("\n") ? "" : " "
        draftPrefill = current + sep + text + " "
    }

    // ------------------------------------------------------------ context gauge

    /// Read the open chat's context window for the gauge by the composer.
    func refreshContextGauge() async {
        guard let server, let sid = openChat?.sid else { return }
        guard let s = try? await server.chatStatus(sid: sid), openChat?.sid == sid else { return }
        composerExtras.context = s.context
        composerExtras.contextSid = sid
        if let c = s.context, c.pct < 65 { composerExtras.contextWarned.remove(sid) }
    }

    // ------------------------------------------------------------ alerts

    /// An event in the answer being followed that you may want to be told about:
    /// a question, an approval, an error, a used-up plan allowance.
    func alert(for ev: StreamEvent) {
        guard let sid = liveSid else { return }
        switch ev {
        case .approvalPrompt(let a): raise("Needs your approval", body: a.name + (a.reason.isEmpty ? "" : " — " + a.reason), sid: sid)
        case .approval(let n, let r, _): raise("Needs your approval", body: n + (r.isEmpty ? "" : " — " + r), sid: sid)
        case .question(let q): raise("Orbit has a question", body: q.question, sid: sid)
        case .error(let e): raise("Error", body: e, sid: sid)
        case .notice(let n) where n.lowercased().contains("limit") && n.lowercased().contains("usage")
            || n.lowercased().contains("plan limit"):
            raise("Usage limit", body: n, sid: sid)
        default: break
        }
    }

    /// Tell you about news in a chat: a notification when the app is in the
    /// background, a toast when you are in another chat, nothing when you are
    /// looking at it. Only news you did not see counts toward the badge: while
    /// the app is away, or in a chat that is not on screen.
    func raise(_ kind: String, body: String, sid: String) {
        let looking = !backgrounded && openChat?.sid == sid
        guard !looking else { return }
        composerExtras.unseen[sid, default: 0] += 1
        let title = chats.first { $0.id == sid }?.displayTitle
        if backgrounded {
            let c = UNMutableNotificationContent()
            c.title = kind + (title.map { " — " + $0 } ?? "")
            c.body = String(body.prefix(240))
            if UserDefaults.standard.object(forKey: "orbit.sound") as? Bool ?? true { c.sound = .default }
            c.userInfo = ["sid": sid]
            c.threadIdentifier = "orbit-" + sid
            UNUserNotificationCenter.current().add(
                UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
        } else {
            toast(kind + (title.map { " — " + $0 } ?? ""))
        }
        syncBadge()
    }

    /// Opening a chat is looking at its news.
    func markSeen(_ sid: String) {
        guard composerExtras.unseen[sid] != nil else { return }
        composerExtras.unseen[sid] = nil
        syncBadge()
    }

    /// Coming back to the app with a chat on screen is looking at its news: what
    /// arrived there while the phone was locked no longer counts on the icon.
    /// Called when the app becomes active.
    func markOpenChatSeen() {
        guard let sid = openChat?.sid else { syncBadge(); return }
        if composerExtras.unseen[sid] != nil { markSeen(sid) } else { syncBadge() }
    }

    /// A chat that is gone has no news left to see: its count leaves the badge.
    func forgetUnseen(_ sid: String) {
        markSeen(sid)
        composerExtras.lastRunning?.remove(sid)
        composerExtras.lastWaiting?.remove(sid)
    }

    /// Unpairing: no counts, no badge, and nothing from the old Mac's poll.
    func resetComposerExtras() {
        composerExtras = ComposerExtras()
        syncBadge()
    }

    func unseenCount(for sid: String) -> Int { composerExtras.unseen[sid] ?? 0 }

    private func syncBadge() {
        UNUserNotificationCenter.current().setBadgeCount(composerExtras.unseenTotal) { _ in }
    }

    /// Chats other than the one on screen, from the running-state poll: one that
    /// starts waiting for you, or finishes answering, is announced.
    func noteRunningState(running: Set<String>, waiting: Set<String>) {
        defer {
            composerExtras.lastRunning = running
            composerExtras.lastWaiting = waiting
        }
        guard let before = composerExtras.lastRunning, let waitedBefore = composerExtras.lastWaiting else { return }
        let followed = liveSid
        for sid in waiting.subtracting(waitedBefore) where sid != followed {
            Task { [weak self] in
                guard let self, let server = self.server else { return }
                let p = try? await server.livePrompts(sid)
                let title = self.chats.first { $0.id == sid }?.displayTitle ?? "A chat"
                if let q = p?.question {
                    self.raise("Orbit has a question", body: q.question, sid: sid)
                } else if let a = p?.approval {
                    self.raise("Needs your approval",
                               body: a.name + (a.reason.isEmpty ? "" : " — " + a.reason), sid: sid)
                } else {
                    // the prompt could not be read: still say it is waiting, never an empty line
                    self.raise("Waiting for you", body: "\(title) is waiting for your answer", sid: sid)
                }
            }
        }
        // `raise` leaves out the chat you are looking at, and counts one finished while you were away
        for sid in before.subtracting(running) where sid != followed {
            raise("Answer ready", body: chats.first { $0.id == sid }?.displayTitle ?? "", sid: sid)
        }
    }
}
