import SwiftUI

/// Two panes on a wide screen. The sidebar is the same list; picking a chat
/// fills the detail rather than pushing a new screen.
struct SplitChats: View {
    @EnvironmentObject var state: AppState
    @State private var selected: String?
    @State private var newWith = false
    @StateObject private var listModel = ChatListModel()     // Views/Chat/ChatListExtras.swift

    var body: some View {
        NavigationSplitView {
            List(selection: $selected) {
                ForEach(ChatListSplit.mine(sorted, running: state.runningChats)) { row($0) }
                ChatPagingRow()
                // sessions other agents began, folded by agent (Views/Chat/ChatListExtras.swift)
                ForEach(ChatListSplit.external(sorted, running: state.runningChats), id: \.0) { src, rows in
                    ExternalChatSection(source: src, chats: rows) { row($0) }
                }
            }
            .navigationTitle("Chats")
            .refreshable { await state.refreshEverything() }
            .task {
                while !Task.isCancelled {
                    await state.refreshRunningState()
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                }
            }
            // a fork or a temporary chat opens in the detail pane
            .onChange(of: state.deepLink) { _, sid in
                guard let sid else { return }
                selected = sid
                state.deepLink = nil
            }
            .onChange(of: selected) { _, _ in listModel.refreshSeen() }
            .modifier(ChatListHost(model: listModel))
            .toolbar {
                ToolbarItem {
                    Button { newWith = true } label: { Image(systemName: "slider.horizontal.3") }
                        .accessibilityLabel("New chat with…")
                }
                ToolbarItem {
                    Button {
                        Task { selected = await state.newChat() }
                    } label: { Image(systemName: "square.and.pencil") }
                    .keyboardShortcut("n", modifiers: .command)
                    .accessibilityLabel("New chat")
                    .contextMenu {
                        Button { Task { await state.startTemporaryChat() } } label: {
                            Label("New temporary chat", systemImage: "flame")
                        }
                    }
                }
            }
            .sheet(isPresented: $newWith) {
                NewChatSheet { sid in selected = sid }
            }
            .task {
                #if DEBUG
                if ProcessInfo.processInfo.environment["ORBIT_NEW_CHAT_WITH"] != nil { newWith = true }
                #endif
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

    private func row(_ chat: ChatSummary) -> some View {
        NavigationLink(value: chat.id) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(chat.displayTitle).lineLimit(1).italic(chat.external == true)
                    if let host = chat.host { ChatHostBadge(host: host) }
                }
                Text("\(chat.n) messages").font(.caption2)
                    .foregroundStyle(.secondary)
                ChatStatusBadge(status: state.status(of: chat, seen: listModel.seen))
            }
        }
        .contextMenu { ChatRowMenu(chat: chat, model: listModel) }
    }

    private var sorted: [ChatSummary] {
        state.chats.filter { $0.archived != true }.sorted {
            if ($0.pinned ?? false) != ($1.pinned ?? false) { return $0.pinned ?? false }
            return $0.mtime > $1.mtime
        }
    }
}
