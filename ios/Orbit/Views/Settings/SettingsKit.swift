import SwiftUI

/// Small pieces the Mac-settings screens share: reaching the server, a brief
/// note at the bottom, a loading row, and the permission-mode names.

extension AppState {
    /// The paired Mac, or a clear error when there isn't one.
    func requireServer() throws -> OrbitServer {
        guard let server else { throw OrbitServer.Failure.notPaired }
        return server
    }
}

/// A capsule at the bottom that clears itself — the phone's version of the web page's toast.
struct NoteOverlay: ViewModifier {
    @Binding var note: String?

    func body(content: Content) -> some View {
        content
            .overlay(alignment: .bottom) {
                if let note, !note.isEmpty {
                    Text(note)
                        .font(.footnote.weight(.medium))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(.thinMaterial, in: .capsule)
                        .padding(.horizontal, 16).padding(.bottom, 12)
                        .transition(.opacity)
                }
            }
            .task(id: note) {
                guard note != nil else { return }
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                withAnimation { note = nil }
            }
    }
}

extension View {
    func settingsNote(_ note: Binding<String?>) -> some View { modifier(NoteOverlay(note: note)) }
}

struct LoadingRow: View {
    var text = "Asking the Mac"
    var body: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.mini)
            Text(text).font(.footnote).foregroundStyle(.secondary)
        }
    }
}

struct ErrorRow: View {
    let message: String
    var body: some View {
        Label(message, systemImage: "exclamationmark.triangle")
            .font(.footnote).foregroundStyle(.orange)
    }
}

/// A value going into a secret: typed, sent, and wiped from the field. The
/// stored key is never fetched or shown, only whether one is set.
struct SecretEntry: View {
    let placeholder: String
    var buttonTitle = "Save"
    let onSave: (String) async -> Bool
    @State private var value = ""
    @State private var busy = false

    var body: some View {
        HStack {
            SecureField(placeholder, text: $value)
                .textContentType(.password)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            Button {
                let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !v.isEmpty else { return }
                busy = true
                Task {
                    if await onSave(v) { value = "" }
                    busy = false
                }
            } label: {
                if busy { ProgressView().controlSize(.mini) } else { Text(buttonTitle) }
            }
            .buttonStyle(.borderless)
            .disabled(busy || value.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }
}

/// Claude Code's and Codex's permission modes, as the web page names them.
enum PermissionModes {
    static let labels: [(id: String, label: String)] = [
        ("default", "Ask"), ("acceptEdits", "Accept edits"), ("plan", "Plan"),
        ("auto", "Auto"), ("dontAsk", "Don't ask"), ("bypassPermissions", "Bypass"),
    ]
    static func label(_ id: String) -> String { labels.first { $0.id == id }?.label ?? id }
}

/// "%d%% left, resets Tue 14:00" for a usage window.
func resetText(_ d: Date?) -> String {
    guard let d else { return "" }
    return "resets " + d.formatted(.dateTime.weekday(.abbreviated).hour().minute())
}

/// Split a shell-ish command line into argv, honouring double quotes.
func splitCommand(_ s: String) -> [String] {
    var out: [String] = []
    var cur = ""
    var quoted = false
    var had = false
    for ch in s {
        if ch == "\"" { quoted.toggle(); had = true; continue }
        if ch.isWhitespace && !quoted {
            if had || !cur.isEmpty { out.append(cur) }
            cur = ""; had = false
        } else { cur.append(ch) }
    }
    if had || !cur.isEmpty { out.append(cur) }
    return out
}

/// Number of minutes/days etc. edited as text, blank-safe.
struct IntField: View {
    let title: String
    @Binding var value: Int
    var suffix: String = ""

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            TextField("0", value: $value, format: .number)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.trailing)
                .frame(maxWidth: 90)
            if !suffix.isEmpty { Text(suffix).foregroundStyle(.secondary) }
        }
    }
}
