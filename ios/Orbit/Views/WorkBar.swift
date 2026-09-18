import SwiftUI

/// Under the title of a Claude Code or Codex chat: which harness, where it
/// works, and its permission mode. Tapping it changes them.
struct WorkBar: View {
    @EnvironmentObject var state: AppState
    let sid: String
    @State private var work: ChatWork?
    @State private var editing = false

    /// Read again when the model changes, a turn lands or an answer starts or ends.
    private var refreshKey: String {
        "\(sid)|\(state.currentModel ?? "")|\(state.messages.count)|\(state.streaming)|\(state.chatExtras.workRevision)"
    }

    var body: some View {
        Group {
            if let w = work, w.engine, state.openChat?.sid == sid {
                Button { editing = true } label: { chip(w) }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(w.harness.label), \(PathText.place(host: w.host, folder: w.folder)), "
                                        + "permission mode \(w.mode.label). Tap to change.")
                    .sheet(isPresented: $editing) {
                        WorkSheet(sid: sid, work: w) { await reload() }
                    }
            } else {
                Color.clear.frame(height: 0)
            }
        }
        .task(id: refreshKey) { await reload() }
    }

    private func chip(_ w: ChatWork) -> some View {
        HStack(spacing: 6) {
            Text(w.harness.label).fontWeight(.semibold)
            Text("·").foregroundStyle(.tertiary)
            Image(systemName: w.host == nil ? "laptopcomputer" : "server.rack").font(.caption2)
            Text(PathText.place(host: w.host, folder: w.folder, keep: 1))
                .lineLimit(1).truncationMode(.head)
            Text("·").foregroundStyle(.tertiary)
            Image(systemName: w.mode.symbol).font(.caption2)
            Text(w.mode.label).lineLimit(1)
                .foregroundStyle(w.mode == .bypass ? .orange : .secondary)
            Spacer(minLength: 0)
            Image(systemName: "chevron.down").font(.caption2).foregroundStyle(.tertiary)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14).padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.bar)
        .overlay(Divider(), alignment: .bottom)
        .contentShape(.rect)
    }

    private func reload() async {
        guard let server = state.server else { return }
        if let w = try? await server.chatWork(sid: sid) { work = w }
    }
}

/// Change where a chat works and its permission mode. The machine only
/// before the first answer: after that its session stays where it began.
struct WorkSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    let sid: String
    let work: ChatWork
    var onSaved: () async -> Void

    @State private var host = ""
    @State private var folder = ""
    @State private var mode: PermissionMode = .auto
    @State private var loaded = false
    @State private var saving = false
    @State private var error: String?
    // resume command, session details and extra folders (Views/Chat/ChatAgentDetails.swift)
    @State private var info: ChatAgentInfo?
    @State private var addDirs: [String] = []

    private var startFolder: String { work.cwd ?? work.cwdPref ?? "" }
    /// The Mac replaces a chat's extra folders with every folder change, so they
    /// are only sent once known — never cleared by a save made before they loaded.
    private var dirsChanged: Bool { info != nil && addDirs != (info?.addDirs ?? []) }
    private var placeChanged: Bool {
        host != (work.host ?? "")
            || folder.trimmingCharacters(in: .whitespacesAndNewlines) != startFolder
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Harness", value: work.harness.label)
                    if let s = work.codexThread ?? work.session {
                        LabeledContent(work.codex ? "Thread" : "Session") {
                            Text(s).font(.caption.monospaced()).lineLimit(1).truncationMode(.middle)
                        }
                    }
                } footer: {
                    if work.started, let f = work.folder {
                        Text("Its session began in \(PathText.place(host: work.host, folder: f)). A new "
                             + "folder is saved for this chat, but to really work somewhere else, "
                             + "start a new chat there.")
                    }
                }

                WorkPlaceSections(host: $host, folder: $folder, harness: work.harness,
                                  hostLocked: work.started,
                                  lockedNote: "This chat has answered, so it stays on "
                                    + (work.host ?? "this Mac")
                                    + ". Start a new chat to work on another machine.")

                if info != nil {
                    AlsoAllowSection(dirs: $addDirs, host: host, harness: work.harness)
                }

                PermissionModeSection(mode: $mode, harness: work.harness)

                if let error {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    }
                }

                if let info {
                    ChatAgentDetailSections(sid: sid, info: info)
                }
            }
            .modifier(ToastOverlay())
            .navigationTitle("Where this chat works")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.disabled(saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("Save") { Task { await save() } }
                            .disabled(!loaded || (!placeChanged && !dirsChanged && mode == work.mode))
                    }
                }
            }
            .interactiveDismissDisabled(saving)
            .task {
                guard !loaded else { return }
                host = work.host ?? ""
                folder = startFolder
                mode = work.mode
                loaded = true
                async let hosts: Void = state.remoteHosts.isEmpty ? state.loadHosts() : ()
                if let server = state.server, let i = try? await server.chatAgentInfo(sid: sid) {
                    info = i
                    addDirs = i.addDirs
                }
                await hosts
            }
        }
    }

    private func save() async {
        guard let server = state.server else { return }
        saving = true
        error = nil
        defer { saving = false }
        do {
            if placeChanged || dirsChanged {
                try await server.setWork(sid: sid, host: work.started ? (work.host ?? "") : host,
                                         cwd: folder.trimmingCharacters(in: .whitespacesAndNewlines),
                                         addDirs: info != nil ? addDirs : nil)
            }
            if mode != work.mode {
                try await server.setPermissionMode(sid: sid, mode: mode)
            }
            Haptics.success()
            await onSaved()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
