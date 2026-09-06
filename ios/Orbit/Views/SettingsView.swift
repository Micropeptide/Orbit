import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var confirmUnpair = false

    var body: some View {
        NavigationStack {
            List {
                Section("Connected to") {
                    LabeledContent("Mac", value: state.pairing?.name ?? "—")
                    LabeledContent("Address", value: state.pairing?.url ?? "—")
                        .font(.caption.monospaced())
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
                    Button("Check again") { Task { await state.refreshEverything() } }
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
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .confirmationDialog("Unpair this phone?", isPresented: $confirmUnpair,
                                titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { state.unpair() }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
