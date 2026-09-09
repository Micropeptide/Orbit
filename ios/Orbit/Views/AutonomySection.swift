import SwiftUI

/// How much Orbit can do on this Mac without stopping to ask you first —
/// mirrors the same three-way choice in the Mac's own Settings → Tools.
struct AutonomySection: View {
    @EnvironmentObject var state: AppState
    @State private var confirmFull = false
    @State private var confirmScreen = false

    private var mode: String { state.autonomy?.autonomy_mode ?? "ask" }
    private var screenOn: Bool { state.autonomy?.computer_use_enabled ?? false }

    var body: some View {
        Section {
            Picker("Autonomy", selection: Binding(
                get: { mode },
                set: { picked in
                    if picked == "full" { confirmFull = true }
                    else { Task { await state.setAutonomyMode(picked) } }
                })) {
                Text("Ask every time").tag("ask")
                Text("Auto-approve safe actions").tag("auto")
                Text("Full computer access").tag("full")
            }
            .pickerStyle(.navigationLink)
            .disabled(state.autonomyBusy)
            if let a = state.autonomy, mode == "full" {
                LabeledContent("Shell", value: (a.shell_enabled ?? false) ? "on" : "on from Full access")
                LabeledContent("Write anywhere", value: (a.write_any ?? false) ? "on" : "on from Full access")
                LabeledContent("The cluster", value: (a.cluster_write ?? false) ? "on" : "on from Full access")
            }
        } header: {
            Text("Autonomy")
        } footer: {
            Text(footer)
        }
        .confirmationDialog("Full computer access?", isPresented: $confirmFull, titleVisibility: .visible) {
            Button("Turn it on", role: .destructive) {
                Task { await state.setAutonomyMode("full") }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Lets Orbit run shell commands, write anywhere on your Mac, and reach the cluster "
                 + "without asking first — for the rest of the session, from any device. It still "
                 + "always asks before sudo, shutting down, the keychain, publishing a package, "
                 + "rewriting git history or force-pushing. It will never wipe a disk, run a fork "
                 + "bomb, open a reverse shell, kill every process, or touch a protected path like "
                 + "your home directory — no mode lifts those.")
        }

        Section {
            Toggle("Screen control", isOn: Binding(
                get: { screenOn },
                set: { on in if on { confirmScreen = true } else { Task { await state.setComputerUse(false) } } }))
                .disabled(state.autonomyBusy)
        } footer: {
            Text("Lets Orbit see your screen and click, type and press keys on the Mac — in any app, "
                 + "not just this project. Separate from Full access on purpose. Needs Screen Recording "
                 + "and Accessibility granted to it by hand in the Mac's System Settings; a click or "
                 + "keystroke still always asks first unless Full access is also on.")
        }
        .confirmationDialog("Turn on screen control?", isPresented: $confirmScreen, titleVisibility: .visible) {
            Button("Turn it on", role: .destructive) {
                Task { await state.setComputerUse(true) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Lets Orbit see your screen and click, type and press keys — in any app, not just "
                 + "this project. Needs Screen Recording and Accessibility granted on the Mac by hand. "
                 + "A click or keystroke still asks for your approval first unless Full access is on.")
        }
    }

    private var footer: String {
        switch mode {
        case "auto":
            return "File edits and deletions that stay inside the workspace run without asking; "
                 + "anything that reaches the rest of the Mac still asks."
        case "full":
            return "Everything short of a short hard-coded list of machine-wide actions runs without "
                 + "asking. Every action is still written to the Mac's safety log."
        default:
            return "The default — every risky action stops for your explicit approval, on whichever "
                 + "device answers it first."
        }
    }
}
