import SwiftUI

/// The local model server on the Mac — what it is doing, and the switches.
///
/// Starting it loads ~20 GB of weights and takes about fifteen seconds;
/// stopping frees that memory. Switching model rewrites the launch config on
/// the Mac and restarts. All of it happens over there; this is the remote.
struct ServerControlView: View {
    @EnvironmentObject var state: AppState
    @State private var confirmSwitch: String?

    private var srv: LocalServer { state.localServer }

    var body: some View {
        Section {
            HStack(spacing: 12) {
                Circle()
                    .fill(srv.running ? Color.green : Color.secondary.opacity(0.4))
                    .frame(width: 10, height: 10)
                    .overlay {
                        if srv.busy { ProgressView().controlSize(.mini) }
                    }
                VStack(alignment: .leading, spacing: 2) {
                    Text(srv.running ? "Running" : "Stopped")
                        .font(.body.weight(.medium))
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }

            HStack(spacing: 10) {
                if srv.running {
                    button("Stop", "stop.fill", role: .destructive) {
                        await state.serverAction(.stop)
                    }
                    button("Restart", "arrow.clockwise") {
                        await state.serverAction(.restart)
                    }
                } else {
                    button("Start", "play.fill") {
                        await state.serverAction(.start)
                    }
                }
            }
            .disabled(srv.busy)

            if let note = srv.note, !note.isEmpty {
                Text(note).font(.caption).foregroundStyle(.secondary)
            }
        } header: {
            Text("Local model")
        } footer: {
            Text(srv.running
                 ? "Stopping frees the memory the weights hold. The next message starts it again."
                 : "Starting takes about fifteen seconds while the weights load. "
                   + "It also starts on its own when a chat needs it.")
        }

        if srv.installed.count > 1 || (srv.installed.count == 1 && srv.serving == nil) {
            Section {
                ForEach(srv.installed, id: \.self) { folder in
                    let isCurrent = (srv.serving ?? "").localizedCaseInsensitiveContains(shortName(folder))
                    Button {
                        if !isCurrent { confirmSwitch = folder }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(shortName(folder)).foregroundStyle(.primary)
                                Text(folder).font(.caption2).foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            Spacer()
                            if isCurrent {
                                Image(systemName: "checkmark").foregroundStyle(.tint)
                            }
                        }
                    }
                    .disabled(srv.busy)
                }
            } header: {
                Text("Installed on the Mac")
            } footer: {
                Text("Choosing another model restarts the server with it. "
                     + "Download more through MTPLX on the Mac.")
            }
        } else if srv.installed.count == 1 {
            Section("Installed on the Mac") {
                LabeledContent("Model", value: shortName(srv.installed[0]))
                Text("Only one model is installed. Download more through MTPLX on the Mac "
                     + "and they will appear here.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var subtitle: String {
        var parts: [String] = []
        if let m = srv.model, !m.isEmpty { parts.append(m) }
        if let g = srv.memoryGB, g > 0 { parts.append(String(format: "%.1f GB", g)) }
        return parts.isEmpty ? "on \(state.pairing?.name ?? "your Mac")"
                             : parts.joined(separator: " · ")
    }

    private func shortName(_ folder: String) -> String {
        // "Youssofal--Qwen3.8-27B-MTPLX-Bare-Speed" -> "Qwen3.8-27B-MTPLX-Bare-Speed"
        folder.components(separatedBy: "--").last ?? folder
    }

    private func button(_ title: String, _ symbol: String, role: ButtonRole? = nil,
                        action: @escaping () async -> Void) -> some View {
        Button(role: role) {
            Haptics.press()
            Task { await action() }
        } label: {
            Label(title, systemImage: symbol)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.bordered)
        .confirmationDialog("Switch model?", isPresented: Binding(
            get: { confirmSwitch != nil }, set: { if !$0 { confirmSwitch = nil } }),
            titleVisibility: .visible) {
            if let f = confirmSwitch {
                Button("Restart with \(shortName(f))") {
                    Task { await state.switchLocalModel(f) }
                    confirmSwitch = nil
                }
            }
            Button("Cancel", role: .cancel) { confirmSwitch = nil }
        } message: {
            Text("Anything generating right now will stop.")
        }
    }
}
