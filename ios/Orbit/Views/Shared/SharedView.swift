import SwiftUI

/// The Shared tab: the projects you work on with other people.
struct SharedView: View {
    @EnvironmentObject var state: AppState
    /// Pushed from Settings it sits inside that tab's stack; as a tab it has its own.
    var embedded = false
    @State private var path: [SharedProject] = []
    @State private var creating = false

    private var store: SharedStore { state.shared }

    var body: some View {
        if embedded {
            list
        } else {
            NavigationStack(path: $path) { list }
                .onAppear {
                    #if DEBUG
                    // development only: ORBIT_SHARED=open lands inside the first project
                    if ProcessInfo.processInfo.environment["ORBIT_SHARED"] == "open",
                       let p = store.projects.first { path = [p] }
                    #endif
                }
        }
    }

    private var list: some View {
        List {
            if state.reachable == false { ConnectionBannerRow() }
            content
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Shared")
        .navigationBarTitleDisplayMode(embedded ? .inline : .large)
        .toolbar {
            if store.enabled == true {
                ToolbarItem(placement: .primaryAction) {
                    Button { creating = true } label: { Image(systemName: "plus") }
                        .accessibilityLabel("New shared project")
                }
            }
        }
        .sheet(isPresented: $creating) { NewSharedProjectSheet().environmentObject(state) }
        .navigationDestination(for: SharedProject.self) { SharedProjectView(project: $0) }
        .refreshable { await state.shared.refresh(using: state.server) }
        .task {
            #if DEBUG
            // development only: ORBIT_SHARED=web opens the first project full screen, web:<chat> on a chat
            let hook = ProcessInfo.processInfo.environment["ORBIT_SHARED"] ?? ""
            if hook.hasPrefix("web") {
                if store.projects.isEmpty { await state.shared.refresh(using: state.server) }
                if let p = store.projects.first, state.sharedTarget == nil {
                    state.sharedTarget = SharedTarget(project: p, chat: hook.count > 4 ? String(hook.dropFirst(4)) : nil)
                }
            }
            #endif
            // while this is on screen, keep who is here and what is new current, as the web sidebar does
            while !Task.isCancelled {
                await state.shared.refresh(using: state.server, quiet: !store.projects.isEmpty)
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
        .overlay { overlay }
    }

    @ViewBuilder private var content: some View {
        if !store.projects.isEmpty {
            Section {
                ForEach(store.projects) { p in
                    NavigationLink(value: p) { SharedProjectRow(project: p, detail: store.detail(p.id)) }
                        .contextMenu {
                            Button {
                                Haptics.press()
                                state.sharedTarget = SharedTarget(project: p, chat: nil)
                            } label: { Label("Open the project", systemImage: "arrow.up.forward.app") }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Haptics.press()
                                state.sharedTarget = SharedTarget(project: p, chat: nil)
                            } label: { Label("Open", systemImage: "arrow.up.forward.app") }
                            .tint(.accentColor)
                        }
                }
            } footer: {
                if store.stale, let when = store.lastRefresh {
                    Text("Last updated \(when.formatted(.relative(presentation: .named))). Pull down to refresh.")
                } else {
                    Text("These live on your Mac. Opening one shows the same page your collaborators use, with you signed in as the owner.")
                }
            }
        }
    }

    @ViewBuilder private var overlay: some View {
        if store.projects.isEmpty {
            switch store.phase {
            case .loading:
                ProgressView()
            case .limited:
                ContentUnavailableView("Chats only",
                    systemImage: "lock",
                    description: Text("This phone is set up to use chats only. Allow it more on the Mac, in Settings, Phone, to open shared projects."))
            case .failed(let m):
                ContentUnavailableView {
                    Label("Can't reach your Mac", systemImage: "wifi.slash")
                } description: {
                    Text(m)
                } actions: {
                    Button("Try again") { Task { await state.shared.refresh(using: state.server) } }
                        .buttonStyle(.bordered)
                }
            case .idle:
                if store.enabled == false {
                    ContentUnavailableView("Shared projects are off",
                        systemImage: "person.2.slash",
                        description: Text("Switch them on at your Mac, in Settings, Shared projects. Then the projects you share appear here."))
                } else if store.enabled == true {
                    ContentUnavailableView {
                        Label("No shared projects yet", systemImage: "person.2")
                    } description: {
                        Text("Start one here, or on your Mac in Settings, Shared projects. Its chats show up in your chat list too.")
                    } actions: {
                        Button("New shared project") { creating = true }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }
        }
    }
}

/// A small "Mac unreachable" line inside a list (the banner above a list in
/// Chats does not fit a grouped list).
struct ConnectionBannerRow: View {
    @EnvironmentObject var state: AppState
    var body: some View {
        Section {
            Label("Can't reach \(state.pairing?.name ?? "your Mac"). Showing the last copy.",
                  systemImage: "wifi.slash")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }
}

struct SharedProjectRow: View {
    let project: SharedProject
    let detail: SharedDetail
    @Environment(\.dynamicTypeSize) private var typeSize
    /// At the biggest text sizes a line that truncates says nothing; let it wrap.
    private var lines: Int? { typeSize.isAccessibilitySize ? nil : 1 }

    private var who: String {
        let names = detail.onlineNames
        switch names.count {
        case 0: return project.members > 1 ? "\(project.members) people" : "Just you"
        case 1: return "\(names[0]) is here"
        case 2: return "\(names[0]) and \(names[1]) are here"
        default: return "\(names[0]), \(names[1]) and \(names.count - 2) more are here"
        }
    }

    private var activity: String? {
        guard let t = detail.lastActivity else { return nil }
        let d = Date(timeIntervalSince1970: t)
        if Date.now.timeIntervalSince(d) < 60 { return "active just now" }
        return "active " + d.formatted(.relative(presentation: .named, unitsStyle: .abbreviated))
    }

    var body: some View {
        HStack(spacing: 12) {
            ZStack(alignment: .bottomTrailing) {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(SharedStyle.color(project.id).gradient)
                    .frame(width: 44, height: 44)
                    .overlay(Text(String(project.name.prefix(1)).uppercased())
                        .font(.system(size: 20, weight: .semibold)).foregroundStyle(.white))
                if !detail.onlineNames.isEmpty {
                    Circle().fill(.green).frame(width: 12, height: 12)
                        .overlay(Circle().stroke(Color(.systemBackground), lineWidth: 2))
                        .offset(x: 3, y: 3)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(project.name).font(.body.weight(.medium)).lineLimit(lines)
                    if detail.frozen || project.frozen {
                        Image(systemName: "pause.circle.fill").font(.caption).foregroundStyle(.orange)
                            .accessibilityLabel("Paused")
                    }
                }
                Text(who).font(.subheadline).foregroundStyle(.secondary).lineLimit(lines)
                Text([ "\(detail.chats.count) \(detail.chats.count == 1 ? "chat" : "chats")", activity ]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(lines)
            }
            Spacer(minLength: 0)
            if detail.unread > 0 {
                Text(detail.unreadMore ? "\(detail.unread)+" : "\(detail.unread)")
                    .font(.footnote.weight(.semibold).monospacedDigit())
                    .foregroundStyle(.white)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Color.accentColor, in: Capsule())
                    .accessibilityLabel("\(detail.unread) new")
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

enum SharedStyle {
    /// A stable colour per project, from its id.
    static func color(_ id: String) -> Color {
        let palette: [Color] = [.blue, .indigo, .purple, .teal, .green, .orange, .pink, .cyan]
        let h = id.unicodeScalars.reduce(0) { ($0 &* 31) &+ Int($1.value) }
        return palette[abs(h) % palette.count]
    }
}

/// One project: open it, jump to a chat in it, see who is in it.
struct SharedProjectView: View {
    let project: SharedProject
    @EnvironmentObject var state: AppState
    @State private var removing: SharedChat?
    @State private var note: String?

    private var detail: SharedDetail { state.shared.detail(project.id) }

    var body: some View {
        List {
            Section {
                Button {
                    Haptics.press()
                    state.sharedTarget = SharedTarget(project: project, chat: nil)
                } label: {
                    HStack {
                        Label("Open \(project.name)", systemImage: "arrow.up.forward.app")
                            .font(.body.weight(.semibold))
                        Spacer()
                        if detail.unread > 0 {
                            Text(detail.unreadMore ? "\(detail.unread)+ new" : "\(detail.unread) new")
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                if detail.frozen || project.frozen {
                    Label("Paused. Nobody can send until you resume it on the Mac.", systemImage: "pause.circle")
                        .font(.footnote).foregroundStyle(.orange)
                }
            }

            Section("Chats") {
                if detail.chats.isEmpty {
                    Text("No chats yet").foregroundStyle(.secondary)
                }
                ForEach(detail.chats) { chat in
                    Button {
                        Haptics.tap()
                        state.sharedTarget = SharedTarget(project: project, chat: chat.id)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: chat.id == "main" ? "bubble.left.and.bubble.right" : "number")
                                .foregroundStyle(.secondary).frame(width: 22)
                            Text(chat.displayName).foregroundStyle(.primary)
                            if chat.imported == true {
                                Image(systemName: "arrow.up.doc").font(.caption).foregroundStyle(.tertiary)
                                    .accessibilityLabel("Shared from your chats")
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                        }
                    }
                    .buttonStyle(.plain)
                    .contextMenu { chatMenu(chat) }
                    .swipeActions(edge: .trailing) {
                        if chat.id != "main" {
                            Button(role: .destructive) { removing = chat } label: {
                                Label("Remove", systemImage: "minus.circle")
                            }
                        }
                    }
                    .swipeActions(edge: .leading) {
                        Button { Task { await copy(chat) } } label: {
                            Label("Copy to mine", systemImage: "doc.on.doc")
                        }.tint(.blue)
                    }
                }
            }

            SharedPeopleSection(project: project, detail: detail, note: $note)
            SharedProjectControls(project: project, frozen: detail.frozen || project.frozen, note: $note)
        }
        .navigationTitle(project.name)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await state.shared.refresh(using: state.server) }
        .confirmationDialog("Remove “\(removing?.displayName ?? "")” from \(project.name)?",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible, presenting: removing) { chat in
            Button("Remove from the project", role: .destructive) { Task { await remove(chat) } }
        } message: { _ in
            Text("Nobody in the project can read it afterwards. Your own chats are not touched.")
        }
        .alert("Shared project", isPresented: Binding(get: { note != nil }, set: { if !$0 { note = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(note ?? "") }
    }

    @ViewBuilder private func chatMenu(_ chat: SharedChat) -> some View {
        Button {
            state.sharedTarget = SharedTarget(project: project, chat: chat.id)
        } label: { Label("Open", systemImage: "arrow.up.forward.app") }
        Button { Task { await copy(chat) } } label: {
            Label("Make a copy in my chats", systemImage: "doc.on.doc")
        }
        if chat.id != "main" {
            Divider()
            Button(role: .destructive) { removing = chat } label: {
                Label("Remove from the project", systemImage: "minus.circle")
            }
        }
    }

    private func copy(_ chat: SharedChat) async {
        guard let server = state.server else { return }
        do {
            let title = try await server.copySharedChat(project: project.id, chat: chat.id)
            Haptics.success()
            note = "Copied “\(title)” into your own chats."
            await state.loadChats()
        } catch { note = error.localizedDescription }
    }

    private func remove(_ chat: SharedChat) async {
        guard let server = state.server else { return }
        do {
            try await server.removeSharedChat(project: project.id, chat: chat.id)
            Haptics.success()
            await state.shared.refresh(using: server, quiet: true)
        } catch { note = error.localizedDescription }
    }
}

/// The yes/no before a chat is copied into a project, and what came of it.
/// Attach once near the root; any view starts a share through `state.shared`.
struct SharePlanAlerts: ViewModifier {
    @EnvironmentObject var state: AppState

    func body(content: Content) -> some View {
        content
            .alert("Add to a shared project?",
                   isPresented: Binding(get: { state.shared.plan != nil },
                                        set: { if !$0 { state.shared.plan = nil } }),
                   presenting: state.shared.plan) { plan in
                Button(plan.warnings.isEmpty ? "Add to \(plan.project.name)" : "Add anyway",
                       role: plan.warnings.isEmpty ? nil : .destructive) {
                    Task { await state.shared.confirmShare(using: state.server) }
                }
                Button("Cancel", role: .cancel) { state.shared.plan = nil }
            } message: { plan in
                Text(planMessage(plan))
            }
            .alert(item: Binding(get: { state.shared.note }, set: { state.shared.note = $0 })) { n in
                if let p = n.project {
                    return Alert(title: Text(n.title), message: Text(n.message),
                                 primaryButton: .default(Text("Open project")) {
                                     state.sharedTarget = SharedTarget(project: p, chat: nil)
                                 },
                                 secondaryButton: .cancel(Text("OK")))
                }
                return Alert(title: Text(n.title), message: Text(n.message), dismissButton: .default(Text("OK")))
            }
    }

    private func planMessage(_ plan: SharePlan) -> String {
        var s = "“\(plan.title)” has \(plan.messages) messages. What you and the model said becomes a new chat in “\(plan.project.name)”, visible to everyone in it. Tool output and images aren't copied. Your own chat stays as it is."
        if !plan.warnings.isEmpty {
            s += "\n\nIt looks like it contains \(plan.warnings.joined(separator: ", ")). Everyone in the project could read that."
        }
        return s
    }
}

extension View {
    func sharePlanAlerts() -> some View { modifier(SharePlanAlerts()) }
}
