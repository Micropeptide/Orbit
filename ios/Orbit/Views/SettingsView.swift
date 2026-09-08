import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: AppState
    @State private var confirmUnpair = false
    @State private var copied = false
    @AppStorage("theme") private var theme = "system"
    @AppStorage("textSize") private var textSize = "default"
    @AppStorage("haptics") private var haptics = true
    @AppStorage("faceID") private var faceID = false

    private var diagnostics: String {
        let b = Bundle.main.infoDictionary
        let srv = state.localServer
        return [
            "Orbit iOS \(b?["CFBundleShortVersionString"] as? String ?? "?") (\(b?["CFBundleVersion"] as? String ?? "?"))",
            "iOS \(UIDevice.current.systemVersion) · \(UIDevice.current.model)",
            "Mac: \(state.pairing?.name ?? "—") at \(state.pairing?.url ?? "—")",
            "Reachable: \(state.reachable.map { $0 ? "yes" : "no" } ?? "unknown")"
                + (state.latencyMS.map { " · \($0) ms" } ?? ""),
            "Model server: \(srv.running ? "running" : "stopped")"
                + (srv.model.map { " · \($0)" } ?? "")
                + (srv.memoryGB.map { String(format: " · %.1f GB", $0) } ?? ""),
            "Models listed: \(state.models.count) · default: \(state.defaultModel ?? "—")",
            "Chats: \(state.chats.count) · projects: \(state.projects.count)",
            "Backup: " + (state.backup.map { ($0.enabled ? "on" : "off") + " · last " + ($0.last?.name ?? "never") } ?? "unknown"),
            "Autonomy: " + (state.autonomy?.autonomy_mode ?? "unknown"),
            "Last error: \(state.lastError ?? "none")",
        ].joined(separator: "\n")
    }

    var body: some View {
        NavigationStack {
            List {
                ServerControlView()
                AutonomySection()
                BackupSection()

                Section {
                    Picker("New chats use", selection: Binding(
                        get: { state.catalogueID(for: state.defaultModel) ?? state.effectiveModelID ?? "" },
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
                            Label(state.latencyMS.map { "yes · \($0) ms" } ?? "yes",
                                  systemImage: "checkmark.circle.fill")
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
                    Button(copied ? "Copied" : "Copy diagnostics") {
                        UIPasteboard.general.string = diagnostics
                        Haptics.success()
                        copied = true
                        Task { try? await Task.sleep(nanoseconds: 1_500_000_000); copied = false }
                    }
                } header: {
                    Text("Connected to")
                } footer: {
                    Text("Diagnostics is a short text report — versions, address, model server, "
                         + "last error — with no chat content and no token.")
                }

                Section {
                    Picker("Theme", selection: $theme) {
                        Text("System").tag("system"); Text("Light").tag("light"); Text("Dark").tag("dark")
                    }
                    Picker("Answer text", selection: $textSize) {
                        Text("Default").tag("default"); Text("Large").tag("large")
                        Text("Extra large").tag("xlarge")
                    }
                    Toggle("Haptics", isOn: $haptics)
                } header: {
                    Text("Appearance")
                }

                Section {
                    Toggle("Require Face ID", isOn: $faceID)
                } footer: {
                    Text("Asks for Face ID or your passcode whenever Orbit comes to the front. "
                         + "If the phone can't check, it doesn't lock.")
                }

                Section {
                    NavigationLink("Bin") { BinView() }
                } header: {
                    Text("Bin on the Mac")
                } footer: {
                    Text("Chats and files you binned. Restore puts them back where they were; "
                         + "the Mac purges the bin on its own schedule.")
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
                    NavigationLink {
                        AboutView()
                    } label: {
                        LabeledContent("About Orbit", value: "by Micropeptide")
                    }
                    LabeledContent("Version",
                                   value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—")
                } header: {
                    Text("About")
                } footer: {
                    Text("Made by Micropeptide · MIT licensed")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .task { await state.refreshServer(); await state.refreshBackup(); await state.refreshAutonomy() }
            .refreshable {
                await state.refreshEverything(); await state.refreshServer()
                await state.refreshBackup(); await state.refreshAutonomy()
            }
            .confirmationDialog("Unpair this phone?", isPresented: $confirmUnpair,
                                titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { state.unpair() }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
