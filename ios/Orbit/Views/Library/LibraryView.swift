import SwiftUI

/// The parts of the Library, each its own screen.
enum LibrarySection: String, CaseIterable, Identifiable {
    case prompts, knowledge, agents, skills, memory, claudeMemory, systemPrompt
    var id: String { rawValue }

    var title: String {
        switch self {
        case .prompts:      return "Saved prompts"
        case .knowledge:    return "Knowledge"
        case .agents:       return "Agents"
        case .skills:       return "Skills"
        case .memory:       return "Memory & instructions"
        case .claudeMemory: return "Claude Code memory"
        case .systemPrompt: return "System prompt"
        }
    }

    var icon: String {
        switch self {
        case .prompts:      return "text.bubble"
        case .knowledge:    return "books.vertical"
        case .agents:       return "person.crop.rectangle.stack"
        case .skills:       return "list.bullet.clipboard"
        case .memory:       return "brain"
        case .claudeMemory: return "sparkles"
        case .systemPrompt: return "doc.plaintext"
        }
    }

    var blurb: String {
        switch self {
        case .prompts:      return "become slash commands"
        case .knowledge:    return "searched before the web"
        case .agents:       return "instructions plus a tool set"
        case .skills:       return "procedures loaded on demand"
        case .memory:       return "in every Orbit chat"
        case .claudeMemory: return "CLAUDE.md and Claude's notes"
        case .systemPrompt: return "what the model is told first"
        }
    }

    @ViewBuilder func destination(sid: String? = nil) -> some View {
        switch self {
        case .prompts:      PromptsView()
        case .knowledge:    KnowledgeView()
        case .agents:       AgentsView()
        case .skills:       SkillsView()
        case .memory:       MemoryView()
        case .claudeMemory: ClaudeMemoryView(sid: sid)
        case .systemPrompt: SystemPromptView()
        }
    }
}

/// The Library tab: what Orbit knows and how it behaves, kept on the Mac.
struct LibraryView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach([LibrarySection.prompts, .knowledge, .agents, .skills]) { row($0) }
                }
                Section {
                    ForEach([LibrarySection.memory, .claudeMemory, .systemPrompt]) { row($0) }
                } header: {
                    Text("Memory and instructions")
                } footer: {
                    Text("Orbit chats use Orbit's memory and instructions. Chats that run through "
                         + "Claude Code use Claude's own files, the same ones a terminal session reads.")
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) { ConnectionBanner() }
            .navigationTitle("Library")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func row(_ s: LibrarySection) -> some View {
        NavigationLink {
            s.destination(sid: state.openChat?.sid)
        } label: {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(s.title)
                    Text(s.blurb).font(.caption).foregroundStyle(.secondary)
                }
            } icon: {
                Image(systemName: s.icon)
            }
        }
    }
}

/// One Library screen in a sheet, opened from a slash command or a chat's menu.
struct LibrarySheet: View {
    let section: LibrarySection
    var sid: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            section.destination(sid: sid)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
    }
}

// ------------------------------------------------------------ shared bits

/// A short line at the bottom of a Library screen: saved, deleted, or what went wrong.
struct LibraryNote: ViewModifier {
    @Binding var note: String?

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            if let note {
                Text(note).font(.footnote.weight(.medium))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.thinMaterial, in: .capsule)
                    .padding(.bottom, 16).padding(.horizontal, 16)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .task(id: note) {
                        try? await Task.sleep(nanoseconds: 2_500_000_000)
                        withAnimation { self.note = nil }
                    }
            }
        }
        .animation(.default, value: note)
    }
}

extension View {
    func libraryNote(_ note: Binding<String?>) -> some View { modifier(LibraryNote(note: note)) }
}

/// A multi-line text field that grows, in a Form row.
struct LibraryTextEditor: View {
    var placeholder: String
    @Binding var text: String
    var minHeight: CGFloat = 160
    var monospaced = false

    var body: some View {
        ZStack(alignment: .topLeading) {
            if text.isEmpty {
                Text(placeholder).foregroundStyle(.tertiary)
                    .padding(.top, 8).padding(.leading, 5)
                    .allowsHitTesting(false)
            }
            TextEditor(text: $text)
                .font(monospaced ? .footnote.monospaced() : .body)
                .frame(minHeight: minHeight)
                .scrollContentBackground(.hidden)
        }
    }
}

/// Names the Mac saves under: letters, digits, - and _.
enum LibraryNames {
    static func safe(_ s: String) -> String {
        String(s.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) || $0 == "-" || $0 == "_" }
            .map(Character.init))
    }

    static func ago(_ secs: Double?) -> String {
        guard let secs else { return "" }
        return RelativeDateTimeFormatter().localizedString(for: Date(timeIntervalSince1970: secs),
                                                           relativeTo: Date())
    }
}
