import SwiftUI

/// Two panes on a wide screen. The sidebar is the same list; picking a chat
/// fills the detail rather than pushing a new screen.
struct SplitChats: View {
    @EnvironmentObject var state: AppState
    @State private var selected: String?

    var body: some View {
        NavigationSplitView {
            List(sorted, selection: $selected) { chat in
                NavigationLink(value: chat.id) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(chat.displayTitle).lineLimit(1)
                        Text("\(chat.n) messages").font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Chats")
            .refreshable { await state.refreshEverything() }
            .toolbar {
                ToolbarItem {
                    Button {
                        Task { selected = await state.newChat() }
                    } label: { Image(systemName: "square.and.pencil") }
                }
            }
        } detail: {
            if let selected {
                ChatView(sid: selected)
            } else {
                ContentUnavailableView("Pick a conversation",
                                       systemImage: "bubble.left.and.bubble.right")
            }
        }
    }

    private var sorted: [ChatSummary] {
        state.chats.filter { $0.archived != true }.sorted {
            if ($0.pinned ?? false) != ($1.pinned ?? false) { return $0.pinned ?? false }
            return $0.mtime > $1.mtime
        }
    }
}
