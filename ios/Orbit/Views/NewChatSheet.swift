import SwiftUI

/// "New chat with…": the harness, model, machine, folder and permission mode
/// chosen together, all set on the Mac before the first message goes out.
struct NewChatSheet: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    /// Called with the new chat's id once it is ready to open.
    var onCreated: (String) -> Void

    @State private var harness: HarnessKind = .orbit
    @State private var model: String?
    @State private var host = ""
    @State private var folder = ""
    @State private var mode: PermissionMode = .auto
    @State private var ready = false
    @State private var creating = false
    @State private var error: String?
    /// A chat an earlier attempt made before something was refused — reused,
    /// so trying again does not leave empty chats behind.
    @State private var madeSid: String?
    // presets (Views/Chat/ChatPresets.swift)
    @State private var presets: [ChatPreset] = []
    /// Whether `presets` is the Mac's list. The Mac replaces the whole list on a
    /// save, so a save from a list that never loaded would wipe it.
    @State private var presetsLoaded = false
    @State private var presetName = ""

    private var modelName: String {
        guard let model else { return "Choose a model" }
        return state.models.first { $0.id == model }?.display ?? model
    }

    var body: some View {
        NavigationStack {
            Form {
                if !presets.isEmpty {
                    ChatPresetsSection(presets: $presets, disabled: creating || !ready) { p in
                        Task { await start(p) }
                    }
                }

                Section {
                    Picker("Harness", selection: Binding(get: { harness }, set: { switchHarness($0) })) {
                        ForEach(HarnessKind.allCases) { Text($0.label).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                } footer: {
                    Text(harnessNote)
                }

                Section("Model") {
                    NavigationLink {
                        ModelPickerView(only: { [harness] in HarnessKind(modelID: $0.id) == harness },
                                        selected: model,
                                        title: "\(harness.label) models",
                                        onPick: { model = $0.id },
                                        embedded: true)
                    } label: {
                        LabeledContent("Model") {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(modelName).lineLimit(1)
                                    .foregroundStyle(model == nil ? .orange : .secondary)
                                ModelAllowanceLine(modelID: model)
                            }
                        }
                    }
                }

                if harness.isAgent {
                    WorkPlaceSections(host: $host, folder: $folder, harness: harness)
                    PermissionModeSection(mode: $mode, harness: harness)
                }

                SavePresetSection(name: $presetName)

                if let error {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                        if madeSid != nil {
                            Text("The chat was made but not fully set up. Fix this and tap Create "
                                 + "again, or Cancel to remove it.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("New chat with…")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { cancel() }.disabled(creating)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if creating {
                        ProgressView()
                    } else {
                        Button("Create") { Task { await create() } }
                            .disabled(!ready || model == nil)
                    }
                }
            }
            .interactiveDismissDisabled(creating || madeSid != nil)
            .task { await prepare() }
            .onChange(of: state.models.count) { _, _ in
                if ready, model == nil { model = state.suggestedModel(for: harness) }
            }
        }
    }

    private var harnessNote: String {
        switch harness {
        case .orbit:
            return "Orbit's own agent on your Mac, with any model."
        case .claude:
            return "Claude Code runs the chat — on your Mac or an SSH host — with the model you pick."
        case .codex:
            return "Codex runs the chat — on your Mac or an SSH host — with the model you pick."
        }
    }

    /// Start from what the Mac would do anyway: its harness, its model in that
    /// harness, its default machine, folder and permission mode.
    private func prepare() async {
        guard !ready else { return }
        // opened straight after launch the Mac may not have listed its models yet
        if state.models.isEmpty { await state.loadModels() }
        harness = state.harnessMode
        model = state.suggestedModel(for: harness)
        async let hosts: Void = state.loadHosts()
        async let saved = try? state.server?.chatPresets()
        let defaults = try? await state.server?.chatWork(sid: "")
        await hosts
        if let list = await saved ?? nil {
            presets = list
            presetsLoaded = true
        }
        if let d = defaults {
            mode = d.defaultMode
            if let h = d.defaultHost {
                host = h
                folder = state.remoteHosts.first { $0.host == h }?.defaultDir ?? "~"
            } else if let dir = d.defaultDir {
                folder = dir
            }
        }
        ready = true
        #if DEBUG
        // development only: preselect a harness so the simulator can be screenshotted
        if let h = ProcessInfo.processInfo.environment["ORBIT_NEW_CHAT_HARNESS"],
           let kind = HarnessKind(rawValue: h) { switchHarness(kind) }
        #endif
    }

    private func switchHarness(_ kind: HarnessKind) {
        guard kind != harness else { return }
        harness = kind
        if HarnessKind(modelID: model) != kind { model = state.suggestedModel(for: kind) }
    }

    private func create() async {
        guard state.server != nil else { return }
        creating = true
        error = nil
        defer { creating = false }
        let sid: String
        if let madeSid { sid = madeSid }
        else {
            guard let made = await state.newChat() else {
                error = state.lastError ?? "Your Mac didn't start a chat."
                return
            }
            sid = made
            madeSid = made
        }
        do {
            try await state.configureChat(sid, model: model, harness: harness, host: host,
                                          folder: folder, mode: harness.isAgent ? mode : nil)
            await savePresetIfNamed()
            Haptics.success()
            madeSid = nil
            dismiss()
            onCreated(sid)
        } catch {
            self.error = error.localizedDescription
        }
    }

    // ------------------------------------------------------------ presets

    /// Start straight from a preset, as the Mac's "start" does.
    private func start(_ p: ChatPreset) async {
        creating = true
        error = nil
        defer { creating = false }
        if let sid = madeSid {
            // an empty chat an earlier Create left behind
            await state.delete(sid)
            madeSid = nil
        }
        state.lastError = nil
        guard let sid = await state.startChat(from: p) else {
            error = state.lastError ?? "Your Mac didn't start a chat."
            return
        }
        if let e = state.lastError { state.toast("Started, but not fully set up: \(e)") }
        Haptics.success()
        dismiss()
        onCreated(sid)
    }

    /// With a name typed, this sheet's choices are saved as a preset. A failure
    /// to save does not stop the chat.
    private func savePresetIfNamed() async {
        let name = presetName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, let server = state.server else { return }
        let p = ChatPreset(name: name, model: model ?? "",
                           cwd: harness.isAgent ? folder.trimmingCharacters(in: .whitespacesAndNewlines) : "",
                           mode: harness.isAgent ? mode.rawValue : "",
                           host: harness.isAgent ? host : "")
        do {
            if !presetsLoaded {
                // not read yet, or the read failed: read them now rather than overwrite them
                presets = try await server.chatPresets()
                presetsLoaded = true
            }
            try await server.savePresets(presets + [p])
            presetName = ""
        } catch {
            state.toast("The preset wasn't saved: \(error.localizedDescription)")
        }
    }

    private func cancel() {
        if let sid = madeSid {
            // an empty chat this sheet made and never finished setting up
            Task { await state.delete(sid) }
        }
        dismiss()
    }
}
