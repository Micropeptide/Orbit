import Foundation
import SwiftUI

/// Chat actions and chat-list management on the shared state: answering a
/// question or approval, fork, regenerate, retry deeper, continue, undo file
/// changes, plan mode, temporary chats, tags, projects, bin with undo, row status.
extension AppState {

    // ------------------------------------------------------------ small helpers

    func toast(_ text: String) {
        chatExtras.toast = text
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_600_000_000)
            if self?.chatExtras.toast == text { self?.chatExtras.toast = nil }
        }
    }

    /// Ordinal among user messages, which is how the Mac counts for fork.
    func userIndex(of message: Message) -> Int? {
        guard let i = messages.firstIndex(where: { $0.id == message.id }) else { return nil }
        return messages[..<i].filter(\.isUser).count
    }

    /// Re-read the saved chat after an answer, so its time, tokens and file
    /// changes (which only the saved copy carries) show up.
    func reloadSaved(_ sid: String) async {
        guard let server, openChat?.sid == sid, !streaming else { return }
        guard let d = try? await server.peek(sid), openChat?.sid == sid, !streaming else { return }
        messages = d.messages
        Cache.saveMessages(d.messages, for: sid)
        learnPlan(sid, from: d.messages)
    }

    /// The todo list in force for a chat, read from its saved messages.
    func learnPlan(_ sid: String, from messages: [Message]) {
        let steps = PlanStep.current(in: messages)
        if plans[sid] != steps { plans[sid] = steps }
    }

    /// A question or approval waiting in the live buffer — raised while the
    /// answer was followed from another window, or before this app attached.
    func pickUpPrompts(_ sid: String) async {
        guard let server, let p = try? await server.livePrompts(sid), liveSid == sid else { return }
        if chatExtras.question?.id != p.question?.id { chatExtras.question = p.question }
        if chatExtras.approval?.id != p.approval?.id {
            chatExtras.approval = p.approval
            pendingApproval = p.approval.map { ($0.name, $0.reason, $0.id) }
        }
    }

    // ------------------------------------------------------------ mid-answer

    func answerQuestion(_ q: AskQuestion, with answer: [String]) async -> Bool {
        guard let server else { return false }
        do {
            try await server.answerQuestion(q.id, answer: answer, multiple: q.multiple)
            if chatExtras.question?.id == q.id { chatExtras.question = nil }
            return true
        } catch {
            if chatExtras.question?.id == q.id { chatExtras.question = nil }
            toast("Already answered — elsewhere, or it timed out")
            return false
        }
    }

    func answerApproval(_ a: ApprovalPrompt, _ reply: ApprovalReply) async {
        guard let server else { return }
        do {
            try await server.approve(a.id, reply: reply)
            toast(reply.allow ? "Allowed" : "Denied")
        } catch {
            toast("Already answered — elsewhere, or it timed out")
        }
        if chatExtras.approval?.id == a.id { chatExtras.approval = nil }
        if pendingApproval?.id == a.id { pendingApproval = nil }
    }

    // ------------------------------------------------------------ per message

    /// A new chat with everything before this message; its text waits in the
    /// new chat's composer to be changed and sent.
    func fork(from message: Message) async {
        guard let server, let sid = openChat?.sid, message.isUser,
              let idx = userIndex(of: message) else { return }
        do {
            let new = try await server.branch(sid, userIndex: idx)
            Drafts.save(new, message.text)
            await loadChats()
            deepLink = new
            toast("Forked — edit it and send")
        } catch { lastError = error.localizedDescription }
    }

    /// Ask the last question again; `deeper` asks with maximum reasoning effort.
    func regenerateLast(deeper: Bool = false) async {
        guard let server, let sid = openChat?.sid, !streaming else { return }
        do {
            if (try? await server.stamp(sid).running) == true {
                throw OrbitServer.Failure.server(409, "that chat is still answering")
            }
            let text = try await server.regenerateOnMac(sid: sid, deeper: deeper)
            if let last = messages.last(where: { $0.isUser && $0.note != true }) { forgetExtras(from: last) }
            if let i = messages.lastIndex(where: \.isUser) {
                messages.removeSubrange(i...)
            }
            await send(text, effort: deeper ? "xhigh" : nil)
        } catch { lastError = error.localizedDescription }
    }

    /// Carry on after an answer stopped at its limit.
    func continueAnswer() async {
        guard let server, openChat?.sid != nil, !streaming else { return }
        do {
            let text = try await server.continueMessage()
            chatExtras.roundLimit = nil
            await send(text)
        } catch { lastError = error.localizedDescription }
    }

    func undoChanges(of message: Message) async -> [String]? {
        guard let server, let sid = openChat?.sid, let t = message.t else { return nil }
        do {
            let done = try await server.undoChanges(sid: sid, t: t)
            await reloadSaved(sid)
            return done
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    func captureSkill(named name: String) async {
        guard let server, let sid = openChat?.sid else { return }
        toast("Capturing the procedure…")
        do {
            let saved = try await server.captureSkill(name: name, sid: sid)
            toast("Saved skill: \(saved)")
        } catch { lastError = "Couldn't save the skill. \(error.localizedDescription)" }
    }

    // ------------------------------------------------------------ chat level

    func setPlanMode(_ on: Bool) async {
        guard let server, let sid = openChat?.sid else { return }
        do {
            chatExtras.planMode = try await server.setPlanMode(sid: sid, on: on)
            openChat?.plan_mode = chatExtras.planMode
            toast(chatExtras.planMode ? "Plan mode: it reads and proposes, and changes nothing"
                                      : "Plan mode off: it may make changes")
        } catch { lastError = error.localizedDescription }
    }

    /// A chat that is never written to disk. Opens it.
    func startTemporaryChat() async {
        guard let server else { return }
        do {
            let sid = try await server.temporaryChat(on: true)
            chatExtras.tempSid = sid
            openChat = ChatDetail(sid: sid, title: "Temporary chat", messages: [])
            messages = []
            deepLink = sid
        } catch { lastError = error.localizedDescription }
    }

    /// Erase the temporary chat. True when the Mac erased it.
    func burnTemporaryChat() async -> Bool {
        guard let server, let sid = chatExtras.tempSid else { return false }
        do {
            try await server.burn(sid: sid)
            chatExtras.tempSid = nil
            forgetUnseen(sid)
            Drafts.save(sid, "")
            if openChat?.sid == sid { openChat = nil; messages = [] }
            await loadChats()
            toast("Erased")
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    // ------------------------------------------------------------ chat list

    func refreshRunningState() async {
        guard let server else { return }
        if let r = try? await server.runningState() {
            noteRunningState(running: r.running, waiting: r.waiting)
            runningChats = r.running
            chatExtras.waiting = r.waiting
        }
    }

    func status(of chat: ChatSummary, seen: [String: Double]) -> ChatRowStatus {
        if chatExtras.waiting.contains(chat.id) { return .waiting }
        if runningChats.contains(chat.id) { return .answering }
        if let q = chat.queued, q > 0 { return .queued(q) }
        if SeenChats.isUnread(chat, seen: seen) { return .unread }
        if let at = chat.scheduled, at > 0 { return .scheduled(at) }
        return .none
    }

    func setTags(_ id: String, _ tags: [String]) async {
        guard let server else { return }
        do {
            try await server.setTags(id, tags)
            if let i = chats.firstIndex(where: { $0.id == id }) { chats[i].tags = tags }
            await loadChats()
        } catch { lastError = error.localizedDescription }
    }

    func assign(_ id: String, project: String?) async {
        guard let server else { return }
        do {
            try await server.assign(id, project: project)
            if let i = chats.firstIndex(where: { $0.id == id }) { chats[i].project = project }
            await loadChats()
            toast(project == nil ? "Removed from its project"
                  : "Moved to \(projects.first { $0.id == project }?.name ?? "the project")")
        } catch { lastError = error.localizedDescription }
    }

    func sortByRecent() async {
        guard let server else { return }
        do {
            try await server.sortRecent()
            await loadChats()
            toast("Sorted by recent")
        } catch { lastError = error.localizedDescription }
    }

    /// Move to the bin, keeping what Undo needs for a few seconds.
    func binWithUndo(_ id: String) async {
        guard let server else { return }
        let title = chats.first { $0.id == id }?.displayTitle ?? "Chat"
        do {
            let item = try await server.bin(id)
            chats.removeAll { $0.id == id }
            Cache.saveChats(chats)
            if openChat?.sid == id { openChat = nil; messages = [] }
            if let item {
                chatExtras.binned = (id, item.name, title)
                Task { [weak self] in
                    try? await Task.sleep(nanoseconds: 7_000_000_000)
                    if self?.chatExtras.binned?.name == item.name { self?.chatExtras.binned = nil }
                }
            } else {
                toast("Moved to the bin")
            }
            await loadChats()
        } catch { lastError = error.localizedDescription }
    }

    func undoBin() async {
        guard let server, let b = chatExtras.binned else { return }
        chatExtras.binned = nil
        let ok = (try? await server.restore(name: b.name)) ?? false
        toast(ok ? "Restored “\(b.title)”" : "The Mac couldn't restore it")
        await loadChats()
    }
}
