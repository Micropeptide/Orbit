import SwiftUI

/// Where archives go, how often, how many are kept and what goes in them —
/// plus a one-off export of the whole setup and a restore from an archive.
struct BackupOptionsView: View {
    @EnvironmentObject var state: AppState
    @State private var dest = ""
    @State private var every = 24
    @State private var keep = 14
    @State private var workspace = false
    @State private var secrets = false
    @State private var loaded = false
    @State private var busy = false
    @State private var note: String?
    @State private var exported: String?
    @State private var restorePath = ""
    @State private var confirmRestore = false
    @State private var confirmSecrets = false

    var body: some View {
        Form {
            if loaded {
                Section {
                    TextField("Folder on the Mac", text: $dest)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                        .font(.callout)
                    Stepper(value: $every, in: 1...720) {
                        LabeledContent("Every", value: "\(every) hour\(every == 1 ? "" : "s")")
                    }
                    Stepper(value: $keep, in: 1...365) {
                        LabeledContent("Keep", value: "\(keep) archive\(keep == 1 ? "" : "s")")
                    }
                    Toggle(isOn: $workspace) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Include the workspace folder")
                            Text("files it made; can be large").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Toggle(isOn: Binding(get: { secrets }, set: { on in
                        if on { confirmSecrets = true } else { secrets = false }
                    })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Include API keys and the pairing token")
                            Text("off, so a stolen archive cannot spend your keys")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Button("Save") { Task { await save() } }.disabled(busy)
                } header: {
                    Text("Automatic backup")
                } footer: {
                    Text("Every: hours between archives. Keep: how many recent archives to hold on to.")
                }

                Section {
                    Button {
                        Task { await export() }
                    } label: {
                        HStack {
                            Text("Export everything now")
                            Spacer()
                            if busy { ProgressView().controlSize(.mini) }
                        }
                    }
                    .disabled(busy)
                    if let exported { Text(exported).font(.caption).foregroundStyle(.secondary) }
                } header: {
                    Text("Export")
                } footer: {
                    Text("A single archive of Orbit's setup, saved in the workspace on the Mac.")
                }

                Section {
                    TextField("Path to a backup archive on the Mac", text: $restorePath)
                        .autocorrectionDisabled().textInputAutocapitalization(.never)
                        .font(.callout)
                    Button("Restore from this archive", role: .destructive) { confirmRestore = true }
                        .disabled(busy || restorePath.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Restore")
                } footer: {
                    Text("Unlike putting back what is missing, this restores the archive's files over what is "
                         + "on the Mac now.")
                }
            } else {
                LoadingRow()
            }
        }
        .navigationTitle("Backup options")
        .navigationBarTitleDisplayMode(.inline)
        .task { if !loaded { await load() } }
        .settingsNote($note)
        .confirmationDialog("Restore from this archive?", isPresented: $confirmRestore, titleVisibility: .visible) {
            Button("Restore", role: .destructive) { Task { await restore() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Files in the archive replace the ones on the Mac. This can't be undone from the phone.")
        }
        .confirmationDialog("Put API keys in the archives?", isPresented: $confirmSecrets,
                            titleVisibility: .visible) {
            Button("Include keys and the pairing token", role: .destructive) { secrets = true }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Anyone who gets hold of an archive could then use your keys and reach Orbit as this phone does.")
        }
    }

    private func load() async {
        if state.backup == nil { await state.refreshBackup() }
        guard let b = state.backup else { note = "the Mac did not answer"; return }
        dest = b.dest
        every = max(1, b.every_hours)
        keep = max(1, b.keep)
        workspace = b.include_workspace ?? false
        secrets = b.include_secrets ?? false
        loaded = true
    }

    private func save() async {
        busy = true
        defer { busy = false }
        do {
            state.backup = try await state.requireServer().setBackup([
                "dest": dest.trimmingCharacters(in: .whitespaces), "every_hours": every, "keep": keep,
                "include_workspace": workspace, "include_secrets": secrets,
            ])
            note = "saved"
            Haptics.success()
        } catch { note = error.localizedDescription }
    }

    private func export() async {
        busy = true
        defer { busy = false }
        do {
            let r = try await state.requireServer().exportSetup()
            let name = (r.path as NSString).lastPathComponent
            exported = ByteCountFormatter.string(fromByteCount: Int64(r.bytes), countStyle: .file) + " → " + name
            if restorePath.isEmpty { restorePath = r.path }
            note = "saved to the workspace"
        } catch { note = error.localizedDescription }
    }

    private func restore() async {
        busy = true
        defer { busy = false }
        do {
            let n = try await state.requireServer().importSetup(
                path: restorePath.trimmingCharacters(in: .whitespaces))
            note = "restored \(n) file\(n == 1 ? "" : "s")"
            await state.loadChats()
        } catch { note = error.localizedDescription }
    }
}
