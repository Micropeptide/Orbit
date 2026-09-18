import SwiftUI

/// Workspace files and knowledge documents for the `@` menu, fetched once and
/// kept for a minute so typing `@` answers at once.
@MainActor
final class MentionCatalog: ObservableObject {
    static let shared = MentionCatalog()

    @Published private(set) var files: [MentionFile] = []
    private var fetchedAt: Date?

    func refresh(_ server: OrbitServer?) async {
        guard let server, fetchedAt.map({ Date().timeIntervalSince($0) > 60 }) ?? true else { return }
        fetchedAt = Date()
        var out: [MentionFile] = []
        if let f = try? await server.files(limit: 300) {
            out += f.map { MentionFile(name: $0.name, rel: $0.rel, area: $0.area ?? "") }
        }
        if let k = try? await server.knowledge() {
            out += k.map { MentionFile(name: $0.name, rel: "knowledge/" + $0.name, area: "knowledge") }
        }
        files = out
    }

    /// The `@word` being typed at the end of the draft, if any ("" right after the @).
    static func term(in draft: String) -> String? {
        guard let at = draft.lastIndex(of: "@") else { return nil }
        let word = draft[draft.index(after: at)...]
        guard !word.contains(where: { $0.isWhitespace || $0 == "@" }) else { return nil }
        // an e-mail address is not a mention
        if at > draft.startIndex, !draft[draft.index(before: at)].isWhitespace { return nil }
        return String(word)
    }
}

/// The `@` menu above the message box: pick a file and its path goes in the message.
struct MentionMenu: View {
    @EnvironmentObject var state: AppState
    @Binding var draft: String
    @ObservedObject private var catalog = MentionCatalog.shared

    private var term: String? { MentionCatalog.term(in: draft) }

    private var hits: [MentionFile] {
        guard let term else { return [] }
        let t = term.lowercased()
        return Array(catalog.files.filter { t.isEmpty || $0.name.lowercased().contains(t) }.prefix(8))
    }

    var body: some View {
        let hits = hits
        Group {
            if !hits.isEmpty {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(hits) { f in
                            Button {
                                Haptics.tap()
                                pick(f)
                            } label: {
                                HStack(spacing: 8) {
                                    Text("@" + f.name).font(.callout.monospaced().weight(.semibold))
                                        .lineLimit(1).layoutPriority(1)
                                    Text(f.area).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                    Spacer(minLength: 4)
                                }
                                .padding(.horizontal, 12).frame(minHeight: 45)
                                .contentShape(.rect)
                            }
                            .buttonStyle(.plain)
                            Divider().padding(.leading, 12)
                        }
                    }
                }
                .frame(maxHeight: min(CGFloat(hits.count) * 46, 230))
                .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 12))
                .padding(.horizontal, 12).padding(.top, 8)
            }
        }
        .task(id: term != nil) {
            if term != nil { await catalog.refresh(state.server) }
        }
    }

    /// `@wor` becomes the file's workspace path, ready for the next word.
    private func pick(_ f: MentionFile) {
        guard let at = draft.lastIndex(of: "@") else { return }
        draft = String(draft[..<at]) + f.rel + " "
    }
}
