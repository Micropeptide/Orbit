import SwiftUI

/// Hosting a shared project from the phone: start one, invite people, look after who is in it.

// MARK: - New project

struct NewSharedProjectSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @AppStorage("sharedOwnerName") private var ownerName = ""
    @State private var name = ""
    @State private var folder = ""
    @State private var working = false
    @State private var error: String?

    private var canCreate: Bool { !name.trimmingCharacters(in: .whitespaces).isEmpty && !working }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name, for example Methylation notebook", text: $name)
                        .textInputAutocapitalization(.sentences)
                } footer: {
                    Text("People you invite see this name.")
                }
                Section {
                    TextField("/path/to/the/folder", text: $folder)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .font(.body.monospaced())
                } header: {
                    Text("Working folder on your Mac")
                } footer: {
                    Text("The folder the models work in. Each person can only reach what you allow. Leave it empty for a project that only chats.")
                }
                Section {
                    TextField("Me", text: $ownerName)
                } header: {
                    Text("Your name in the project")
                }
                if let error {
                    Section { Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.footnote) }
                }
            }
            .navigationTitle("New shared project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button { Task { await create() } } label: {
                        if working { ProgressView() } else { Text("Create").fontWeight(.semibold) }
                    }
                    .disabled(!canCreate)
                }
            }
        }
    }

    private func create() async {
        guard let server = state.server else { return }
        working = true; error = nil
        defer { working = false }
        do {
            try await server.sharedCreateProject(name: name.trimmingCharacters(in: .whitespaces),
                                                 workingDir: folder.trimmingCharacters(in: .whitespaces),
                                                 ownerName: ownerName.trimmingCharacters(in: .whitespaces).isEmpty ? "Me" : ownerName)
            Haptics.success()
            await state.shared.refresh(using: server)
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Invite

struct InviteSheet: View {
    let project: SharedProject
    let roles: [String]
    var onDone: () -> Void = {}
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var role = "editor"
    @State private var uses = 1
    @State private var days: Int? = 7
    @State private var made: SharedInviteLink?
    @State private var working = false
    @State private var error: String?
    @State private var copied = false

    private static let blurb: [String: String] = [
        "admin": "Can invite people and change what others may do.",
        "editor": "Chats, asks the models, edits files you allow.",
        "commenter": "Reads and comments; cannot make the models change files.",
        "viewer": "Reads only.",
        "guest": "Reads the chats it is shown, nothing else.",
    ]

    var body: some View {
        NavigationStack {
            Form {
                if let made { linkSection(made) } else { optionsSection }
                if let error {
                    Section { Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.footnote) }
                }
            }
            .navigationTitle("Invite to \(project.name)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(made == nil ? "Cancel" : "Done") { onDone(); dismiss() } }
            }
        }
    }

    @ViewBuilder private var optionsSection: some View {
        Section {
            Picker("They can", selection: $role) {
                ForEach(offered, id: \.self) { Text($0.capitalized).tag($0) }
            }
            .pickerStyle(.menu)
        } footer: {
            Text(Self.blurb[role] ?? "")
        }
        Section {
            Picker("Link works for", selection: $uses) {
                Text("One person").tag(1)
                Text("Five people").tag(5)
                Text("Anyone who has it").tag(0)
            }
            Picker("Link lapses", selection: $days) {
                Text("In a day").tag(Optional(1))
                Text("In a week").tag(Optional(7))
                Text("In a month").tag(Optional(30))
                Text("Never").tag(Optional<Int>.none)
            }
        } footer: {
            Text("You can cancel an unused link from the project's People list at any time.")
        }
        Section {
            Button { Task { await make() } } label: {
                HStack { Spacer(); if working { ProgressView() } else { Text("Create the link").fontWeight(.semibold) }; Spacer() }
            }
            .disabled(working)
        }
    }

    @ViewBuilder private func linkSection(_ l: SharedInviteLink) -> some View {
        Section {
            Text(l.link).font(.footnote.monospaced()).textSelection(.enabled).lineLimit(4)
            ShareLink(item: l.link, subject: Text("Join \(project.name) on Orbit"),
                      message: Text("Open this link to join “\(project.name)” on Orbit.")) {
                Label("Send the link…", systemImage: "square.and.arrow.up")
            }
            Button {
                UIPasteboard.general.string = l.link
                copied = true; Haptics.success()
            } label: {
                Label(copied ? "Copied" : "Copy the link", systemImage: copied ? "checkmark" : "doc.on.doc")
            }
        } header: {
            Text("Invitation link, \(l.role ?? role)")
        } footer: {
            Text("Anyone who opens it can join with this role, so send it only to the person you mean.")
        }
        if l.onlyOnTheMac {
            Section {
                Label("This link only opens on your Mac. To let other people reach the project, publish it through the Orbit service or choose a reachable mode at the Mac, in Settings, Shared projects.",
                      systemImage: "exclamationmark.triangle")
                    .font(.footnote).foregroundStyle(.orange)
            }
        }
    }

    /// Roles an invitation may carry: not the owner's.
    private var offered: [String] {
        let all = roles.isEmpty ? ["admin", "editor", "commenter", "viewer", "guest"] : roles
        return all.filter { $0 != "owner" }
    }

    private func make() async {
        guard let server = state.server else { return }
        working = true; error = nil
        defer { working = false }
        do {
            made = try await server.sharedInvite(project: project.id, role: role, uses: uses, expiresDays: days)
            Haptics.success()
        } catch {
            self.error = error.localizedDescription
        }
    }
}

// MARK: - People and invitations

/// Who is in the project and what to do about it: change a role, mute, remove, cancel an unused invitation.
struct SharedPeopleSection: View {
    let project: SharedProject
    let detail: SharedDetail
    @Binding var note: String?
    @EnvironmentObject var state: AppState
    @State private var people = SharedPeople()
    @State private var loaded = false
    @State private var inviting = false
    @State private var removing: SharedMember?

    var body: some View {
        Group {
            Section {
                ForEach(rows) { person in
                    row(person)
                }
                Button { inviting = true } label: { Label("Invite someone", systemImage: "person.badge.plus") }
            } header: {
                Text("People")
            }
            if !people.invites.isEmpty {
                Section {
                    ForEach(people.invites) { inv in
                        HStack {
                            Image(systemName: "link").foregroundStyle(.secondary).frame(width: 22)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\((inv.role ?? "editor").capitalized) link")
                                Text(inviteDetail(inv)).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) { Task { await act(inv.id, "revoke_invite") } } label: {
                                Label("Cancel", systemImage: "xmark.circle")
                            }
                        }
                    }
                } header: {
                    Text("Unused invitation links")
                } footer: {
                    Text("Swipe a link to cancel it.")
                }
            }
        }
        .task { await load() }
        .sheet(isPresented: $inviting) {
            InviteSheet(project: project, roles: people.roles) { Task { await load() } }
                .environmentObject(state)
        }
        .confirmationDialog("Remove \(removing?.name ?? "this person")?",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible, presenting: removing) { m in
            Button("Remove from the project", role: .destructive) { Task { await act(m.id, "remove") } }
        } message: { _ in
            Text("They lose access at once. They can come back only with a new invitation.")
        }
    }

    /// The Mac's list when it has answered; until then the list the project page already gave us.
    private var rows: [SharedMember] {
        if loaded, !people.members.isEmpty { return people.members }
        return detail.people.map { SharedMember(id: $0.id, name: $0.name, role: $0.role, state: $0.state, owner: $0.role == "owner", summary: nil) }
    }

    @ViewBuilder private func row(_ person: SharedMember) -> some View {
        let here = detail.online.contains(person.id)
        let isMe = person.id == detail.me
        let locked = person.owner == true || isMe
        HStack(spacing: 10) {
            Circle().fill(here ? Color.green : Color.secondary.opacity(0.3)).frame(width: 9, height: 9)
            VStack(alignment: .leading, spacing: 2) {
                Text(isMe ? "\(person.name) (you)" : person.name)
                if person.isMuted { Text("Muted").font(.caption).foregroundStyle(.orange) }
            }
            Spacer()
            if let role = person.role { Text(role.capitalized).font(.caption).foregroundStyle(.secondary) }
            if !locked {
                Menu {
                    roleMenu(person)
                    Button { Task { await act(person.id, person.isMuted ? "unmute" : "mute") } } label: {
                        Label(person.isMuted ? "Let them write again" : "Mute", systemImage: person.isMuted ? "speaker.wave.2" : "speaker.slash")
                    }
                    Divider()
                    Button(role: .destructive) { removing = person } label: { Label("Remove…", systemImage: "person.badge.minus") }
                } label: {
                    Image(systemName: "ellipsis.circle").foregroundStyle(.secondary).padding(6)
                }
                .accessibilityLabel("Actions for \(person.name)")
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(here ? "here now" : "away")
    }

    @ViewBuilder private func roleMenu(_ person: SharedMember) -> some View {
        Menu {
            ForEach(people.roles.filter { $0 != "owner" }, id: \.self) { r in
                Button { Task { await act(person.id, "role", value: r) } } label: {
                    if r == person.role { Label(r.capitalized, systemImage: "checkmark") } else { Text(r.capitalized) }
                }
            }
        } label: { Label("Change what they can do", systemImage: "person.crop.circle.badge.checkmark") }
    }

    private func inviteDetail(_ inv: SharedInviteRow) -> String {
        var parts: [String] = []
        if let n = inv.usesLeft { parts.append(n == 1 ? "one use left" : "\(n) uses left") } else { parts.append("no limit on uses") }
        if let t = inv.expiresAt {
            parts.append("lapses " + Date(timeIntervalSince1970: t).formatted(.relative(presentation: .named)))
        } else { parts.append("does not lapse") }
        return parts.joined(separator: ", ")
    }

    private func load() async {
        guard let server = state.server else { return }
        if let p = try? await server.sharedPeople(project: project.id) { people = p; loaded = true }
    }

    private func act(_ id: String, _ action: String, value: String? = nil) async {
        guard let server = state.server else { return }
        do {
            try await server.sharedMemberAction(project: project.id, member: id, action: action, value: value)
            Haptics.success()
            await load()
            await state.shared.refresh(using: server, quiet: true)
        } catch { note = error.localizedDescription }
    }
}

// MARK: - Project controls

/// Pause, rename and the export switch: the few things the owner changes about the project itself.
struct SharedProjectControls: View {
    let project: SharedProject
    let frozen: Bool
    @Binding var note: String?
    @EnvironmentObject var state: AppState
    @State private var renaming = false
    @State private var newName = ""
    @State private var allowExport: Bool

    init(project: SharedProject, frozen: Bool, note: Binding<String?>) {
        self.project = project
        self.frozen = frozen
        self._note = note
        self._allowExport = State(initialValue: project.allowExport)
    }

    var body: some View {
        Section {
            Button { Task { await setPaused(!frozen) } } label: {
                if frozen { Label("Resume the project", systemImage: "play.circle") }
                else { Label("Pause the project", systemImage: "pause.circle") }
            }
            Button { newName = project.name; renaming = true } label: { Label("Rename", systemImage: "pencil") }
            Toggle(isOn: Binding(get: { allowExport }, set: { v in allowExport = v; Task { await setExport(v) } })) {
                Label("Let people export chats", systemImage: "square.and.arrow.up")
            }
        } header: {
            Text("Project")
        } footer: {
            Text(frozen ? "Paused: nobody can send anything until you resume it."
                        : "Pausing stops every model and every message at once. Use it if something looks wrong.")
        }
        .alert("Rename the project", isPresented: $renaming) {
            TextField("Name", text: $newName)
            Button("Rename") { Task { await rename() } }
            Button("Cancel", role: .cancel) {}
        }
    }

    private func setPaused(_ paused: Bool) async {
        guard let server = state.server else { return }
        do {
            try await server.sharedSetPaused(project: project.id, paused: paused)
            Haptics.success()
            await state.shared.refresh(using: server, quiet: true)
        } catch { note = error.localizedDescription }
    }

    private func setExport(_ v: Bool) async {
        guard let server = state.server else { return }
        do { try await server.sharedSettings(project: project.id, allowExport: v) }
        catch { allowExport = !v; note = error.localizedDescription }
    }

    private func rename() async {
        let n = newName.trimmingCharacters(in: .whitespaces)
        guard let server = state.server, !n.isEmpty else { return }
        do {
            try await server.sharedSettings(project: project.id, name: n)
            await state.shared.refresh(using: server, quiet: true)
        } catch { note = error.localizedDescription }
    }
}
