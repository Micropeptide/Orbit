import SwiftUI

/// Search in Settings: every page and the settings on it, by the words you would use
/// for them. A hit on a page opens it; a hit on this screen scrolls to it.
struct SettingsSearchEntry: Identifiable {
    enum Target { case here(String), page(() -> AnyView) }
    let id = UUID()
    let title: String
    let place: String
    let words: String
    let target: Target

    func matches(_ term: String) -> Bool {
        let t = term.lowercased()
        return title.lowercased().contains(t) || words.contains(t) || place.lowercased().contains(t)
    }
}

enum SettingsIndex {
    static func page<V: View>(_ v: @autoclosure @escaping () -> V) -> SettingsSearchEntry.Target {
        .page { AnyView(v()) }
    }

    /// This screen's sections, by hand (they live in one file and rarely change), then every
    /// page of the Mac's settings with the words on it, generated on each build from the
    /// screens themselves (scripts/gen-settings-index), plus a few words people use for them.
    static let all: [SettingsSearchEntry] = here + generated.map { e in
        SettingsSearchEntry(title: e.title, place: e.place,
                            words: e.words + " " + (synonyms[e.title] ?? ""), target: e.target)
    }

    static let synonyms: [String: String] = [
        "Models & keys": "api key provider openai anthropic deepseek opencode hidden removed",
        "When a model keeps failing": "fallback retry usage limit",
        "General": "side work helper model reviewer review fix verify check auto-compact quiet recycle bin goal offer",
        "Tools & rules": "permissions allow deny shell write anywhere code execution screen control",
        "Phone access": "pairing qr code token devices revoke unpair tailscale network",
        "Status & health": "doctor diagnostics launch flags",
    ]

    static let here: [SettingsSearchEntry] = [
        // this screen
        .init(title: "Model server", place: "Settings", words: "local model start stop restart mtplx memory", target: .here("server")),
        .init(title: "How chats run", place: "Settings", words: "harness engine claude code codex orbit mode", target: .here("harness")),
        .init(title: "Autonomy", place: "Settings", words: "auto ask full access approve permissions reviewer", target: .here("autonomy")),
        .init(title: "Backup", place: "Settings", words: "backup restore export", target: .here("backup")),
        .init(title: "Default model", place: "Settings", words: "new chats use model default", target: .here("default")),
        .init(title: "Connected to", place: "Settings", words: "mac address reachable latency diagnostics check again", target: .here("connected")),
        .init(title: "Appearance", place: "Settings", words: "theme dark light text size answer text code output haptics", target: .here("appearance")),
        .init(title: "Require Face ID", place: "Settings", words: "face id passcode lock privacy lock screen notifications", target: .here("faceid")),
        .init(title: "Shared projects", place: "Settings", words: "shared project collaborate team people members share chat", target: .here("shared")),
        .init(title: "Bin", place: "Settings", words: "bin trash restore deleted recycle", target: .here("bin")),
        .init(title: "Offline copy", place: "Settings", words: "offline cache clear", target: .here("offline")),
        .init(title: "Unpair this phone", place: "Settings", words: "unpair pairing token forget", target: .here("unpair")),
        .init(title: "User guide", place: "Settings", words: "help guide how to manual instructions", target: .here("about")),
        .init(title: "About Orbit", place: "Settings", words: "about version licence license author runtian", target: .here("about")),
    ]
}

struct SettingsSearchResults: View {
    let term: String
    let jump: (String) -> Void
    @Environment(\.dismissSearch) private var dismissSearch

    private var hits: [SettingsSearchEntry] {
        SettingsIndex.all.filter { $0.matches(term.trimmingCharacters(in: .whitespaces)) }
    }

    var body: some View {
        Section {
            if hits.isEmpty {
                Text("Nothing in Settings matches “\(term)”").foregroundStyle(.secondary)
            }
            ForEach(hits) { e in
                switch e.target {
                case .here(let id):
                    Button { dismissSearch(); jump(id) } label: { row(e) }
                        .foregroundStyle(.primary)
                case .page(let make):
                    NavigationLink { make() } label: { row(e) }
                }
            }
        } header: {
            Text("Results")
        }
    }

    private func row(_ e: SettingsSearchEntry) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(e.title)
            Text(e.place).font(.caption).foregroundStyle(.secondary)
        }
    }
}
