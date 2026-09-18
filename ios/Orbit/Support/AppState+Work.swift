import Foundation
import SwiftUI

/// The chat list's pages and other agents' sessions, `/tasks`, and starting a
/// chat from a "New chat with…" preset.
extension AppState {

    // ------------------------------------------------------------ the chat list

    /// The Mac scans other agents' sessions in the background, so one refresh
    /// can come back with a whole source missing. Keep the rows it had, once,
    /// rather than making a section vanish and reappear — as the Mac's list does.
    func keepingExternal(_ items: [ChatSummary]) -> [ChatSummary] {
        var out = items
        for src in ExternalSource.allCases {
            let had = chats.filter { $0.external == true && ExternalSource(chat: $0) == src }
            let got = items.contains { $0.external == true && ExternalSource(chat: $0) == src }
            if !got, !had.isEmpty, !Self.keptOnce.contains(src) {
                Self.keptOnce.insert(src)
                out += had
            } else if got {
                Self.keptOnce.remove(src)
            }
        }
        return out
    }

    /// Sources whose rows were kept through one refresh that lacked them.
    private static var keptOnce: Set<ExternalSource> = []

    /// More chats than the Mac has listed so far.
    var moreChatsOnMac: Int {
        guard let total = work.chatTotal else { return 0 }
        return max(0, total - chats.count)
    }

    func loadMoreChats() async {
        work.chatLimit += WorkExtras.page
        await loadChats()
    }

    // ------------------------------------------------------------ /tasks

    /// Show what is running in the background. For `/tasks` in the message box.
    func presentTasks() {
        work.showTasks = true
    }

    /// Stop an answer or a shell command, or remove a queued message.
    func stopBackground(_ t: BackgroundTask) async -> Bool {
        guard let server else { return false }
        do {
            try await server.stopBackground(t)
            Haptics.tap()
            if t.kind == .queued, let sid = t.sid, openChat?.sid == sid { await loadQueue() }
            await refreshRunningState()
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    // ------------------------------------------------------------ presets

    /// A new chat set up as the preset says. Its id, or nil (with `lastError`).
    func startChat(from p: ChatPreset) async -> String? {
        guard let sid = await newChat() else { return nil }
        let kind = HarnessKind(modelID: p.model)
        do {
            try await configureChat(sid, model: p.model.isEmpty ? nil : p.model, harness: kind,
                                    host: p.host, folder: p.cwd,
                                    mode: kind.isAgent ? p.permissionMode : nil)
            return sid
        } catch {
            lastError = error.localizedDescription
            // the chat exists; open it anyway so what was set can be fixed there
            return sid
        }
    }
}
