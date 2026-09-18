import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

/// The bar at the bottom of a conversation. Attachments come from three places
/// — the photo library, the camera, or the Files app — and each opens the real
/// system picker, so it looks and behaves like every other app on the phone.
///
/// While an answer runs, a new message joins the chat's queue and starts when the
/// answers ahead of it are done, as on the Mac; holding Send (or ⌘⇧↩) steers
/// instead — a note the running answer reads at its next step.
struct Composer: View {
    @EnvironmentObject var state: AppState
    @Binding var draft: String
    var typing: FocusState<Bool>.Binding
    var modelName: String
    var onPickModel: () -> Void
    /// Returns true when it handled a `/command`, so the text is not sent as a message.
    var onCommand: ((String) -> Bool)? = nil

    static let commands: [(String, String)] = [
        ("/new", "start a new chat"), ("/model", "switch the model for this chat"),
        ("/compact", "compact the history"), ("/find", "find in this chat"),
        ("/rewind", "go back to an earlier message — chat only, or files too"),
        ("/context", "what is filling the context window right now"),
        ("/copy", "copy the last answer (/copy 2 for the one before)"),
        ("/diff", "every file change shown in this chat, as a diff"),
        ("/verbose", "show every tool call in full, or fold them again"),
        ("/todos", "show or hide the todo list"),
        ("/usage", "cost, tokens and time — this chat and lately"),
        ("/permissions", "what it may do without asking"),
        ("/theme", "light, dark or follow the system"),
        ("/fork", "copy this chat into a new one and carry on there"),
        ("/jump", "jump to one of your messages in this chat"),
        ("/stats", "usage: turns, tokens and time per model"),
        ("/hidetools", "hide or show finished tool rows"),
        ("/clear", "clear the screen only"),
        ("/help", "show these commands"),
    ]

    /// A leading `!` runs a shell command; a single `# line` goes to memory.
    private enum Mode { case message, shell, memory }
    private var mode: Mode {
        if draft.hasPrefix("!") { return .shell }
        if draft.hasPrefix("# "), !draft.contains("\n") { return .memory }
        return .message
    }
    /// Library: the "/" menu (commands, saved prompts, Claude's commands) and what it opens.
    @StateObject private var slash = SlashController()

    /// When you last sent or queued, so a double tap cannot land on Stop.
    @State private var lastSubmit = Date.distantPast
    @State private var showAttachMenu = false
    @State private var showLibrary = false
    @State private var showCamera = false
    @State private var showFiles = false
    @State private var picked: [PhotosPickerItem] = []
    @State private var showLater = false
    @State private var showHistory = false
    @State private var showShortcuts = false
    /// Long pastes folded into `[Pasted #n · ~L lines]`, by number.
    @State private var pastes: [Int: String] = [:]
    @State private var lastEscape = Date.distantPast
    @AppStorage("orbit.verboseTools") private var verboseTools = false
    @AppStorage("orbit.todosHidden") private var todosHidden = false
    @AppStorage("orbit.hideTools") private var hideTools = false

    private var sid: String? { state.openChat?.sid }

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !state.attachments.isEmpty
    }

    /// Send puts the message in the queue rather than starting it.
    private var queues: Bool { state.sendingQueues }

    var body: some View {
        VStack(spacing: 0) {
            if !state.queue.items.isEmpty { QueueStrip() }
            HStack(spacing: 8) {
            // Which model answers is the single fact you most want in view, so it
            // lives here rather than in a toolbar that folds it away when cramped.
            Button(action: onPickModel) {
                HStack(spacing: 5) {
                    Image(systemName: "cpu").font(.caption2)
                    Text(state.streaming && !state.liveModel.isEmpty ? state.liveModel : modelName)
                        .font(.caption.weight(.medium)).lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down").font(.caption2)
                }
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(.quaternary.opacity(0.35), in: .capsule)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Model: \(modelName). Tap to change.")
            ContextGauge()
            OffpeakBadge()
            if canSend {
                Button { showLater = true } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "clock").font(.caption2)
                        Text("Send later").font(.caption.weight(.medium))
                    }
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(.quaternary.opacity(0.35), in: .capsule)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Send later")
            }
            }
            .padding(.top, 6)
            ContextLowLine()
            if !state.attachments.isEmpty || state.uploading { attachmentStrip }
            if !pasteTokens.isEmpty { pasteStrip }
            SlashMenu(draft: $draft, controller: slash, builtins: Self.commands, onCommand: onCommand)
            MentionMenu(draft: $draft)
            HStack(alignment: .bottom, spacing: 8) {
                Button {
                    Haptics.tap()
                    showAttachMenu = true
                } label: {
                    Image(systemName: "plus")
                        .font(.body.weight(.semibold))
                        .frame(width: 36, height: 36)
                        .background(.quaternary.opacity(0.5), in: .circle)
                }
                .accessibilityLabel("Attach")

                TextField(queues ? "Queue a message" : "Message", text: typedDraft, axis: .vertical)
                    .lineLimit(1...6)
                    .font(mode == .shell ? .body.monospaced() : .body)
                    .focused(typing)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.background, in: .rect(cornerRadius: 20))
                    .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(modeBorder, lineWidth: mode == .message ? 1 : 1.5))

                if !state.streaming || canSend {
                    sendButton
                }
                if state.streaming {
                    Button {
                        // Stop takes the send button's place once the box is empty: a second tap
                        // meant for Send (a double tap) must not stop the answer just started
                        guard Date().timeIntervalSince(lastSubmit) > 1.2 else { return }
                        Task { await state.stopGenerating() }
                    } label: {
                        Image(systemName: "stop.fill")
                            .font(.footnote.weight(.bold))
                            .frame(width: 36, height: 36)
                            .background(.red, in: .circle)
                            .foregroundStyle(.white)
                    }
                    .accessibilityLabel("Stop")
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 8)
            .padding(.bottom, mode == .message ? 6 : 4)
            if let hint = modeHint {
                Text(hint)
                    .font(.caption2)
                    .foregroundStyle(modeBorder)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16).padding(.bottom, 4)
            }
            PermissionModeLine()
        }
        .background { keyCommands }
        .slashSheets(slash)
        .sheet(isPresented: $showLater) {
            SendLaterSheet { date, rep in schedule(at: date, repeat: rep) }
                .presentationDetents([.medium, .large])
        }
        .sheet(isPresented: $showHistory) {
            PromptHistorySheet { text in
                draft = text
                typing.wrappedValue = true
            }
        }
        .sheet(isPresented: $showShortcuts) { ShortcutsSheet() }
        // Three real pickers. Each is a system sheet, presented from a bool it
        // owns, so nothing is hidden under anything else.
        .confirmationDialog("Attach", isPresented: $showAttachMenu, titleVisibility: .hidden) {
            Button("Photo Library") { showLibrary = true }
            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button("Take Photo") { showCamera = true }
            }
            Button("Choose File") { showFiles = true }
            Button("Earlier messages") { showHistory = true }
            Button("Cancel", role: .cancel) {}
        }
        .photosPicker(isPresented: $showLibrary, selection: $picked,
                      maxSelectionCount: 4, matching: .images)
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            let batch = items
            picked = []
            Task { for item in batch { await state.attach(photo: item) } }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { image in
                showCamera = false
                guard let image else { return }
                Task { await state.attach(image: image) }
            }
            .ignoresSafeArea()
        }
        .fileImporter(isPresented: $showFiles, allowedContentTypes: [.item],
                      allowsMultipleSelection: true) { result in
            if case .success(let urls) = result {
                Task { for u in urls { await state.attach(fileAt: u) } }
            }
        }
        .task(id: sid) {
            if let sid { pastes = Pastes.load(sid) }
        }
    }

    // ------------------------------------------------------------ sending

    /// Send, or Queue while an answer runs. Holding it offers Steer and Send later.
    private var sendButton: some View {
        Button { submit() } label: {
            Image(systemName: queues ? "tray.and.arrow.down.fill" : "arrow.up")
                .font(.body.weight(.bold))
                .frame(width: 36, height: 36)
                .background(canSend ? Color.accentColor : Color.secondary.opacity(0.35),
                            in: .circle)
                .foregroundStyle(.white)
        }
        .disabled(!canSend)
        .accessibilityLabel(queues ? "Queue" : "Send")
        .accessibilityHint(queues ? "It starts when the answers ahead of it are done" : "")
        // hold to steer the running answer, or to send it later instead
        .contextMenu {
            if canSend {
                if state.streaming {
                    Button { submit(now: true) } label: {
                        Label("Send into the running answer now", systemImage: "arrow.turn.down.right")
                    }
                    Divider()
                }
                ForEach(SendLaterSheet.presets(), id: \.label) { p in
                    Button { schedule(at: p.date, repeat: .once) } label: {
                        Label("Send \(p.label)", systemImage: "clock")
                    }
                }
                Button { showLater = true } label: {
                    Label("Pick a time…", systemImage: "calendar.badge.clock")
                }
            }
        }
        .accessibilityAction(named: "Send into the running answer now") {
            if state.streaming && canSend { submit(now: true) }
        }
    }

    /// What Send does with the box. While the chat answers, or has messages
    /// waiting, a message joins the queue — `now` steers the running answer
    /// instead. A `/command` always runs straight away.
    private func submit(now: Bool = false) {
        lastSubmit = Date()
        let raw = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let text = Pastes.expand(raw, pastes)
        guard !text.isEmpty || !state.attachments.isEmpty else { return }
        let sending = mode
        // `!` and `#` lines are actions, not messages: they never wait in the queue
        if sending == .shell {
            let cmd = String(text.dropFirst()).trimmingCharacters(in: .whitespaces)
            guard !cmd.isEmpty else { return }
            // the Mac holds the chat while it answers and refuses a command (409): say
            // so here and keep the box, rather than queueing it as a message
            if state.streaming {
                slash.note = "That chat is answering — run it after"
                return
            }
            PromptHistory.push(text)
            Haptics.tap()
            clearBox()
            Task { await state.runBang(cmd) }
            return
        }
        if sending == .memory {
            PromptHistory.push(text)
            Haptics.tap()
            clearBox()
            Task { await state.rememberLine(String(text.dropFirst(2))) }
            return
        }
        if !text.isEmpty { PromptHistory.push(text) }
        Haptics.tap()

        let command = Self.isCommand(text)
        let kept = draft, keptPastes = pastes, keptSid = sid
        if queues && !command {
            if now && state.streaming { steer(text); return }
            clearBox()
            Task { if !(await state.enqueue(text)) { restore(kept, keptPastes, sid: keptSid) } }
            return
        }
        clearBox()
        if command {
            if let replaced = slash.intercept(text, state: state) {
                draft = replaced      // a saved prompt expands in place; a Library command ran
                return
            }
            if onCommand?(text) == true { return }
            // Claude Code and Codex have commands of their own; Orbit's chats do not
            if !SlashCatalog.isClaudeChat(state) {
                slash.note = slash.unknownCommand(text, builtins: Self.commands)
                restore(kept, keptPastes, sid: keptSid)
                return
            }
        }
        Task { await state.send(text) }
    }

    /// A note for the running answer, read at its next step. Attachments cannot go with it.
    private func steer(_ text: String) {
        guard !text.isEmpty else {
            state.toast("Attachments go with a new message — queue it, or wait for the answer")
            return
        }
        if !state.attachments.isEmpty { state.toast("The note goes without the attachments — send those after") }
        clearBox()
        Task { await state.steer(text) }
    }

    /// A `/command` is a slash and a word at the very start; "/Users/me/data.csv
    /// summarize" is a path, and goes out as a message.
    static func isCommand(_ text: String) -> Bool {
        guard text.range(of: #"^/[A-Za-z][\w-]*(\s|$)"#, options: .regularExpression) != nil else { return false }
        let head = text.split(whereSeparator: \.isWhitespace).first ?? ""
        return !head.dropFirst().contains("/")
    }

    /// Put back a draft that could not be queued or scheduled, with the long pastes its tokens stand for.
    private func restore(_ kept: String, _ keptPastes: [Int: String], sid keptSid: String?) {
        guard keptSid == sid else { return }
        pastes = keptPastes
        if let keptSid { Pastes.save(keptSid, keptPastes) }
        draft = kept
    }

    private func clearBox() {
        draft = ""
        pastes = [:]
        if let sid { Pastes.save(sid, [:]) }
    }

    private var modeBorder: AnyShapeStyle {
        switch mode {
        case .shell: return AnyShapeStyle(Color.orange)
        case .memory: return AnyShapeStyle(Color.purple)
        case .message: return AnyShapeStyle(.quaternary)
        }
    }

    private var modeHint: String? {
        switch mode {
        case .shell: return "! shell mode — runs in this chat's folder; the output joins the conversation"
        case .memory: return "# memory — send saves this line to memory"
        case .message: return nil
        }
    }

    /// The draft goes into the chat's queue for later, and the box clears.
    private func schedule(at date: Date, repeat rep: Repeat) {
        let text = Pastes.expand(draft.trimmingCharacters(in: .whitespacesAndNewlines), pastes)
        guard !(text.isEmpty && state.attachments.isEmpty) else { return }
        let kept = draft, keptPastes = pastes, keptSid = sid
        clearBox()
        Haptics.success()
        Task { if !(await state.sendLater(text, at: date, repeat: rep)) { restore(kept, keptPastes, sid: keptSid) } }
    }

    // ------------------------------------------------------------ long pastes

    private var pasteTokens: [Int] {
        pastes.isEmpty ? [] : Pastes.tokens(in: draft).filter { pastes[$0] != nil }
    }

    /// The box's text as the text field sees it. Only your own typing and pasting
    /// come through this setter; the app filling the box (a saved draft, a quote,
    /// edit and resend, an earlier message, "show the paste") writes `draft`
    /// directly, so only a real paste is folded away.
    private var typedDraft: Binding<String> {
        Binding(get: { draft }, set: { new in
            let old = draft
            draft = new
            foldPaste(old: old, new: new)
        })
    }

    /// A long block arriving at once is a paste: it folds into a token, so the box
    /// stays usable, and goes out in full with the message.
    private func foldPaste(old: String, new: String) {
        guard let sid, new.count - old.count >= Pastes.minChars else { return }
        let prefix = old.commonPrefix(with: new).count
        let oldTail = old.dropFirst(prefix), newTail = new.dropFirst(prefix)
        var suffix = 0
        for (a, b) in zip(oldTail.reversed(), newTail.reversed()) where a == b { suffix += 1 }
        suffix = min(suffix, oldTail.count)
        let inserted = String(newTail.dropLast(suffix))
        let lines = inserted.split(separator: "\n", omittingEmptySubsequences: false).count
        guard inserted.count >= Pastes.minChars, lines >= Pastes.minLines else { return }
        let n = (pastes.keys.max() ?? 0) + 1
        pastes[n] = inserted
        Pastes.save(sid, pastes)
        draft = String(new.prefix(prefix)) + Pastes.token(n, lines: lines) + String(newTail.suffix(suffix))
    }

    /// The folded pastes in the box: open one back up, or drop it.
    private var pasteStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(pasteTokens, id: \.self) { n in
                    let body = pastes[n] ?? ""
                    HStack(spacing: 6) {
                        Image(systemName: "doc.plaintext").font(.caption)
                        Text("Pasted #\(n) · \(body.count.formatted()) chars").font(.caption).lineLimit(1)
                        Button {
                            replaceToken(n, with: body)
                        } label: { Image(systemName: "arrow.up.left.and.arrow.down.right").font(.caption) }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("Show the paste in the box")
                        Button {
                            replaceToken(n, with: "")
                        } label: { Image(systemName: "xmark.circle.fill").font(.caption) }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("Remove the paste")
                    }
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(.quaternary.opacity(0.5), in: .capsule)
                }
            }
            .padding(.horizontal, 12).padding(.top, 8)
        }
        .frame(height: 40)
    }

    private func replaceToken(_ n: Int, with text: String) {
        guard let sid, let re = try? NSRegularExpression(pattern: #"\[Pasted #\#(n) · ~\d+ lines\]"#) else { return }
        pastes[n] = nil
        Pastes.save(sid, pastes)
        let range = NSRange(draft.startIndex..., in: draft)
        // the template must not read `$` or `\` in the pasted text as references
        draft = re.stringByReplacingMatches(in: draft, range: range,
                                            withTemplate: NSRegularExpression.escapedTemplate(for: text))
    }

    // ------------------------------------------------------------ keyboard

    /// A hardware keyboard's commands, as on the Mac.
    private var keyCommands: some View {
        KeyCommands(commands: [
            .init(queues ? "Queue" : "Send", .return, .command, enabled: canSend) { submit() },
            .init("Send into the running answer", .return, [.command, .shift],
                  enabled: state.streaming && canSend) { submit(now: true) },
            .init(state.streaming ? "Stop the answer" : "Clear the box", .escape) { escape() },
            .init("Clear the box", "l", .control) { clearBox() },
            .init("Earlier messages", "r", .control) { showHistory = true },
            .init("Cycle the permission mode", .tab, .shift) {
                Task { await state.cyclePermissionMode() }
            },
            .init(verboseTools ? "Fold tool calls" : "Show every tool call", "o", .control) {
                verboseTools.toggle()
                state.toast(verboseTools ? "Showing every tool call in full" : "Tool calls folded again")
            },
            .init(todosHidden ? "Show the todo list" : "Hide the todo list", "t", .control) {
                todosHidden.toggle()
            },
            .init(hideTools ? "Show finished tool rows" : "Hide finished tool rows", "h", .control) {
                _ = onCommand?("/hidetools")
            },
            .init("Jump to a message", "g", .command) { _ = onCommand?("/jump") },
            .init("New chat", "n", .command) { _ = onCommand?("/new") },
            .init("Keyboard shortcuts", "/", .command) { showShortcuts = true },
        ])
    }

    /// Esc stops a running answer, or clears the box; twice quickly opens the rewind list.
    private func escape() {
        let now = Date()
        defer { lastEscape = now }
        if now.timeIntervalSince(lastEscape) < 0.6 {
            lastEscape = .distantPast
            _ = onCommand?("/rewind")
            return
        }
        if state.streaming {
            Task { await state.stopGenerating() }
        } else if !draft.isEmpty {
            PromptHistory.push(Pastes.expand(draft, pastes))
            clearBox()
        }
    }

    /// What is going up with the next message, and how to change your mind.
    private var attachmentStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(state.attachments) { a in
                    HStack(spacing: 6) {
                        if let thumb = a.thumbnail {
                            Image(uiImage: thumb).resizable().scaledToFill()
                                .frame(width: 28, height: 28).clipShape(.rect(cornerRadius: 6))
                        } else {
                            Image(systemName: a.kind == "image" ? "photo" : "doc").font(.caption)
                        }
                        Text(a.name).font(.caption).lineLimit(1).frame(maxWidth: 140)
                        Button {
                            state.attachments.removeAll { $0.id == a.id }
                        } label: { Image(systemName: "xmark.circle.fill").font(.caption) }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(.leading, 6).padding(.trailing, 9).padding(.vertical, 5)
                    .background(.quaternary.opacity(0.5), in: .capsule)
                }
                if state.uploading {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini)
                        Text("uploading").font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 9).padding(.vertical, 6)
                }
            }
            .padding(.horizontal, 12).padding(.top, 8)
        }
        .frame(height: 46)
    }
}

/// The system camera, wrapped. Returns nil if the person backs out.
struct CameraPicker: UIViewControllerRepresentable {
    var onDone: (UIImage?) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let c = UIImagePickerController()
        c.sourceType = .camera
        c.delegate = context.coordinator
        return c
    }
    func updateUIViewController(_ vc: UIImagePickerController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(onDone: onDone) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onDone: (UIImage?) -> Void
        init(onDone: @escaping (UIImage?) -> Void) { self.onDone = onDone }
        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onDone(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onDone(nil) }
    }
}
