import SwiftUI

struct ChatListView: View {
    @EnvironmentObject var state: AppState
    @State private var search = ""
    @State private var goToChat: String?
    @State private var hits: [SearchHit] = []
    @State private var searching = false
    @State private var searchTask: Task<Void, Never>?
    @State private var renaming: ChatSummary?
    @State private var newTitle = ""
    @State private var showArchived = false
    @State private var project: String? = nil        // nil = all projects
    @State private var jump: SearchHit?

    /// A full hostname does not fit a phone title bar and says nothing
    /// useful past the first word.
    private var shortMacName: String {
        let raw = state.pairing?.name ?? "Orbit"
        let first = raw.split(whereSeparator: { $0 == "-" || $0 == "." }).first.map(String.init)
        return (first?.isEmpty == false ? first! : raw)
    }

    private var shown: [ChatSummary] {
        let base = state.chats.filter { showArchived ? $0.archived == true
                                                     : $0.archived != true }
                              .filter { project == nil || $0.project == project }
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        let matched = q.isEmpty ? base
            : base.filter { $0.displayTitle.lowercased().contains(q) }
        return matched.sorted {
            if ($0.pinned ?? false) != ($1.pinned ?? false) { return $0.pinned ?? false }
            return $0.mtime > $1.mtime
        }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ConnectionBanner()
                List {
                    // Titles match first and instantly; the server searches the
                    // text of every message a moment later.
                    if !hits.isEmpty {
                        Section("In messages") {
                            ForEach(hits) { hit in
                                Button { jump = hit } label: {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(hit.chatTitle)
                                            .font(.footnote.weight(.medium))
                                            .foregroundStyle(.secondary)
                                        Text(hit.snippet)
                                            .font(.callout).lineLimit(3)
                                            .foregroundStyle(.primary)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    if searching {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.mini)
                            Text("searching messages").font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    ForEach(dayGroups, id: \.0) { day, chats in
                     Section(day) {
                      ForEach(chats) { chat in
                        NavigationLink(value: chat.id) {
                            row(chat)
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task { await state.delete(chat.id) }
                            } label: { Label("Bin", systemImage: "trash") }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Task { await state.setPinned(chat.id, !(chat.pinned ?? false)) }
                            } label: {
                                Label(chat.pinned == true ? "Unpin" : "Pin",
                                      systemImage: chat.pinned == true ? "pin.slash" : "pin")
                            }
                            .tint(.orange)
                            Button {
                                Task { await state.setArchived(chat.id, !(chat.archived ?? false)) }
                            } label: {
                                Label(chat.archived == true ? "Unarchive" : "Archive",
                                      systemImage: "archivebox")
                            }
                            .tint(.gray)
                        }
                        .contextMenu {
                            Button {
                                newTitle = chat.displayTitle; renaming = chat
                            } label: { Label("Rename", systemImage: "pencil") }
                            Button {
                                Task { await state.setPinned(chat.id, !(chat.pinned ?? false)) }
                            } label: {
                                Label(chat.pinned == true ? "Unpin" : "Pin",
                                      systemImage: "pin")
                            }
                            Button {
                                Task { await state.setArchived(chat.id, !(chat.archived ?? false)) }
                            } label: {
                                Label(chat.archived == true ? "Unarchive" : "Archive",
                                      systemImage: "archivebox")
                            }
                            Divider()
                            Button(role: .destructive) {
                                Task { await state.delete(chat.id) }
                            } label: { Label("Move to bin", systemImage: "trash") }
                        }
                      }
                     }
                    }
                    if shown.isEmpty { empty }
                }
                .listStyle(.plain)
                .refreshable { await state.refreshEverything() }
            }
            .navigationTitle(shortMacName)
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $search, prompt: "Search chats and messages")
            .onChange(of: search) { _, q in runSearch(q) }
            .navigationDestination(for: String.self) { ChatView(sid: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Picker("Show", selection: $showArchived) {
                            Label("Active", systemImage: "tray").tag(false)
                            Label("Archived", systemImage: "archivebox").tag(true)
                        }
                        if !state.projects.isEmpty {
                            // projects are folders, in the Telegram sense
                            Picker("Project", selection: $project) {
                                Label("All projects", systemImage: "folder").tag(String?.none)
                                ForEach(state.projects) { p in
                                    Label(p.name, systemImage: "folder.fill").tag(String?.some(p.id))
                                }
                            }
                        }
                    } label: {
                        Image(systemName: (showArchived || project != nil)
                              ? "line.3.horizontal.decrease.circle.fill"
                              : "line.3.horizontal.decrease.circle")
                    }
                    .accessibilityLabel("Filter chats")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task {
                            if let sid = await state.newChat() { goToChat = sid }
                        }
                    } label: { Image(systemName: "square.and.pencil") }
                    .accessibilityLabel("New chat")
                }
            }
            .navigationDestination(item: $goToChat) { ChatView(sid: $0) }
            .navigationDestination(item: $state.deepLink) { ChatView(sid: $0) }
            .navigationDestination(item: $jump) { hit in
                ChatView(sid: hit.sid, highlight: hit.rowIndex)
            }
            .alert("Rename chat", isPresented: Binding(
                get: { renaming != nil },
                set: { if !$0 { renaming = nil } })) {
                TextField("Title", text: $newTitle)
                Button("Save") {
                    if let c = renaming { Task { await state.rename(c.id, to: newTitle) } }
                    renaming = nil
                }
                Button("Cancel", role: .cancel) { renaming = nil }
            }
            .task {
                await state.refreshRunning()
                Cache.prune(keeping: state.chats.map(\.id))
            }
        }
    }

    /// Debounced so a four-letter word does not fire four searches.
    private func runSearch(_ q: String) {
        searchTask?.cancel()
        let term = q.trimmingCharacters(in: .whitespaces)
        guard term.count >= 2 else { hits = []; searching = false; return }
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled, let server = state.server else { return }
            searching = true
            defer { searching = false }
            let found = (try? await server.search(term)) ?? []
            guard !Task.isCancelled else { return }
            hits = Array(found.prefix(25))
        }
    }

    /// Pinned first, then by day — the way a person looks for a conversation.
    private var dayGroups: [(String, [ChatSummary])] {
        let cal = Calendar.current
        func label(_ c: ChatSummary) -> String {
            if c.pinned == true { return "Pinned" }
            if cal.isDateInToday(c.date) { return "Today" }
            if cal.isDateInYesterday(c.date) { return "Yesterday" }
            if let week = cal.date(byAdding: .day, value: -7, to: .now), c.date > week {
                return "This week"
            }
            return "Earlier"
        }
        let order = ["Pinned": 0, "Today": 1, "Yesterday": 2, "This week": 3, "Earlier": 4]
        return Dictionary(grouping: shown, by: label)
            .sorted { (order[$0.key] ?? 9) < (order[$1.key] ?? 9) }
            .map { ($0.key, $0.value) }
    }

    private func row(_ chat: ChatSummary) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(avatarColor(chat.id).gradient)
                if state.runningChats.contains(chat.id) {
                    ProgressView().controlSize(.mini).tint(.white)
                } else {
                    Text(String(chat.displayTitle.prefix(1)).uppercased())
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.white)
                }
            }
            .frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text(chat.displayTitle).lineLimit(1).font(.body)
                    if chat.pinned == true {
                        Image(systemName: "pin.fill").font(.caption2).foregroundStyle(.orange)
                    }
                }
                Text(relative(chat.date) + (chat.n > 0 ? " · \(chat.n) messages" : " · empty"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 3)
    }

    /// A stable colour per chat, from its id — the same chat always gets the same one.
    private func avatarColor(_ id: String) -> Color {
        let palette: [Color] = [.blue, .indigo, .purple, .teal, .green, .orange, .pink, .cyan]
        let h = id.unicodeScalars.reduce(0) { ($0 &* 31) &+ Int($1.value) }
        return palette[abs(h) % palette.count]
    }

    private var empty: some View {
        VStack(spacing: 8) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.largeTitle).foregroundStyle(.secondary)
            Text(search.isEmpty ? "No chats yet" : "Nothing matches “\(search)”")
                .foregroundStyle(.secondary)
            if search.isEmpty {
                Text("Tap the pencil to start one.")
                    .font(.footnote).foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 50)
        .listRowSeparator(.hidden)
    }

    private func relative(_ d: Date) -> String {
        let seconds = Date.now.timeIntervalSince(d)
        if seconds < 60 { return "just now" }        // never "in 0s"
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .abbreviated
        return f.localizedString(for: d, relativeTo: .now)
    }
}
