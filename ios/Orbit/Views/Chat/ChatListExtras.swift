import SwiftUI

/// What the chat list presents: tags, projects, rename, export. One per list.
@MainActor
final class ChatListModel: ObservableObject {
    @Published var tagging: ChatSummary?
    @Published var showProjects = false
    @Published var showStats = false
    @Published var renaming: ChatSummary?
    @Published var newTitle = ""
    @Published var exportURL: URL?
    @Published var seen: [String: Double] = SeenChats.all()

    func refreshSeen() { seen = SeenChats.all() }
}

// ------------------------------------------------------------------ other agents, status, paging

/// Your chats, and the sessions other agents began. Those go in their own
/// sections — unless one of your chats that runs through such an agent is
/// answering right now, which keeps it in your list.
enum ChatListSplit {
    static func mine(_ chats: [ChatSummary], running: Set<String>) -> [ChatSummary] {
        chats.filter { ExternalSource(chat: $0) == nil || ($0.external != true && running.contains($0.id)) }
    }

    static func external(_ chats: [ChatSummary], running: Set<String>) -> [(ExternalSource, [ChatSummary])] {
        let mineIDs = Set(mine(chats, running: running).map(\.id))
        return ExternalSource.allCases.compactMap { src in
            let rows = chats.filter { !mineIDs.contains($0.id) && ExternalSource(chat: $0) == src }
            return rows.isEmpty ? nil : (src, rows)
        }
    }
}

/// Which "From Claude Code / Codex / OpenCode" sections are open. Folded until
/// you open one, and remembered.
enum ExternalSectionsOpen {
    private static let key = "orbit.extSectionsOpen"
    static func isOpen(_ s: ExternalSource) -> Bool {
        (UserDefaults.standard.stringArray(forKey: key) ?? []).contains(s.rawValue)
    }
    static func toggle(_ s: ExternalSource) {
        var open = Set(UserDefaults.standard.stringArray(forKey: key) ?? [])
        if open.contains(s.rawValue) { open.remove(s.rawValue) } else { open.insert(s.rawValue) }
        UserDefaults.standard.set(Array(open).sorted(), forKey: key)
    }
}

/// A folding section of sessions one other agent began.
struct ExternalChatSection<Row: View>: View {
    let source: ExternalSource
    let chats: [ChatSummary]
    /// While searching, every section is open.
    var forceOpen = false
    @ViewBuilder var row: (ChatSummary) -> Row
    @State private var open = false

    var body: some View {
        Section {
            if open || forceOpen {
                ForEach(chats) { row($0) }
            }
        } header: {
            Button {
                ExternalSectionsOpen.toggle(source)
                withAnimation { open = ExternalSectionsOpen.isOpen(source) }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.bold))
                        .rotationEffect(.degrees(open || forceOpen ? 90 : 0))
                    Text(source.label)
                    Text("\(chats.count)").foregroundStyle(.secondary)
                    Spacer()
                }
                .contentShape(.rect)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(source.label), \(chats.count) sessions")
            .accessibilityHint(source.tip)
            .accessibilityAddTraits(.isHeader)
        } footer: {
            if open || forceOpen {
                Text(source.tip).font(.caption2)
            }
        }
        .onAppear { open = ExternalSectionsOpen.isOpen(source) }
    }
}

/// What is going on, at a glance: waiting for you, answering, queued. Tapping
/// one shows only the chats that need attention; tapping again shows them all.
struct ChatStatusChips: View {
    @EnvironmentObject var state: AppState
    let chats: [ChatSummary]
    @Binding var filter: ChatFilter

    var body: some View {
        let ids = Set(chats.map(\.id))
        let waiting = state.chatExtras.waiting.intersection(ids).count
        let answering = state.runningChats.intersection(ids).count
        let queued = chats.filter { ($0.queued ?? 0) > 0 }.count
        if waiting + answering + queued > 0 {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    if waiting > 0 { chip("! \(waiting) waiting for you", tint: .orange, spinner: false) }
                    if answering > 0 { chip("\(answering) answering", tint: .accentColor, spinner: true) }
                    if queued > 0 {
                        chip("\(queued) with queued message\(queued == 1 ? "" : "s")", tint: .purple, spinner: false)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 6)
            }
            .background(.bar)
            .overlay(Divider(), alignment: .bottom)
        }
    }

    private func chip(_ text: String, tint: Color, spinner: Bool) -> some View {
        Button {
            withAnimation { filter = filter == .attention ? .active : .attention }
        } label: {
            HStack(spacing: 5) {
                if spinner { ProgressView().controlSize(.mini) }
                Text(text).font(.caption.weight(.medium))
            }
            .padding(.horizontal, 10).padding(.vertical, 5)
            .foregroundStyle(filter == .attention ? .white : tint)
            .background(filter == .attention ? AnyShapeStyle(tint) : AnyShapeStyle(tint.opacity(0.14)),
                        in: .capsule)
        }
        .buttonStyle(.plain)
        .accessibilityHint(filter == .attention ? "Shows every chat" : "Shows only chats that need attention")
    }
}

/// The SSH host a chat runs on.
struct ChatHostBadge: View {
    let host: String

    var body: some View {
        Label(host, systemImage: "server.rack")
            .labelStyle(.titleAndIcon)
            .font(.caption2.weight(.medium))
            .lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .foregroundStyle(.teal)
            .background(Color.teal.opacity(0.12), in: .capsule)
            .accessibilityLabel("runs on \(host) over SSH")
    }
}

/// "Showing 500 of 812 · Show more", under the list when the Mac has more.
struct ChatPagingRow: View {
    @EnvironmentObject var state: AppState
    @State private var loading = false

    var body: some View {
        if state.moreChatsOnMac > 0 {
            HStack {
                Text("Showing \(state.chats.count) of \(state.work.chatTotal ?? state.chats.count)")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if loading {
                    ProgressView().controlSize(.small)
                } else {
                    Button("Show more") {
                        loading = true
                        Task { await state.loadMoreChats(); loading = false }
                    }
                    .font(.caption.weight(.semibold))
                    .buttonStyle(.borderless)
                }
            }
            .listRowSeparator(.hidden)
        }
    }
}

/// A chat's state at a glance: waiting for you, answering, queued, new, scheduled.
struct ChatStatusBadge: View {
    let status: ChatRowStatus

    var body: some View {
        switch status {
        case .none:
            EmptyView()
        case .waiting:
            badge("exclamationmark.circle.fill", status.label!, .orange)
        case .answering:
            HStack(spacing: 4) {
                ProgressView().controlSize(.mini)
                Text("answering").font(.caption2.weight(.medium)).foregroundStyle(.tint)
            }
        case .queued:
            badge("tray.full", status.label!, .purple)
        case .unread:
            HStack(spacing: 4) {
                Circle().fill(Color.accentColor).frame(width: 7, height: 7)
                Text("new").font(.caption2.weight(.medium)).foregroundStyle(.tint)
            }
            .accessibilityElement(children: .combine)
        case .scheduled:
            badge("clock", status.label!, .secondary)
        }
    }

    private func badge(_ icon: String, _ text: String, _ tint: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.caption2.weight(.medium))
            .foregroundStyle(tint)
            .labelStyle(.titleAndIcon)
    }
}

/// Everything you can do to a chat from the list, as the Mac's chat menu offers it.
struct ChatRowMenu: View {
    let chat: ChatSummary
    @ObservedObject var model: ChatListModel
    @EnvironmentObject var state: AppState

    var body: some View {
        Button {
            Task { await state.setPinned(chat.id, !(chat.pinned ?? false)) }
        } label: {
            Label(chat.pinned == true ? "Unpin" : "Pin to top", systemImage: chat.pinned == true ? "pin.slash" : "pin")
        }
        Button {
            model.newTitle = chat.displayTitle
            model.renaming = chat
        } label: { Label("Rename", systemImage: "pencil") }
        Button { model.tagging = chat } label: {
            Label("Tags…", systemImage: "tag")
        }
        Menu {
            ForEach(state.projects) { p in
                Button {
                    Task { await state.assign(chat.id, project: p.id) }
                } label: {
                    if chat.project == p.id {
                        Label(p.name, systemImage: "checkmark")
                    } else {
                        Text(p.name)
                    }
                }
            }
            if chat.project != nil {
                Divider()
                Button(role: .destructive) {
                    Task { await state.assign(chat.id, project: nil) }
                } label: { Label("Remove from project", systemImage: "folder.badge.minus") }
            }
            Divider()
            Button { model.showProjects = true } label: {
                Label("Manage projects…", systemImage: "folder.badge.gearshape")
            }
        } label: {
            Label("Project", systemImage: "folder")
        }
        Button {
            Task {
                guard let server = state.server else { return }
                do { model.exportURL = try await server.exportMarkdown(chat.id, title: chat.displayTitle) }
                catch { state.lastError = error.localizedDescription }
            }
        } label: { Label("Export Markdown", systemImage: "square.and.arrow.up") }
        Button {
            Task { await state.setArchived(chat.id, !(chat.archived ?? false)) }
        } label: {
            Label(chat.archived == true ? "Unarchive" : "Archive", systemImage: "archivebox")
        }
        Button {
            Task { await state.sortByRecent() }
        } label: { Label("Sort by most recent", systemImage: "arrow.up.arrow.down") }
        Divider()
        Button(role: .destructive) {
            Task { await state.binWithUndo(chat.id) }
        } label: { Label("Move to bin", systemImage: "trash") }
    }
}

/// Sheets and alerts for the list, attached once.
struct ChatListHost: ViewModifier {
    @ObservedObject var model: ChatListModel
    @EnvironmentObject var state: AppState

    func body(content: Content) -> some View {
        content
            .sheet(item: $model.tagging) { TagsEditor(chat: $0) }
            .sheet(isPresented: $model.showProjects) { ProjectsManager() }
            .sheet(isPresented: $model.showStats) { UsageStatsView(sid: nil) }
            .sheet(item: $model.exportURL) { ActivityView(items: [$0]).ignoresSafeArea() }
            .alert("Rename chat", isPresented: Binding(
                get: { model.renaming != nil },
                set: { if !$0 { model.renaming = nil } })) {
                TextField("Title", text: $model.newTitle)
                Button("Save") {
                    if let c = model.renaming {
                        let t = model.newTitle
                        Task { await state.rename(c.id, to: t) }
                    }
                    model.renaming = nil
                }
                Button("Cancel", role: .cancel) { model.renaming = nil }
            }
            .modifier(ToastOverlay())
    }
}

/// Tags on one chat: tap to toggle, or add a new one.
struct TagsEditor: View {
    let chat: ChatSummary
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var tags: [String] = []
    @State private var known: [(name: String, count: Int)] = []
    @State private var adding = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        TextField("New tag", text: $adding)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .submitLabel(.done)
                            .onSubmit(add)
                        Button("Add", action: add)
                            .disabled(adding.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
                Section("Tags") {
                    let all = Array(NSOrderedSet(array: tags + known.map(\.name))) as? [String] ?? tags
                    if all.isEmpty { Text("No tags yet").foregroundStyle(.secondary) }
                    ForEach(all, id: \.self) { t in
                        Button {
                            if let i = tags.firstIndex(of: t) { tags.remove(at: i) } else { tags.append(t) }
                        } label: {
                            HStack {
                                Image(systemName: tags.contains(t) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(tags.contains(t) ? Color.accentColor : .secondary)
                                Text(t).foregroundStyle(.primary)
                                Spacer()
                                if let n = known.first(where: { $0.name == t })?.count {
                                    Text("\(n)").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle(chat.displayTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        let t = tags
                        Task { await state.setTags(chat.id, t) }
                        dismiss()
                    }
                }
            }
            .task {
                tags = chat.tags ?? []
                if let server = state.server { known = (try? await server.tags()) ?? [] }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func add() {
        for part in adding.split(separator: ",") {
            let t = part.trimmingCharacters(in: .whitespaces)
            if !t.isEmpty, !tags.contains(t) { tags.append(t) }
        }
        adding = ""
    }
}

/// Projects: folders for chats, with their own instructions.
struct ProjectsManager: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var items: [ProjectDetail] = []
    @State private var editing: ProjectDetail?
    @State private var deleting: ProjectDetail?

    var body: some View {
        NavigationStack {
            List {
                if items.isEmpty {
                    Text("No projects yet. A project groups chats and adds its instructions to each of them.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                ForEach(items) { p in
                    Button { editing = p } label: {
                        HStack(spacing: 10) {
                            Circle().fill(Color(projectHex: p.color)).frame(width: 12, height: 12)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(p.name).foregroundStyle(.primary)
                                let n = state.chats.filter { $0.project == p.id }.count
                                Text(p.description.isEmpty ? "\(n) chat\(n == 1 ? "" : "s")" : p.description)
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            }
                        }
                    }
                    .swipeActions {
                        Button(role: .destructive) { deleting = p } label: { Label("Delete", systemImage: "trash") }
                    }
                }
                // the order they appear in the sidebar, which is the one place a phone
                // is better at this than a mouse
                .onMove { from, to in
                    items.move(fromOffsets: from, toOffset: to)
                    let ids = items.map(\.id)
                    Task {
                        do { try await state.requireServer().reorderProjects(ids); await state.loadProjects() }
                        catch { state.lastError = error.localizedDescription; await load() }
                    }
                }
            }
            .navigationTitle("Projects")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .topBarLeading) { if items.count > 1 { EditButton() } }
                ToolbarItem(placement: .primaryAction) {
                    Button { editing = ProjectDetail() } label: { Image(systemName: "plus") }
                        .accessibilityLabel("New project")
                }
            }
            .sheet(item: $editing) { p in
                ProjectEditor(project: p) { Task { await load() } }
            }
            .confirmationDialog("Delete “\(deleting?.name ?? "")”?",
                                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible) {
                Button("Delete project", role: .destructive) {
                    guard let p = deleting, let server = state.server else { return }
                    Task {
                        do { try await server.deleteProject(p.id) }
                        catch { state.lastError = error.localizedDescription }
                        await load()
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Its chats are kept; they just lose the project.")
            }
            .task { await load() }
        }
    }

    private func load() async {
        guard let server = state.server else { return }
        items = (try? await server.projectDetails()) ?? []
        await state.loadProjects()
        await state.loadChats()
    }
}

struct ProjectEditor: View {
    @State var project: ProjectDetail
    var saved: () -> Void
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $project.name)
                    TextField("What this project is about", text: $project.description)
                    HStack(spacing: 10) {
                        ForEach(ProjectDetail.colors, id: \.self) { c in
                            Circle().fill(Color(projectHex: c)).frame(width: 26, height: 26)
                                .overlay(Circle().strokeBorder(.primary, lineWidth: project.color == c ? 2 : 0))
                                .onTapGesture { project.color = c }
                                .accessibilityLabel("Colour \(c)")
                                .accessibilityAddTraits(project.color == c ? .isSelected : [])
                        }
                    }
                }
                Section {
                    TextField("/absolute/path (optional)", text: $project.folder)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.callout.monospaced())
                    Toggle("Trust this folder's tools", isOn: $project.trustTools)
                } header: {
                    Text("Folder on the Mac")
                } footer: {
                    Text("A rules file there (ORBIT.md or AGENTS.md) and a .orbit/tools folder apply to this project's chats.")
                }
                Section {
                    TextEditor(text: $project.instructions).frame(minHeight: 140)
                } header: {
                    Text("Instructions")
                } footer: {
                    Text("Added to every chat in this project.")
                }
                if let error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
            }
            .navigationTitle(project.id.isEmpty ? "New project" : "Edit project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(project.name.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                }
            }
        }
    }

    private func save() async {
        guard let server = state.server else { return }
        let folder = project.folder.trimmingCharacters(in: .whitespaces)
        if !folder.isEmpty, !(folder.hasPrefix("/") || folder.hasPrefix("~/")) {
            error = "The folder needs an absolute path."
            return
        }
        busy = true
        defer { busy = false }
        var p = project
        p.name = p.name.trimmingCharacters(in: .whitespaces)
        p.folder = folder
        do {
            let r = try await server.saveProjectNotingFolder(p)
            saved()
            // saved either way; stay open so the warning is read before it is gone
            if r.folderMissing {
                project.id = r.id
                self.error = "Saved — but that folder does not exist yet."
                return
            }
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}

extension Color {
    /// "#6b5bd6" → a colour; anything unreadable is grey.
    init(projectHex hex: String) {
        let s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        guard s.count == 6, let v = UInt32(s, radix: 16) else { self = .gray; return }
        self.init(red: Double((v >> 16) & 0xff) / 255, green: Double((v >> 8) & 0xff) / 255,
                  blue: Double(v & 0xff) / 255)
    }
}
