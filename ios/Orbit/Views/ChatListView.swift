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
    @State private var project: String? = nil        // nil = all projects
    @State private var jump: SearchHit?
    @State private var newWith = false
    /// A file found by search, in QuickLook. Held here, on the list, so refreshing
    /// the search results does not close it.
    @State private var filePreview: URL?
    // filters, tags, projects, status (Views/Chat/ChatListExtras.swift)
    @State private var filter: ChatFilter = .active
    @State private var tagFilter: String? = nil
    @StateObject private var listModel = ChatListModel()
    @Environment(\.dynamicTypeSize) private var typeSize
    /// Which shared projects are folded in the list, remembered between launches.
    @AppStorage("shared.collapsed") private var collapsedRaw = ""
    private var collapsedShared: Set<String> {
        get { Set(collapsedRaw.split(separator: ",").map(String.init)) }
        nonmutating set { collapsedRaw = newValue.sorted().joined(separator: ",") }
    }

    /// A full hostname does not fit a phone title bar and says nothing
    /// useful past the first word.
    private var shortMacName: String {
        let raw = state.macDisplayName
        if raw == "your Mac" { return "Orbit" }
        if raw.contains(" ") { return raw }
        let first = raw.split(whereSeparator: { $0 == "-" || $0 == "." }).first.map(String.init)
        return (first?.isEmpty == false ? first! : raw)
    }

    /// Your chats. Sessions other agents began have sections of their own below them.
    private var shown: [ChatSummary] { ChatListSplit.mine(matching, running: state.runningChats) }

    /// Every chat that passes the filters, yours and other agents' alike.
    private var matching: [ChatSummary] {
        let base = state.chats.filter { passes($0) }
                              .filter { project == nil || $0.project == project }
                              .filter { tagFilter == nil || ($0.tags ?? []).contains(tagFilter!) }
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
                ChatStatusChips(chats: ChatListSplit.mine(state.chats, running: state.runningChats),
                                filter: $filter)
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
                    FileSearchSection(query: search, preview: $filePreview)
                    if showsShared {
                        ForEach(state.shared.projects) { p in sharedSection(p) }
                    }
                    ForEach(dayGroups, id: \.0) { day, chats in
                     Section {
                      ForEach(chats) { chat in listRow(chat) }
                     } header: {
                      // the header floats while its rows scroll (plain list style), so it
                      // may as well say how many are under it
                      HStack(spacing: 6) {
                       Text(day)
                       Text("\(chats.count)")
                        .font(.caption2.monospacedDigit())
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(.quaternary.opacity(0.5), in: .capsule)
                       Spacer(minLength: 0)
                      }
                     }
                    }
                    if shown.isEmpty { empty }
                    ChatPagingRow()
                    // conversations that began outside Orbit: each agent in its own section, folded until opened
                    ForEach(ChatListSplit.external(matching, running: state.runningChats), id: \.0) { src, rows in
                        ExternalChatSection(source: src, chats: rows,
                                            forceOpen: !search.trimmingCharacters(in: .whitespaces).isEmpty) {
                            listRow($0)
                        }
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .background(OrbitTheme.paper)
                .refreshable { await state.refreshEverything() }
                .quickLookPreview($filePreview)
            }
            .navigationTitle(shortMacName)
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $search, prompt: "Search chats and messages")
            .onChange(of: search) { _, q in runSearch(q) }
            // a new chat starts in the project you are looking at, as on the Mac
            .onChange(of: project, initial: true) { _, p in state.composerExtras.projectFilter = p }
            .navigationDestination(for: String.self) { ChatView(sid: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Menu {
                        Picker("Show", selection: $filter) {
                            ForEach(ChatFilter.allCases) { f in
                                Label(f.label, systemImage: f.icon).tag(f)
                            }
                        }
                        // the other agents' own tags are their sections already
                        let tags = Array(Set(state.chats.flatMap { $0.tags ?? [] }))
                            .filter { !["claude-qwen", "codex", "opencode"].contains($0) }.sorted()
                        if !tags.isEmpty {
                            Picker("Tag", selection: $tagFilter) {
                                Label("Any tag", systemImage: "tag").tag(String?.none)
                                ForEach(tags, id: \.self) { t in
                                    Label(t, systemImage: "tag.fill").tag(String?.some(t))
                                }
                            }
                        }
                        Divider()
                        Button { listModel.showProjects = true } label: {
                            Label("Projects…", systemImage: "folder.badge.gearshape")
                        }
                        Button { Task { await state.sortByRecent() } } label: {
                            Label("Sort by most recent", systemImage: "arrow.up.arrow.down")
                        }
                        Button { listModel.showStats = true } label: {
                            Label("Usage stats", systemImage: "chart.bar")
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
                        Image(systemName: (filter != .active || project != nil || tagFilter != nil)
                              ? "line.3.horizontal.decrease.circle.fill"
                              : "line.3.horizontal.decrease.circle")
                    }
                    .accessibilityLabel("Filter chats")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    // tap: a chat like the last one; hold: choose its harness, machine and folder
                    Menu {
                        Button {
                            Task { if let sid = await state.newChat() { goToChat = sid } }
                        } label: { Label("New chat", systemImage: "square.and.pencil") }
                        Button { newWith = true } label: {
                            Label("New chat with…", systemImage: "slider.horizontal.3")
                        }
                        Button { Task { await state.startTemporaryChat() } } label: {
                            Label("New temporary chat", systemImage: "flame")
                        }
                    } label: {
                        Image(systemName: "square.and.pencil")
                    } primaryAction: {
                        Task { if let sid = await state.newChat() { goToChat = sid } }
                    }
                    .keyboardShortcut("n", modifiers: .command)
                    .accessibilityLabel("New chat")
                    .accessibilityHint("Hold for New chat with…")
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
            .sheet(isPresented: $newWith) {
                NewChatSheet { sid in goToChat = sid }
            }
            .task {
                #if DEBUG
                if ProcessInfo.processInfo.environment["ORBIT_NEW_CHAT_WITH"] != nil { newWith = true }
                #endif
                await state.refreshRunning()
                Cache.prune(keeping: state.chats.map(\.id))
            }
            .task {
                // answering / waiting for you, kept current while the list is on screen
                while !Task.isCancelled {
                    await state.refreshRunningState()
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                }
            }
            .task {
                // A chat renamed, binned or started on the Mac shows up here without
                // pulling to refresh — and asking "has it changed?" costs one small
                // answer, rather than a page of JSON every ten seconds on cellular.
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 10_000_000_000)
                    if Task.isCancelled { break }
                    await state.loadChatsIfChanged()
                }
            }
            .task {
                // who is here and what is new in the shared projects, as the Shared tab keeps it
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 30_000_000_000)
                    if Task.isCancelled { break }
                    if state.reachable != false { await state.shared.refresh(using: state.server, quiet: true) }
                }
            }
            .onAppear { listModel.refreshSeen() }
            .modifier(ChatListHost(model: listModel))
        }
    }

    /// Shared projects sit above the day groups, except while the list is narrowed to something else.
    private var showsShared: Bool {
        state.shared.visible && search.trimmingCharacters(in: .whitespaces).isEmpty
            && project == nil && tagFilter == nil && (filter == .active || filter == .all)
    }

    /// The chats of a shared project, folded under its name, the way the web sidebar shows them.
    @ViewBuilder private func sharedSection(_ p: SharedProject) -> some View {
        let detail = state.shared.detail(p.id)
        let open = !collapsedShared.contains(p.id)
        Section {
            if open {
                Button {
                    Haptics.tap()
                    state.sharedTarget = SharedTarget(project: p, chat: nil)
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "arrow.up.forward.app").foregroundStyle(Color.accentColor).frame(width: 20)
                        Text("Open the project").foregroundStyle(Color.accentColor)
                        Spacer(minLength: 0)
                    }.font(.subheadline)
                }
                ForEach(detail.chats) { c in
                    Button {
                        Haptics.tap()
                        state.sharedTarget = SharedTarget(project: p, chat: c.id)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "number").foregroundStyle(.secondary).frame(width: 20)
                            Text(c.displayName).foregroundStyle(.primary).lineLimit(1)
                            Spacer(minLength: 0)
                        }
                    }
                }
            }
        } header: {
            Button {
                Haptics.tap()
                withAnimation(.snappy) {
                    if open { collapsedShared.insert(p.id) } else { collapsedShared.remove(p.id) }
                }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.right").font(.caption2.weight(.bold))
                        .rotationEffect(.degrees(open ? 90 : 0))
                    Text("Shared · \(p.name)").lineLimit(typeSize.isAccessibilitySize ? 3 : 1)
                    Spacer()
                    if detail.unread > 0 {
                        Text(detail.unreadMore ? "\(detail.unread)+" : "\(detail.unread)")
                            .font(.caption2.weight(.semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 6).padding(.vertical, 1)
                            .background(Color.accentColor, in: Capsule())
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Shared project \(p.name)\(detail.unread > 0 ? ", \(detail.unread) new" : "")")
            .accessibilityHint(open ? "Collapse" : "Expand")
            .accessibilityAddTraits(.isHeader)
        }
    }

    private func passes(_ c: ChatSummary) -> Bool {
        switch filter {
        case .active: return c.archived != true
        case .pinned: return c.pinned == true
        case .archived: return c.archived == true
        case .all: return true
        case .attention:
            return state.status(of: c, seen: listModel.seen).needsAttention
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

    /// A row with its swipe actions and menu — the same for your chats and other agents' sessions.
    private func listRow(_ chat: ChatSummary) -> some View {
        NavigationLink(value: chat.id) {
            row(chat)
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                Task { await state.binWithUndo(chat.id) }
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
            ChatRowMenu(chat: chat, model: listModel)
        }
    }

    private func row(_ chat: ChatSummary) -> some View {
        let status = state.status(of: chat, seen: listModel.seen)
        let unread = status == .unread
        return HStack(alignment: .top, spacing: 11) {
            // what the chat is doing, where a letter avatar used to say nothing at all
            RowMark(status: status)
                .frame(width: 16, height: 20)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text(chat.displayTitle).lineLimit(1)
                        .font(.body.weight(unread ? .semibold : .regular))
                        .italic(chat.external == true)
                    if chat.pinned == true {
                        Image(systemName: "pin.fill").font(.caption2).foregroundStyle(.secondary)
                    }
                    if let host = chat.host { ChatHostBadge(host: host) }
                    if let p = chat.parent {
                        Image(systemName: "arrow.turn.down.right").font(.caption2).foregroundStyle(.tint)
                            .accessibilityLabel("started by " + (p["title"] ?? "another chat"))
                    }
                    Spacer(minLength: 6)
                    Text(Self.when(chat.date))
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(unread ? AnyShapeStyle(.tint) : AnyShapeStyle(.secondary))
                }
                HStack(spacing: 8) {
                    Text(chat.n > 0 ? "\(chat.n) message\(chat.n == 1 ? "" : "s")" : "empty")
                        .font(.caption).foregroundStyle(.secondary)
                    ChatStatusBadge(status: status == .unread ? .none : status,
                                    since: state.runningSince[chat.id], goal: chat.goal,
                                    talkingTo: state.talking[chat.id], spinner: false)
                    if let tags = chat.tags, !tags.isEmpty {
                        ForEach(tags.prefix(2), id: \.self) { t in
                            Text(t).font(.caption2)
                                .padding(.horizontal, 6).padding(.vertical, 1)
                                .background(.quaternary.opacity(0.5), in: .capsule)
                        }
                    }
                }
                .lineLimit(1)
            }
        }
        .padding(.vertical, 4)
    }

    /// 17:26 today, Yesterday, Mon this week, 28 Sep before that -- as Messages does.
    static func when(_ d: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(d) { return d.formatted(date: .omitted, time: .shortened) }
        if cal.isDateInYesterday(d) { return "Yesterday" }
        if let days = cal.dateComponents([.day], from: d, to: .now).day, days < 7 {
            return d.formatted(.dateTime.weekday(.abbreviated))
        }
        let sameYear = cal.component(.year, from: d) == cal.component(.year, from: .now)
        return sameYear ? d.formatted(.dateTime.day().month(.abbreviated))
                        : d.formatted(.dateTime.day().month(.abbreviated).year(.twoDigits))
    }

    private var empty: some View {
        VStack(spacing: 8) {
            if state.chats.isEmpty, search.isEmpty, state.reachable == nil {
                // still asking the Mac: a spinner, not "No chats yet"
                ProgressView()
                Text("Connecting to \(state.macDisplayName)")
                    .font(.footnote).foregroundStyle(.secondary)
            } else if state.chats.isEmpty, search.isEmpty, state.reachable == false {
                Image(systemName: "wifi.slash")
                    .font(.largeTitle).foregroundStyle(.secondary)
                Text("Can't reach \(state.macDisplayName)")
                    .foregroundStyle(.secondary)
                Text("It may be asleep, or this phone may be off the tailnet.")
                    .font(.footnote).foregroundStyle(.tertiary).multilineTextAlignment(.center)
                Button("Try again") { Haptics.tap(); Task { await state.refreshEverything() } }
                    .buttonStyle(.bordered)
            } else {
                Image(systemName: "bubble.left.and.bubble.right")
                    .font(.largeTitle).foregroundStyle(.secondary)
                Text(search.isEmpty ? "No chats yet" : "Nothing matches “\(search)”")
                    .foregroundStyle(.secondary)
                if search.isEmpty {
                    Text("Tap the pencil to start one.")
                        .font(.footnote).foregroundStyle(.tertiary)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 50)
        .padding(.horizontal, 20)
        .listRowSeparator(.hidden)
    }
}
