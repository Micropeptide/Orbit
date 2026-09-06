import SwiftUI

/// The Mac's daily archive of chats, memory, skills, knowledge and settings —
/// into iCloud Drive when the Mac has it. Restoring only adds what is missing.
struct BackupSection: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Section {
            if let b = state.backup {
                Toggle("Automatic backup", isOn: Binding(
                    get: { b.enabled },
                    set: { on in Task { await state.setBackup(enabled: on) } }))
                LabeledContent("Where", value: b.in_icloud ? "iCloud Drive" : "On the Mac")
                LabeledContent("Last backup", value: b.last.map { relative($0.date) } ?? "never")
                if b.count > 0 {
                    LabeledContent("Kept", value: "\(b.count) · " + bytes(b.total_bytes ?? 0))
                }
                Button {
                    Haptics.tap()
                    Task { await state.backupNow() }
                } label: {
                    HStack {
                        Text("Back up now")
                        Spacer()
                        if state.backupBusy { ProgressView().controlSize(.mini) }
                    }
                }
                .disabled(state.backupBusy)
                if let list = b.backups, !list.isEmpty {
                    NavigationLink("Backups") { BackupListView(backups: list) }
                }
                if let note = state.backupNote, !note.isEmpty {
                    Text(note).font(.caption).foregroundStyle(.secondary)
                }
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.mini)
                    Text("Checking with the Mac").font(.footnote).foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Backup")
        } footer: {
            Text(footer)
        }
    }

    private var footer: String {
        guard let b = state.backup else { return "" }
        let base = "Once a day the Mac archives chats, memory, skills, knowledge and "
            + "settings. API keys and the pairing token stay out. "
        return b.icloud
            ? base + "Archives go to iCloud Drive › Orbit Backups, so a lost Mac costs a "
                   + "restore, not the conversations."
            : base + "iCloud Drive isn't set up on the Mac, so they stay in Orbit's own "
                   + "backups folder."
    }

    private func relative(_ d: Date) -> String {
        if Date.now.timeIntervalSince(d) < 60 { return "just now" }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .abbreviated
        return f.localizedString(for: d, relativeTo: .now)
    }

    private func bytes(_ n: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(n), countStyle: .file)
    }
}

struct BackupListView: View {
    @EnvironmentObject var state: AppState
    let backups: [BackupEntry]
    @State private var confirm: BackupEntry?

    var body: some View {
        List(backups) { b in
            VStack(alignment: .leading, spacing: 3) {
                Text(b.date.formatted(date: .abbreviated, time: .shortened))
                Text(ByteCountFormatter.string(fromByteCount: Int64(b.bytes), countStyle: .file))
                    .font(.caption).foregroundStyle(.secondary)
            }
            .contextMenu {
                Button {
                    confirm = b
                } label: { Label("Restore what is missing", systemImage: "arrow.uturn.backward") }
            }
        }
        .navigationTitle("Backups")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("Restore from this backup?", isPresented: Binding(
            get: { confirm != nil }, set: { if !$0 { confirm = nil } }),
            titleVisibility: .visible) {
            if let b = confirm {
                Button("Put back what is missing") {
                    Task { await state.restoreMissing(from: b) }
                    confirm = nil
                }
            }
            Button("Cancel", role: .cancel) { confirm = nil }
        } message: {
            Text("Chats, memory, skills and knowledge the Mac no longer has are put back. "
                 + "Nothing on the Mac is overwritten.")
        }
        .overlay(alignment: .bottom) {
            if let note = state.backupNote, !note.isEmpty {
                Text(note).font(.footnote.weight(.medium))
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.thinMaterial, in: .capsule)
                    .padding(.bottom, 12)
            }
        }
    }
}
