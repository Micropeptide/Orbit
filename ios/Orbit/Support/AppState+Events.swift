import Foundation
import SwiftUI

/// What the newer stream events leave behind, kept outside `AppState` (an
/// extension cannot add stored properties) and observed only by the views that
/// draw it, so a hook firing does not redraw the whole chat.
@MainActor
final class TranscriptExtras: ObservableObject {
    static let shared = TranscriptExtras()

    /// sid -> turn (which of your messages it answers) -> what came with that answer.
    @Published private(set) var answers: [String: [Int: AnswerExtras]] = [:]
    /// sid -> note text -> "✓ read" or "kept — …", for notes sent mid-answer.
    @Published var notes: [String: [String: String]] = [:]
    /// sid -> plan steps still open when the answer stopped at its limit.
    @Published var roundPending: [String: [String]] = [:]

    /// This answer's extras, if they were collected for the same message.
    func extras(sid: String?, turn: Int, prompt: String) -> AnswerExtras? {
        guard let sid, let e = answers[sid]?[turn], e.prompt == prompt, !e.isEmpty else { return nil }
        return e
    }

    func update(sid: String, turn: Int, prompt: String, _ change: (inout AnswerExtras) -> Void) {
        var e = answers[sid]?[turn] ?? AnswerExtras(prompt: prompt)
        if e.prompt != prompt { e = AnswerExtras(prompt: prompt) }
        change(&e)
        answers[sid, default: [:]][turn] = e
    }

    func dismissSkillHint(sid: String, turn: Int) {
        answers[sid]?[turn]?.skillHint = nil
    }

    /// The answers from `turn` on are gone (rewound, retried, regenerated): what
    /// came with them must not turn up under the answers that replace them.
    func forget(sid: String, fromTurn turn: Int) {
        guard let kept = answers[sid] else { return }
        answers[sid] = kept.filter { $0.key < turn }
        notes[sid] = nil
        roundPending[sid] = nil
    }
}

extension Message {
    /// Pictures or phone-side files went with it, which "Retry from here" cannot
    /// send again: it only has the words. (A workspace file the Mac noted as
    /// "[attached file: …]" is in the words, so that one does go again.)
    var hasUnsendableAttachments: Bool {
        guard isUser else { return false }
        if !(images ?? []).isEmpty { return true }
        return text.split(separator: "\n").contains { $0.hasPrefix("📎 ") }
    }
}

extension AppState {

    /// Which turn a message of yours starts, counted as `liveTurn` counts them.
    func turnOrdinal(of message: Message) -> Int? {
        guard let i = messages.firstIndex(where: { $0.id == message.id }) else { return nil }
        return messages[..<i].filter { $0.isUser && $0.note != true }.count
    }

    /// Drop the extras of every answer from this message of yours on.
    func forgetExtras(from message: Message) {
        guard let sid = openChat?.sid, let t = turnOrdinal(of: message) else { return }
        TranscriptExtras.shared.forget(sid: sid, fromTurn: t)
    }

    /// The turn a live answer belongs to: your latest real message.
    private var liveTurn: (turn: Int, prompt: String) {
        var n = -1
        var prompt = ""
        for m in messages where m.isUser && m.note != true { n += 1; prompt = m.text }
        return (max(n, 0), prompt)
    }

    /// Take in one of the newer stream events.
    func applyExtra(_ e: TranscriptEvent) {
        guard let sid = liveSid ?? openChat?.sid else { return }
        let store = TranscriptExtras.shared
        let (turn, prompt) = liveTurn
        func note(_ change: (inout AnswerExtras) -> Void) {
            store.update(sid: sid, turn: turn, prompt: prompt, change)
        }
        switch e {
        case .sources(let hits):    note { $0.sources = hits }
        case .weakClaims(let c):    note { $0.weakClaims = c }
        case .injection(let name, let markers):
            note { $0.warnings.append("Possible prompt injection in \(name) output: " + markers.joined(separator: " | ")) }
        case .skillHint(let n):     note { $0.skillHint = n }
        case .longRunning(let mins, let rounds, let pending):
            let next = pending.isEmpty ? "" : " · next: " + pending.prefix(2).joined(separator: " · ")
            note { $0.longRunning = "still working — \(mins) min, \(rounds) steps so far\(next) · no action needed" }
        case .systemLine(let line): note { $0.lines.append(line) }
        case .retry(let line):
            liveStatus = line
            note { $0.retry = line }
        case .stagnation(let tool, let times):
            liveStatus = ""
            note { $0.warnings.append("repeated \(tool) \(times)× with the same arguments — nudged to change approach") }
        case .squeezed(let chars, let pct):
            liveStatus = "trimming older tool output"
            note { $0.lines.append("trimmed \(Int((Double(chars) / 1000).rounded()))k of old tool output — context now \(pct)%") }
        case .autocompactDone(let before, let after):
            liveStatus = ""
            note { $0.lines.append("compacted \(before) → \(after) messages") }
        case .hook(let msg):        note { $0.hooks.add(msg) }
        case .interjection(let text, let late):
            if !late { liveStatus = "reading your note" }
            store.notes[sid, default: [:]][text] = late ? "kept — it reads this with your next message" : "✓ read"
        case .roundLimit(let reason, let pending):
            chatExtras.roundLimit = reason
            store.roundPending[sid] = pending
        }
    }

    // ------------------------------------------------------------ the message box

    /// Quote some words into your reply.
    func quoteInDraft(_ text: String) {
        guard let sid = openChat?.sid else { return }
        let quoted = text.split(separator: "\n", omittingEmptySubsequences: false)
            .map { "> " + $0 }.joined(separator: "\n") + "\n\n"
        let current = Drafts.load(sid)
        draftPrefill = (current.isEmpty ? "" : current.hasSuffix("\n") ? current + "\n" : current + "\n\n") + quoted
    }

    // ------------------------------------------------------------ any message

    /// Ask again from one of your messages: the chat goes back to just before
    /// it on the Mac, and it is sent again.
    func retry(from message: Message) async {
        guard let server, let sid = openChat?.sid, !streaming, message.isUser,
              let index = userIndex(of: message) else { return }
        guard !message.hasUnsendableAttachments else {
            toast("Its attachments can't be sent again — attach them to a new message")
            return
        }
        let turn = turnOrdinal(of: message)
        do {
            _ = try await server.rewind(sid: sid, index: index, files: false)
            if let turn { TranscriptExtras.shared.forget(sid: sid, fromTurn: turn) }
            await open(sid)
            await send(message.text)
        } catch { lastError = error.localizedDescription }
    }

    // ------------------------------------------------------------ files in a chat

    /// Every existing file the open chat names, newest first.
    func chatFiles(sid: String) async -> [ResolvedPath] {
        var names: [String] = []
        for m in messages {
            names += FileLinks.names(in: m)
        }
        guard !names.isEmpty else { return [] }
        let found = await FileLinks.shared.resolveNow(sid: sid, names: names)
        var seen = Set<String>()
        var out: [ResolvedPath] = []
        for n in names {
            guard let f = found[n], f.exists, let p = f.path, !seen.contains(p) else { continue }
            seen.insert(p)
            out.append(f)
        }
        return out.sorted { ($0.mtime ?? 0) > ($1.mtime ?? 0) }
    }
}
