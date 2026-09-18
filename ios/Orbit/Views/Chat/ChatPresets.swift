import SwiftUI

/// "New chat with…" presets: a model, machine, folder and permission mode saved
/// under a name, to start the same kind of chat again in one tap. They live in
/// Orbit's Claude Code settings on the Mac, so the web page has the same list.
struct ChatPresetsSection: View {
    @EnvironmentObject var state: AppState
    @Binding var presets: [ChatPreset]
    var disabled = false
    var onStart: (ChatPreset) -> Void
    @State private var deleting: ChatPreset?

    var body: some View {
        Section {
            ForEach(presets) { p in
                Button { onStart(p) } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "bookmark.fill").foregroundStyle(Color.accentColor)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.name).foregroundStyle(.primary)
                            Text(summary(p)).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                        Spacer(minLength: 0)
                        Text("Start").font(.caption.weight(.semibold)).foregroundStyle(.tint)
                    }
                }
                .disabled(disabled)
                .swipeActions {
                    Button(role: .destructive) { deleting = p } label: { Label("Delete", systemImage: "trash") }
                }
                .contextMenu {
                    Button { onStart(p) } label: { Label("Start chat", systemImage: "play") }
                    Button(role: .destructive) { deleting = p } label: { Label("Delete preset", systemImage: "trash") }
                }
            }
        } header: {
            Text("Presets")
        } footer: {
            Text("Tap one to start a chat set up that way. Swipe to delete.")
        }
        .confirmationDialog("Delete the preset “\(deleting?.name ?? "")”?",
                            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                            titleVisibility: .visible, presenting: deleting) { p in
            Button("Delete", role: .destructive) { Task { await delete(p) } }
            Button("Cancel", role: .cancel) {}
        }
    }

    /// "DeepSeek V4 · lab-host:~/analysis · Auto", as the Mac describes a preset.
    private func summary(_ p: ChatPreset) -> String {
        let model = p.model.isEmpty ? "default model" : (state.modelLabel(p.model) ?? p.model)
        let place = p.host.isEmpty ? p.cwd : "\(p.host):\(p.cwd.isEmpty ? "~" : p.cwd)"
        return [model, place, p.permissionMode?.label ?? ""].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func delete(_ p: ChatPreset) async {
        guard let server = state.server else { return }
        var list = presets
        list.removeAll { $0.id == p.id }
        do {
            try await server.savePresets(list)
            presets = list.enumerated().map { var x = $0.element; x.index = $0.offset; return x }
            state.toast("Preset deleted")
        } catch { state.lastError = error.localizedDescription }
    }
}

/// A name to save this sheet's choices under, as a preset.
struct SavePresetSection: View {
    @Binding var name: String

    var body: some View {
        Section {
            TextField("Name (optional), e.g. Lab analysis · DeepSeek", text: $name)
                .submitLabel(.done)
        } header: {
            Text("Save as preset")
        } footer: {
            Text("With a name, Create also saves the model, machine, folder and permission mode as a preset.")
        }
    }
}
