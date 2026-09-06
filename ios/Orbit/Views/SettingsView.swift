import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var confirmUnpair = false

    var body: some View {
        NavigationStack {
            List {
                ServerControlView()

                Section {
                    Picker("New chats use", selection: Binding(
                        get: { state.defaultModel ?? state.currentModel ?? "" },
                        set: { id in Task { await state.setDefaultModel(id) } })) {
                        ForEach(state.models.filter(\.isReady)) { m in
                            Text(m.display).tag(m.id)
                        }
                    }
                } header: {
                    Text("Default model")
                } footer: {
                    Text("Each chat can still pick its own from the label above the message box.")
                }

                Section {
                    LabeledContent("Mac", value: state.pairing?.name ?? "—")
                    LabeledContent("Address") {
                        Text(state.pairing?.url ?? "—")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                    }
                    HStack {
                        Text("Reachable")
                        Spacer()
                        switch state.reachable {
                        case .some(true):
                            Label("yes", systemImage: "checkmark.circle.fill")
                                .foregroundStyle(.green).labelStyle(.titleAndIcon)
                        case .some(false):
                            Label("no", systemImage: "xmark.circle.fill")
                                .foregroundStyle(.red).labelStyle(.titleAndIcon)
                        case .none:
                            ProgressView().controlSize(.mini)
                        }
                    }
                    if let e = state.lastError {
                        Text(e).font(.caption).foregroundStyle(.secondary)
                    }
                    Button("Check again") {
                        Task { await state.refreshEverything(); await state.refreshServer() }
                    }
                } header: {
                    Text("Connected to")
                }

                Section {
                    LabeledContent("Chats held locally", value: "\(state.chats.count)")
                    Button("Clear the offline copy") {
                        Cache.clear()
                        Task { await state.refreshEverything() }
                    }
                } header: {
                    Text("Offline")
                } footer: {
                    Text("Your Mac is the only place chats are stored. This app keeps a "
                         + "read-only copy so it opens to something when the Mac is asleep.")
                }

                Section {
                    Button("Unpair this phone", role: .destructive) { confirmUnpair = true }
                } footer: {
                    Text("Removes the token from this phone's Keychain and deletes the "
                         + "offline copy. Nothing on your Mac changes.")
                }

                Section {
                    LabeledContent("Version",
                                   value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—")
                    Link(destination: URL(string: "https://github.com/Micropeptide/Orbit")!) {
                        LabeledContent("Source", value: "github.com/Micropeptide/Orbit")
                    }
                } header: {
                    Text("About")
                } footer: {
                    Text("Built by Micropeptide · MIT licensed")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .task { await state.refreshServer() }
            .refreshable { await state.refreshEverything(); await state.refreshServer() }
            .confirmationDialog("Unpair this phone?", isPresented: $confirmUnpair,
                                titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { state.unpair() }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
