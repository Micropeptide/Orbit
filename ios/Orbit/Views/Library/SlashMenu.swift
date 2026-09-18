import SwiftUI

/// Saved prompts and Claude Code's commands, fetched once and kept for a while,
/// so typing "/" answers at once.
@MainActor
final class SlashCatalog: ObservableObject {
    static let shared = SlashCatalog()

    @Published private(set) var prompts: [SavedPrompt] = []
    @Published private(set) var claudeCommands: [ClaudeCommand] = []
    private var promptsAt: Date?
    private var claudeAt: Date?

    func invalidate() { promptsAt = nil }

    func refresh(_ server: OrbitServer?, claude: Bool) async {
        guard let server else { return }
        if promptsAt.map({ Date().timeIntervalSince($0) > 60 }) ?? true,
           let p = try? await server.prompts() {
            prompts = p
            promptsAt = Date()
        }
        if claude, claudeAt.map({ Date().timeIntervalSince($0) > 300 }) ?? true,
           let c = try? await server.claudeCommands() {
            claudeCommands = c
            claudeAt = Date()
        }
    }

    /// Whether the open chat answers through Claude Code — the same test the web uses.
    static func isClaudeChat(_ state: AppState) -> Bool {
        let m = state.currentModel ?? state.defaultModel ?? ""
        return m.hasPrefix("claude-qwen-cli") || m.hasPrefix("harness:")
    }
}

/// One line of the "/" menu.
struct SlashItem: Identifiable, Hashable {
    enum Kind: Hashable { case builtin, library, prompt, claude }
    var command: String
    var detail: String
    var kind: Kind
    var id: String { "\(kind)\(command)" }
}

/// What a library command opens.
enum SlashSheet: Identifiable {
    case section(LibrarySection, sid: String?)
    case chat(String)
    /// `/export`: the chat as Markdown, for the share sheet.
    case share(URL)
    /// `/tools` and other answers too long for a line.
    case info(title: String, text: String)
    case doctor
    case shortcuts
    case history
    var id: String {
        switch self {
        case .section(let s, _): return "section." + s.rawValue
        case .chat(let sid):  return "chat." + sid
        case .share(let url): return "share." + url.absoluteString
        case .info(let t, _): return "info." + t
        case .doctor: return "doctor"
        case .shortcuts: return "shortcuts"
        case .history: return "history"
        }
    }
}

/// The composer's side of the Library: the "/" menu's contents, the commands
/// that open Library screens, and saved prompts expanding into the message box.
@MainActor
final class SlashController: ObservableObject {
    @Published var sheet: SlashSheet?
    @Published var note: String?

    /// Orbit commands that make sense on a phone, beyond the composer's own.
    static let libraryCommands: [(String, String)] = [
        ("/prompts", "saved prompts"), ("/knowledge", "your document library"),
        ("/agents", "agent presets"), ("/skills", "saved procedures"),
        ("/memory", "memory and instructions"),
        ("/agent", "choose this chat's agent"), ("/instructions", "this chat's own instructions"),
        ("/remember", "save a note to memory: /remember <text>"),
        ("/scheduled", "messages and tasks for later"), ("/files", "files named in this chat"),
        ("/rename", "rename this chat: /rename <title>"),
        ("/later", "send later: /later 21:30 <message>, /later tomorrow 9am …, /later daily 8:00 …"),
        ("/tasks", "everything running in the background — answers, queued messages, shell jobs"),
        ("/plan", "plan mode: it may read and think but change nothing"),
        ("/build", "leave plan mode: it may make changes again"),
        ("/export", "download this chat as markdown"),
        ("/tools", "list active tools"), ("/status", "server, memory, context"),
        ("/doctor", "check deps, disk, server, config for problems"),
        ("/settings", "open settings"),
        ("/start", "start the model server"), ("/restart", "restart the server (applies settings)"),
        ("/stop", "stop the model server (frees ~15 GB)"),
        ("/sound", "a sound with the notification when an answer finishes while you are away"),
        ("/history", "earlier messages you sent — pick one to send again"),
        ("/shortcuts", "every keyboard shortcut"),
    ]

    /// Commands that wait for words after them rather than running when picked.
    static let takesWords: Set<String> = ["/remember", "/rename", "/later"]

    func items(for draft: String, builtins: [(String, String)], catalog: SlashCatalog,
               claude: Bool) -> [SlashItem] {
        guard draft.hasPrefix("/"), !draft.contains(" "), !draft.contains("\n") else { return [] }
        let typed = draft.lowercased()
        var all: [SlashItem] = []
        var known = Set<String>()
        func add(_ c: String, _ d: String, _ k: SlashItem.Kind) {
            guard known.insert(c.lowercased()).inserted else { return }
            all.append(SlashItem(command: c, detail: d, kind: k))
        }
        for (c, d) in builtins { add(c, d, .builtin) }
        for (c, d) in Self.libraryCommands { add(c, d, .library) }
        for p in catalog.prompts {
            add("/" + p.name, p.desc.isEmpty ? "saved prompt" : p.desc, .prompt)
        }
        if claude {
            for c in catalog.claudeCommands {
                guard let n = c.name, !n.isEmpty else { continue }
                add("/" + n, String((c.description ?? "Claude Code").prefix(120)), .claude)
            }
        }
        return Self.rank(all, typed: typed)
    }

    /// Commands that start with what you typed first, then ones that contain it,
    /// then ones whose description does, then its letters in order — so /ctx
    /// still finds /context, as Claude Code's menu does.
    static func rank(_ all: [SlashItem], typed: String) -> [SlashItem] {
        var seen = Set<String>()
        var out: [SlashItem] = []
        func take(_ match: (SlashItem) -> Bool) {
            for item in all where match(item) && seen.insert(item.id).inserted { out.append(item) }
        }
        take { $0.command.lowercased().hasPrefix(typed) }
        let word = String(typed.dropFirst())
        guard !word.isEmpty else { return out }
        take { $0.command.lowercased().contains(word) }
        take { $0.detail.lowercased().contains(word) }
        take { item in
            var rest = Substring(item.command.lowercased().dropFirst())
            for ch in word {
                guard let i = rest.firstIndex(of: ch) else { return false }
                rest = rest[rest.index(after: i)...]
            }
            return true
        }
        return out
    }

    /// A typed "/command words" the Library handles. Returns the new message-box
    /// text (empty when the command ran), or nil to let the message go on as usual.
    func intercept(_ text: String, state: AppState) -> String? {
        let head = text.split(whereSeparator: { $0 == " " || $0 == "\n" }).first.map(String.init) ?? ""
        let rest = text.dropFirst(head.count).trimmingCharacters(in: .whitespacesAndNewlines)
        let name = String(head.dropFirst())
        if let p = SlashCatalog.shared.prompts.first(where: { $0.name == name }) {
            return PromptExpander.expand(p.text, rest: rest)
        }
        let sid = state.openChat?.sid
        switch head.lowercased() {
        case "/prompts":   sheet = .section(.prompts, sid: sid)
        case "/knowledge": sheet = .section(.knowledge, sid: sid)
        case "/agents":    sheet = .section(.agents, sid: sid)
        case "/skills":    sheet = .section(.skills, sid: sid)
        case "/memory":
            sheet = .section(SlashCatalog.isClaudeChat(state) ? .claudeMemory : .memory, sid: sid)
        case "/agent", "/instructions":
            guard let sid else { note = "Open a chat first"; return "" }
            sheet = .chat(sid)
        case "/scheduled": state.tab = "scheduled"
        case "/files":
            // in a chat, the chat's own list of the files it names (ChatView); elsewhere the Files tab
            if sid != nil { return nil }
            state.tab = "files"
        case "/remember":
            guard !rest.isEmpty else { return "/remember " }
            Task { await remember(rest, state: state) }
        case "/rename":
            guard let sid else { note = "Open a chat first"; return "" }
            guard !rest.isEmpty else { note = "Type the new title after /rename"; return "/rename " }
            Task {
                await state.rename(sid, to: rest)
                note = "Renamed to “\(rest)”"
            }
        case "/later":
            guard LaterParser.parse(rest).map({ !$0.text.isEmpty }) == true else {
                note = "Usage: " + LaterParser.usage
                return "/later " + rest
            }
            Task { _ = await state.sendLaterParsed(rest) }
        case "/tasks":     state.presentTasks()
        case "/plan", "/build":
            let on = head.lowercased() == "/plan"
            Task { if state.chatExtras.planMode != on { await state.setPlanMode(on) } }
        case "/export":
            guard let sid, let server = state.server else { note = "Open a chat first"; return "" }
            Task {
                do {
                    sheet = .share(try await server.exportMarkdown(sid, title: state.openChat?.title ?? "Chat"))
                } catch { note = error.localizedDescription }
            }
        case "/tools":
            Task {
                do {
                    let tools = try await state.server?.activeTools() ?? []
                    sheet = .info(title: "Active tools",
                                  text: tools.isEmpty ? "No tools are active." : tools.joined(separator: "\n"))
                } catch { note = error.localizedDescription }
            }
        case "/status":
            Task {
                do {
                    guard let s = try await state.server?.chatStatus(sid: sid) else { return }
                    var bits = [s.running ? "running" : "stopped"]
                    if let m = s.model, !m.isEmpty { bits.append(m) }
                    if let g = s.memoryGB { bits.append("\(g.formatted()) GB") }
                    if let c = s.context { bits.append("ctx \(c.used.formatted())/\(c.max.formatted())") }
                    note = bits.joined(separator: " · ")
                } catch { note = error.localizedDescription }
            }
        case "/doctor":    sheet = .doctor
        case "/settings":  state.tab = "settings"
        case "/start", "/stop", "/restart":
            let action: OrbitServer.ServerAction = head.lowercased() == "/stop" ? .stop
                : head.lowercased() == "/start" ? .start : .restart
            note = "\(action.rawValue == "stop" ? "stopping" : action.rawValue + "ing") the server…"
            Task {
                await state.serverAction(action)
                note = state.localServer.note ?? "done"
            }
        case "/sound":
            let on = !(UserDefaults.standard.object(forKey: "orbit.sound") as? Bool ?? true)
            UserDefaults.standard.set(on, forKey: "orbit.sound")
            note = on ? "Sound on — when an answer finishes while you are away" : "Sound off"
        case "/history":   sheet = .history
        case "/shortcuts": sheet = .shortcuts
        default: return nil
        }
        return ""
    }

    /// An `/unknown` command in one of Orbit's own chats: what it might have been.
    func unknownCommand(_ text: String, builtins: [(String, String)]) -> String {
        let head = (text.split(whereSeparator: { $0 == " " || $0 == "\n" }).first.map(String.init) ?? text).lowercased()
        let names = builtins.map(\.0) + Self.libraryCommands.map(\.0)
            + SlashCatalog.shared.prompts.map { "/" + $0.name }
        let near = names.filter { $0.lowercased().hasPrefix(head) }.prefix(4)
        return near.isEmpty ? "Unknown command \(head) — type / to see the list"
                            : "Unknown command — did you mean \(near.joined(separator: ", "))?"
    }

    /// Tapping a line in the menu.
    func picked(_ item: SlashItem, draft: inout String, state: AppState,
                onCommand: ((String) -> Bool)?) {
        switch item.kind {
        case .builtin:
            draft = ""
            _ = onCommand?(item.command)
        case .library:
            if Self.takesWords.contains(item.command) { draft = item.command + " "; return }
            if let replaced = intercept(item.command, state: state) {
                draft = replaced
            } else {
                // one the chat itself answers, such as /files
                draft = ""
                _ = onCommand?(item.command)
            }
        case .prompt:
            let p = SlashCatalog.shared.prompts.first { "/" + $0.name == item.command }
            let body = p?.text ?? ""
            // a prompt that takes words waits for them; one that doesn't goes in whole
            let takesWords = body.contains("$ARGUMENTS")
                || body.range(of: #"\$\{?\d"#, options: .regularExpression) != nil
            draft = takesWords || p == nil ? item.command + " " : body
        case .claude:
            draft = item.command + " "
        }
    }

    /// Same naming as the web: the first four words, lowercased, joined with -.
    private func remember(_ text: String, state: AppState) async {
        let words = text.lowercased().split(whereSeparator: \.isWhitespace).prefix(4).joined(separator: "-")
        let name = String(words.unicodeScalars.filter {
            ("a"..."z").contains($0) || ("0"..."9").contains($0) || $0 == "-"
        }.map(Character.init))
        do {
            let saved = try await state.server?.saveMemory(name: name.isEmpty ? "note" : name, text: text)
            note = "Saved to memory: \(saved ?? name)"
            Haptics.success()
        } catch {
            note = error.localizedDescription
        }
    }
}

/// The "/" menu above the message box.
struct SlashMenu: View {
    @EnvironmentObject var state: AppState
    @Binding var draft: String
    @ObservedObject var controller: SlashController
    @ObservedObject private var catalog = SlashCatalog.shared
    var builtins: [(String, String)]
    var onCommand: ((String) -> Bool)?

    private var claude: Bool { SlashCatalog.isClaudeChat(state) }

    var body: some View {
        let items = controller.items(for: draft, builtins: builtins, catalog: catalog, claude: claude)
        VStack(spacing: 0) {
            if let note = controller.note {
                Text(note).font(.caption.weight(.medium)).foregroundStyle(.secondary)
                    .padding(.horizontal, 12).padding(.top, 6)
                    .task(id: note) {
                        try? await Task.sleep(nanoseconds: 2_500_000_000)
                        controller.note = nil
                    }
            }
            if !items.isEmpty {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(items) { item in
                            Button {
                                Haptics.tap()
                                controller.picked(item, draft: &draft, state: state, onCommand: onCommand)
                            } label: { row(item) }
                            .buttonStyle(.plain)
                            Divider().padding(.leading, 12)
                        }
                    }
                }
                .frame(maxHeight: min(CGFloat(items.count) * 46, 230))
                .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 12))
                .padding(.horizontal, 12).padding(.top, 8)
            }
        }
        .task(id: draft.hasPrefix("/")) {
            if draft.hasPrefix("/") { await catalog.refresh(state.server, claude: claude) }
        }
    }

    private func row(_ item: SlashItem) -> some View {
        HStack(spacing: 8) {
            Text(item.command).font(.callout.monospaced().weight(.semibold))
                .lineLimit(1).layoutPriority(1)
            Text(item.detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            Spacer(minLength: 4)
            switch item.kind {
            case .prompt: tag("prompt")
            case .claude: tag("Claude")
            default: EmptyView()
            }
        }
        .padding(.horizontal, 12).frame(minHeight: 45)
        .contentShape(.rect)
    }

    private func tag(_ s: String) -> some View {
        Text(s).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(.quaternary, in: .capsule)
    }
}

extension View {
    /// The Library screens a slash command opens, presented over the chat.
    func slashSheets(_ controller: SlashController) -> some View {
        sheet(item: Binding(get: { controller.sheet }, set: { controller.sheet = $0 })) { target in
            switch target {
            case .section(let s, let sid): LibrarySheet(section: s, sid: sid)
            case .chat(let sid):  ChatLibrarySheet(sid: sid)
            case .share(let url): ActivityView(items: [url]).ignoresSafeArea()
            case .info(let title, let text): SlashInfoSheet(title: title, text: text)
            case .doctor:
                NavigationStack {
                    StatusHealthView()
                        .toolbar { ToolbarItem(placement: .confirmationAction) { DismissButton() } }
                }
            case .shortcuts: ShortcutsSheet()
            case .history: SlashHistorySheet()
            }
        }
    }
}

/// A command's answer too long for the line under the box.
private struct SlashInfoSheet: View {
    let title: String
    let text: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                Text(text).font(.callout.monospaced()).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding()
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
    }
}

/// "Done" for a screen borrowed from Settings.
private struct DismissButton: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View { Button("Done") { dismiss() } }
}

/// `/history`: the message picked goes back in the box.
private struct SlashHistorySheet: View {
    @EnvironmentObject var state: AppState
    var body: some View { PromptHistorySheet { state.draftPrefill = $0 } }
}
