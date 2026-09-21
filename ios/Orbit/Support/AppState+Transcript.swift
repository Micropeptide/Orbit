import SwiftUI

/// What Claude Code gives you over a transcript, on the shared state: go back
/// to an earlier message, run a `!` command, save a `#` line to memory, copy an
/// answer, and cycle the permission mode.
extension AppState {

    // ------------------------------------------------------------ rewind

    /// What rewinding with files would do to each of them, asked before doing it.
    func rewindPreview(toUserIndex index: Int) async -> OrbitServer.UndoPreview? {
        guard let server, let sid = openChat?.sid else { return nil }
        do { return try await server.rewindPreview(sid: sid, index: index) }
        catch { lastError = error.localizedDescription; return nil }
    }

    /// Put the open chat back to just before your `index`-th message, then reload it.
    /// Answers with what the Mac reported, so the caller can say what really happened.
    @discardableResult
    func rewind(toUserIndex index: Int, files: Bool, force: Bool = false)
        async -> OrbitServer.RewindResult? {
        guard let server, let sid = openChat?.sid, !streaming else { return nil }
        // the message it goes back to, found before the chat reloads without it
        let target = messages.filter(\.isUser).dropFirst(index).first
        do {
            let r = try await server.rewind(sid: sid, index: index, files: files, force: force)
            if let target { forgetExtras(from: target) }
            await open(sid)
            var note = "Rewound \(r.dropped) message\(r.dropped == 1 ? "" : "s")"
            if files {
                // a file you changed yourself since stops the restore: say that plainly
                // rather than counting the Mac's refusals as files put back
                note += " · \(r.restored.count) file\(r.restored.count == 1 ? "" : "s") put back"
                if !r.refused.isEmpty { note += " · \(r.refused.count) left alone (changed since)" }
            }
            toast(note)
            return r
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }

    // ------------------------------------------------------------ ! and #

    /// Run a command in this chat's folder; what it prints joins the conversation.
    func runBang(_ command: String, confirmed: Bool = false) async {
        let cmd = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let server, let sid = openChat?.sid, !cmd.isEmpty else {
            if openChat == nil { toast("Open a chat first") }
            return
        }
        var hold = Message(role: "user", text: "! " + cmd)
        hold.bang = BangRun(cmd: cmd, rc: 0, secs: nil, host: nil, out: "", running: true)
        messages.append(hold)
        defer { messages.removeAll { $0.id == hold.id } }
        do {
            switch try await server.bang(sid: sid, command: cmd, confirmed: confirmed) {
            case .confirm(let why):
                chatExtras.bangConfirm = BangConfirm(cmd: cmd, reason: why)
            case .ran(let run):
                guard openChat?.sid == sid else { return }
                var m = Message(role: "user", text: "! " + cmd)
                m.bang = run
                messages.append(m)
                Cache.saveMessages(messages.filter { $0.id != hold.id }, for: sid)
            }
        } catch {
            lastError = "Couldn't run that. \(error.localizedDescription)"
        }
    }

    /// A `# line`: saved to memory under its first few words, as the web names it.
    func rememberLine(_ text: String) async {
        guard let server else { return }
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        let words = body.lowercased().split(whereSeparator: \.isWhitespace).prefix(5).joined(separator: "-")
        let name = String(words.unicodeScalars.filter {
            ("a"..."z").contains($0) || ("0"..."9").contains($0) || $0 == "-"
        }.map(Character.init))
        do {
            let saved = try await server.saveMemory(name: name.isEmpty ? "note" : name, text: body)
            Haptics.success()
            toast("Saved to memory: \(saved)")
        } catch {
            lastError = "Couldn't save to memory. \(error.localizedDescription)"
        }
    }

    // ------------------------------------------------------------ /copy

    /// The last answer, or the `n`th from the end, as Markdown on the clipboard.
    func copyAnswer(_ n: Int) {
        let answers = messages.filter { !$0.isUser && !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        let n = max(1, n)
        guard answers.count >= n else { toast("No answer to copy"); return }
        UIPasteboard.general.string = answers[answers.count - n].text
        Haptics.success()
        toast(n > 1 ? "Copied the answer \(n) back" : "Copied the last answer")
    }

    // ------------------------------------------------------------ permission mode

    /// Claude Code's order, Codex's (which starts at auto), or plan mode on and
    /// off for Orbit's own chats.
    func cycleMode(work: ChatWork?) async -> PermissionMode? {
        guard let server, let sid = openChat?.sid else { return nil }
        guard let work, work.engine else {
            await setPlanMode(!chatExtras.planMode)
            return nil
        }
        let order: [PermissionMode] = work.codex ? [.auto, .acceptEdits, .plan, .ask] : [.ask, .acceptEdits, .plan, .auto]
        let next = order[((order.firstIndex(of: work.mode) ?? -1) + 1) % order.count]
        do {
            try await server.setPermissionMode(sid: sid, mode: next)
            chatExtras.workRevision += 1
            Haptics.tap()
            return next
        } catch {
            lastError = error.localizedDescription
            return nil
        }
    }
}
