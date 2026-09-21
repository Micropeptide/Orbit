import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

struct ChatView: View {
    let sid: String
    /// Index of the message a search hit pointed at, so the view can land there
    /// and flash it rather than dumping you at the end of a long conversation.
    var highlight: Int? = nil
    @State private var flashed: Int? = nil
    /// Whether the newest message is on screen, and whether more arrived while it was not.
    @State private var atBottom = true
    @State private var newBelow = false
    /// Whether new text should keep you at the newest message. Only your own finger turns
    /// it off (dragging back up to read); rows changing height never do -- they used to
    /// leave the view parked past the end of a finished answer, which looked blank.
    @State private var following = true
    /// True while a scroll you started is still in flight, so a layout change cannot be
    /// mistaken for you scrolling back to the bottom.
    @State private var userScrolling = false
    @State private var scrollToken = UUID()
    /// How tall each transcript row is, for the turn rail's bars.
    @State private var rowHeights: [Int: CGFloat] = [:]
    @State private var viewportHeight: CGFloat = 800
    /// Draw lazily only in very long chats. Decided from the saved messages with a gap between
    /// the two thresholds, so an answer finishing (or streaming) never flips it mid-read --
    /// flipping rebuilt the whole transcript.
    @State private var lazyTranscript = false
    /// Bumped by the "Latest" button, which lives in the composer, away from the scroll proxy.
    @State private var scrollDownRequest = 0
    @EnvironmentObject var state: AppState
    @State private var draft = ""
    @State private var showModels = false
    @State private var showLibrary = false      // Library: agent, instructions, memory for this chat
    @State private var renaming = false
    @State private var newTitle = ""
    @State private var confirmBin = false
    @State private var finding = false
    @State private var findText = ""
    @State private var findAt = 0
    @State private var jumpTo: Int?
    @State private var pdfURL: URL?
    @FocusState private var findFocused: Bool
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var typing: Bool
    @ObservedObject private var links = FileLinks.shared
    /// Per-message and chat-level actions, and the sheets they open (Views/Chat).
    @StateObject private var actionsModel = ChatActionsModel()
    @AppStorage("orbit.verboseTools") private var verboseTools = false
    @AppStorage("orbit.todosHidden") private var todosHidden = false
    @AppStorage("theme") private var theme = "system"
    @AppStorage("orbit.hideTools") private var hideTools = false
    /// `/clear`: the rows before this many messages are hidden until the chat is opened
    /// again. Only the view: the messages, the chat on the Mac and the cache keep them.
    @State private var cleared: (sid: String, count: Int)?

    /// A chat known to be empty — a new one, or one loaded with nothing in it — opens at
    /// its greeting. Not merely one with no messages yet: a chat still loading has none for
    /// a moment, and opening it at the top left an ongoing conversation at its oldest message.
    private var isHome: Bool {
        state.messages.isEmpty && !state.streaming && state.openChat?.sid == sid
            && (state.openChat?.messages.isEmpty ?? true) && (state.openChat?.n ?? 0) == 0
    }

    /// "Good morning — what's next?", as the Mac greets a new chat. Six bands, and the
    /// same words the Mac uses: "Good afternoon" at 17:59 and "Good evening" at 18:00
    /// is a cliff, and 5am and midnight are not the same kind of late.
    static func greeting(now: Date = .now) -> String {
        let h = Calendar.current.component(.hour, from: now)
        let when = h < 5 ? "Still up" : h < 9 ? "Early start" : h < 12 ? "Good morning"
                 : h < 18 ? "Good afternoon" : h < 23 ? "Good evening" : "Late one"
        return "\(when) — what's next?"
    }

    var body: some View {
        // The banner and composer are safe-area insets rather than VStack rows:
        // that keeps the transcript's own inset correct, so text scrolls under
        // the navigation bar instead of starting behind it.
        transcript
            .safeAreaInset(edge: .top, spacing: 0) {
                VStack(spacing: 0) {
                    ConnectionBanner()
                    WorkBar(sid: sid)
                    ChatModeChips(sid: sid, model: actionsModel)
                    if finding { findBar }
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) { composer }
            .navigationTitle(state.openChat?.title ?? "New chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)     // inside a conversation the keyboard needs the room
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button { showModels = true } label: {
                            Label("Change model", systemImage: "cpu")
                        }
                        .keyboardShortcut("k", modifiers: .command)
                        .disabled(state.streaming)
                        Button { renaming = true; newTitle = state.openChat?.title ?? "" } label: {
                            Label("Rename", systemImage: "pencil")
                        }
                        .disabled(state.streaming)
                        ShareLink(item: state.markdown(for: sid),
                                  preview: SharePreview(state.openChat?.title ?? "Chat")) {
                            Label("Share as Markdown", systemImage: "square.and.arrow.up")
                        }
                        Button {
                            UIPasteboard.general.string = state.markdown(for: sid)
                            Haptics.success()
                        } label: {
                            Label("Copy as text", systemImage: "doc.on.doc")
                        }
                        Button { makePDF() } label: {
                            Label("Share as PDF", systemImage: "doc.richtext")
                        }
                        Button { showLibrary = true } label: {
                            Label("Agent, instructions, memory", systemImage: "books.vertical")
                        }
                        Button { finding = true; findFocused = true } label: {
                            Label("Find in chat", systemImage: "magnifyingglass")
                        }
                        .keyboardShortcut("f", modifiers: .command)
                        Button {
                            Task { await state.compactCurrent() }
                        } label: {
                            Label("Compact history", systemImage: "arrow.down.right.and.arrow.up.left")
                        }
                        .disabled(state.streaming)
                        ChatMenuItems(sid: sid, model: actionsModel)
                        Divider()
                        Button(role: .destructive) { confirmBin = true } label: {
                            Label("Move to bin", systemImage: "trash")
                        }
                        .disabled(state.streaming)
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    // what only reads (find, share, jump, context) stays open while it answers
                    .accessibilityLabel("Chat options")
                }
            }
            .alert("Rename chat", isPresented: $renaming) {
                TextField("Title", text: $newTitle)
                Button("Save") { Task { await state.rename(sid, to: newTitle) } }
                Button("Cancel", role: .cancel) {}
            }
            .confirmationDialog("Move this chat to the bin?", isPresented: $confirmBin,
                                titleVisibility: .visible) {
                Button("Move to bin", role: .destructive) {
                    Task { await state.delete(sid); dismiss() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("It stays in the bin on your Mac for the retention period.")
            }
            .sheet(isPresented: $showModels) { ModelPickerView() }
            .sheet(isPresented: $showLibrary) { ChatLibrarySheet(sid: sid) }
            .sheet(item: $links.presenting) { FilePreviewSheet(target: $0) }
            .sheet(item: $pdfURL) { ActivityView(items: [$0]).ignoresSafeArea() }
            .onChange(of: state.draftPrefill) { _, text in
                guard let text else { return }
                draft = text; typing = true; state.draftPrefill = nil
            }
            .onChange(of: draft) { _, text in Drafts.save(sid, text) }
            .onChange(of: actionsModel.helpPick) { _, text in
                guard let text else { return }
                draft = text; typing = true; actionsModel.helpPick = nil
            }
            // questions and approvals are cards in the transcript (ChatPromptCards)
            .modifier(ChatActionsHost(sid: sid, model: actionsModel))
            .modifier(ToastOverlay())
    }

    private var currentModelName: String { state.currentModelName }

    /// (row index, first words, how tall that turn is) — one entry per message of
    /// yours, a turn being everything from it up to the next one.
    private var turnAnchors: [(index: Int, text: String, height: CGFloat)] {
        let rows = transcriptRows
        var out: [(index: Int, text: String, height: CGFloat)] = []
        for r in rows {
            let m = r.message
            if m.isUser && m.note != true {
                out.append((index: r.index, text: m.text, height: 0))
            }
            guard !out.isEmpty else { continue }
            out[out.count - 1].height += (rowHeights[r.index] ?? 60)
        }
        return out.count > 3 ? out.map { ($0.index, $0.text, max(10, $0.height)) } : []
    }

    private var transcriptRows: [TranscriptRow] {
        let rows = TranscriptRow.build(state.messages)
        guard let c = cleared, c.sid == sid, c.count <= state.messages.count else { return rows }
        return rows.filter { $0.index >= c.count }
    }

    // ------------------------------------------------------------ transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                // A plain stack for ordinary chats: the lazy one mis-measured tall answers (a long
                // list, a big table) and parked the view past the end, so the chat looked blank.
                // Only very long chats, where drawing every row costs too much, stay lazy.
                Group {
                    if !lazyTranscript {
                        VStack(alignment: .leading, spacing: 18) { transcriptContent }
                    } else {
                        LazyVStack(alignment: .leading, spacing: 18) { transcriptContent }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
            }
            .coordinateSpace(name: "transcript")
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { viewportHeight = $0 }
            // open at the newest message; an empty chat opens at its greeting
            .defaultScrollAnchor(isHome ? .top : .bottom)
            .scrollDismissesKeyboard(.interactively)
            .apply { followingNewest($0, proxy: proxy) }
            .onChange(of: actionsModel.jumpRequest) { _, i in
                guard let i else { return }
                jumpTo = i
                actionsModel.jumpRequest = nil
            }
            .onChange(of: jumpTo) { _, i in
                guard let i else { return }
                withAnimation(reduceMotion ? nil : .default) {
                    proxy.scrollTo("row-\(i)", anchor: .center)
                    flashed = i
                }
                jumpTo = nil
            }
            .onAppear { scroll(proxy, animated: false) }
            .onDisappear { SeenChats.mark(sid, mtime: state.chats.first { $0.id == sid }?.mtime ?? 0) }
            .modifier(AnswerTextSize())
            // how long this is and where you are in it — a question the outline, which
            // lists what you asked, does not answer
            .overlay(alignment: .trailing) {
                TurnRail(sid: sid, turns: turnAnchors,
                         live: state.streaming && state.liveSid == sid,
                         showing: userScrolling || (state.streaming && state.liveSid == sid)) { i in
                    jumpTo = i
                }
            }
            // file names in answers are looked up in this chat
            .environment(\.fileLinkSid, sid)
            .task(id: sid) {
                // what you were typing here last time, unless something is being handed in
                draft = Drafts.load(sid)
                await state.open(sid)
                SeenChats.mark(sid, mtime: state.chats.first { $0.id == sid }?.mtime ?? 0)
                if let text = state.draftPrefill { draft = text; typing = true; state.draftPrefill = nil }
                if highlight == nil { await pinToNewest(proxy) }
                // a search hit: land on that message and flash it once the rows exist
                guard let h = highlight, h < state.messages.count, flashed == nil else { return }
                try? await Task.sleep(nanoseconds: 250_000_000)
                withAnimation { proxy.scrollTo("row-\(h)", anchor: .center) }
                withAnimation { flashed = h }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                withAnimation { flashed = nil }
            }
        }
    }

    /// Every row of the transcript: your messages and answers, the answer being written,
    /// prompts, errors, and the marker that says you are at the newest message.
    @ViewBuilder private var transcriptContent: some View {
                    if state.messages.isEmpty && !state.streaming {
                        VStack(spacing: 10) {
                            Image("OrbitMark").resizable().scaledToFit()
                                .frame(width: 56, height: 56).opacity(0.9)
                            Text(Self.greeting()).font(.title3.weight(.semibold))
                            Text("Answering with \(currentModelName)")
                                .font(.caption2).foregroundStyle(.tertiary)
                            EmptyChatHero(sid: sid)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 48).padding(.horizontal, 24)
                        .id("home")
                    }
                    let rows = transcriptRows
                    // /hidetools: steps that are only finished tool calls are left out of the rows
                    // themselves (an empty conditional row upsets the lazy list's layout)
                    let shown = hideTools ? rows.filter { !$0.message.onlyToolCalls } : rows
                    let stamped = TranscriptRow.stamped(shown)
                    let turns = TranscriptRow.turns(state.messages)
                    ForEach(shown) { row in
                        let i = row.index
                        let m = row.message
                        let t = i < turns.count && turns[i].ends ? turns[i] : nil
                        VStack(alignment: .leading, spacing: 3) {
                            MessageBubble(message: hideTools ? m.hidingTools : m,
                                          isLast: row.id == rows.last?.id,
                                          onEdit: { msg in Task { await state.editAndResend(msg) } },
                                          onRegenerate: { actionsModel.confirmRegenerate = false },
                                          onQuote: { msg in quote(msg) },
                                          actions: actionsModel.actions(state),
                                          showByline: row.showByline,
                                          turn: t.map { ($0.turn, $0.prompt) })
                            if stamped.contains(m.id), let at = m.t { MessageTime(t: at, trailing: m.isUser) }
                        }
                            .id(m.id)
                            .padding(.top, row.joinsPrevious ? -12 : 0)
                            .padding(.horizontal, flashed == i ? 8 : 0)
                            .padding(.vertical, flashed == i ? 6 : 0)
                            .background(flashed == i ? Color.yellow.opacity(0.18) : .clear,
                                        in: .rect(cornerRadius: 10))
                            .id("row-\(i)")
                            // how tall each row is, so the rail can size its bars by how
                            // long a turn actually is. A height changes when the layout
                            // does; a POSITION changes on every scroll frame, and writing
                            // one per row per frame rebuilt the whole transcript each time.
                            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { h in
                                let r = (h / 4).rounded() * 4          // ignore sub-step noise
                                if rowHeights[i] != r { rowHeights[i] = r }
                            }
                    }
                    if state.streaming {
                        // each finished step of the running answer is its own row: packed into one
                        // tall row, the lazy list lost its layout and the answer went blank mid-way
                        let continues = state.messages.last.map { !$0.isUser } ?? false
                        ForEach(Array(state.liveSteps.enumerated()), id: \.element.id) { n, step in
                            MessageBubble(message: step, showByline: n == 0 && !continues)
                                .id(step.id)
                                .environment(\.fileLinkSid, nil)
                        }
                        liveStepInHand.id("live").environment(\.fileLinkSid, nil)
                    }
                    ChatPromptCards().id("prompts")
                    if let e = state.lastError, !state.streaming { errorNote(e) }
                    // seen = you are at the newest message; new text follows you only then
                    // where the end of the chat is on screen: within a short reach of the bottom
                    // edge counts as being at the newest message (appear/disappear can't tell --
                    // an ordinary stack creates every row up front)
                    Color.clear.frame(height: 8).id("bottom")
                        .onGeometryChange(for: CGFloat.self) { $0.frame(in: .named("transcript")).minY } action: { y in
                            let near = y < viewportHeight + 60
                            if near != atBottom { atBottom = near }
                            if near { newBelow = false }
                            // Following again is a decision, and only you make it. An image
                            // finishing, a tool row opening, a thinking block expanding and the
                            // todo dock appearing all move this marker into range without your
                            // touching anything — and the next token then yanked you down
                            // mid-sentence. Your own drag ending near the bottom says it.
                            if near && userScrolling { following = true }
                        }
    }

    /// Shown in the transcript where the answer would have been, because that
    /// is where you are looking when it fails.
    private func errorNote(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 3) {
                Text(text).font(.footnote)
                Button("Dismiss") { state.lastError = nil }
                    .font(.caption).buttonStyle(.plain).foregroundStyle(.tint)
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.10), in: .rect(cornerRadius: 10))
    }

    /// How the transcript keeps up with new text: follows while you are at the newest message,
    /// stays put while you read back, and offers a button to come back down. (Its own function:
    /// in the long modifier chain above, the compiler gave up type-checking.)
    private func followingNewest<V: View>(_ content: V, proxy: ScrollViewProxy) -> some View {
        content
    // pulling the list down is you reading back: stop following until you come back down
    .simultaneousGesture(DragGesture(minimumDistance: 12)
        .onChanged { v in
            userScrolling = true
            if v.translation.height > 16 { following = false }
        }
        // the flag outlives the gesture a moment: the scroll carries on after your
        // thumb leaves, and it is still your scroll that lands at the bottom
        .onEnded { _ in
            let token = UUID(); scrollToken = token
            Task { try? await Task.sleep(for: .milliseconds(900))
                   if scrollToken == token { userScrolling = false } }
        })
    // the answer's live rows turn into saved rows of another height when it ends, and a
    // reload replaces them again: settle on the newest message once they have laid out
    .onChange(of: state.streaming) { _, on in if !on { settle(proxy) } }
    .onChange(of: state.messages.last?.id) { _, _ in settle(proxy) }
    .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardDidShowNotification)) { _ in
        settle(proxy)
    }
    // what you send always brings you down; what arrives only follows you if you are
    // already at the bottom -- reading further up, you stay where you are
    .onChange(of: state.messages.count) { _, n in
        // fewer messages than were cleared (a rewind, a reload): nothing older to hide
        if let c = cleared, n < c.count { cleared = nil }
        if state.messages.last?.isUser == true { following = true; scroll(proxy) } else { follow(proxy) }
    }
    .onChange(of: state.liveText) { _, _ in follow(proxy, animated: false) }
    .onChange(of: state.liveRuns.count + state.liveSteps.count) { _, _ in follow(proxy) }
    .onChange(of: state.chatExtras.question?.id) { _, _ in follow(proxy) }
    .onChange(of: state.chatExtras.approval?.id) { _, _ in follow(proxy) }
    .onChange(of: scrollDownRequest) { _, _ in following = true; newBelow = false; scroll(proxy) }
    .onChange(of: state.messages.count, initial: true) { _, n in
        if n > 110 { lazyTranscript = true } else if n < 70 { lazyTranscript = false }
    }
    }

    /// Keeps up with a growing answer only while you are at the bottom; otherwise marks
    /// that something new arrived below.
    private func follow(_ proxy: ScrollViewProxy, animated: Bool = true) {
        if following { scroll(proxy, animated: animated) } else { newBelow = true }
    }

    /// Back to the newest message after the rows have been measured -- twice, because a
    /// lazy list measures rows it has not drawn only as they come on screen.
    private func settle(_ proxy: ScrollViewProxy) {
        guard following else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) { scroll(proxy, animated: false) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { if following { scroll(proxy, animated: false) } }
    }

    /// Opening a chat lands on its newest message. A long chat is drawn lazily from
    /// estimated row heights, so one jump to the end fell short (it opened partway up); keep
    /// going to the end while the rows measure themselves, for a couple of seconds, unless
    /// you start scrolling.
    private func pinToNewest(_ proxy: ScrollViewProxy) async {
        following = true
        for _ in 0..<16 {
            guard following, !Task.isCancelled else { return }
            scroll(proxy, animated: false)
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
    }

    private func scroll(_ proxy: ScrollViewProxy, animated: Bool = true) {
        // an empty chat is its home page: start at the greeting, not the bottom of the cards
        let empty = isHome
        let last = transcriptRows.last?.index ?? -1
        let go = {
            if empty { proxy.scrollTo("home", anchor: .top); return }
            // the last message's own row first: in a long lazy list the end marker alone
            // is placed from estimated heights and the jump stopped partway up
            if last >= 0 { proxy.scrollTo("row-\(last)", anchor: .bottom) }
            proxy.scrollTo("bottom", anchor: .bottom)
        }
        if animated && !reduceMotion { withAnimation(.easeOut(duration: 0.18)) { go() } } else { go() }
    }

    // ------------------------------------------------------------ find

    private var findMatches: [Int] {
        let q = findText.trimmingCharacters(in: .whitespaces).lowercased()
        guard q.count >= 2 else { return [] }
        return state.messages.enumerated().compactMap { $0.element.text.lowercased().contains(q) ? $0.offset : nil }
    }

    private var findBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
            TextField("Find in this chat", text: $findText)
                .textFieldStyle(.plain)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($findFocused)
                .submitLabel(.search)
                .onSubmit { step(1) }
                .onChange(of: findText) { _, _ in
                    findAt = 0
                    if let first = findMatches.first { jumpTo = first }
                }
            if !findMatches.isEmpty {
                Text("\(findAt + 1) of \(findMatches.count)")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            } else if findText.count >= 2 {
                Text("none").font(.caption).foregroundStyle(.secondary)
            }
            Button { step(-1) } label: { Image(systemName: "chevron.up") }
                .disabled(findMatches.isEmpty)
            Button { step(1) } label: { Image(systemName: "chevron.down") }
                .disabled(findMatches.isEmpty)
            Button("Done") { finding = false; findText = ""; flashed = nil }
                .font(.callout.weight(.semibold))
        }
        .padding(.horizontal, 14).padding(.vertical, 9)
        .background(.bar)
        .overlay(Divider(), alignment: .bottom)
    }

    private func step(_ by: Int) {
        let m = findMatches
        guard !m.isEmpty else { return }
        findAt = ((findAt + by) % m.count + m.count) % m.count
        jumpTo = m[findAt]
    }

    // ------------------------------------------------------------ commands

    /// `/new`, `/model`, `/compact`, `/find` and Claude Code's transcript
    /// commands — typed, or tapped from the menu.
    private func command(_ raw: String) -> Bool {
        let rest = raw.split(separator: " ", maxSplits: 1).dropFirst().joined()
            .trimmingCharacters(in: .whitespaces)
        switch raw.lowercased().split(separator: " ").first.map(String.init) ?? "" {
        case "/new":
            Task { if let sid = await state.newChat() { state.deepLink = sid } }
        case "/model":   showModels = true
        case "/compact": Task { await state.compactCurrent() }
        case "/find":
            finding = true; findFocused = true
            if !rest.isEmpty { findText = rest }
        case "/rewind":
            if state.messages.contains(where: \.isUser) { actionsModel.showRewind = true }
            else { state.toast("Nothing to rewind to yet") }
        case "/context":     actionsModel.showContext = true
        case "/copy":        state.copyAnswer(Int(rest) ?? 1)
        case "/diff":        actionsModel.showDiffs = true
        case "/files":       actionsModel.showFiles = true
        case "/verbose":
            verboseTools.toggle()
            state.toast(verboseTools ? "Showing every tool call in full" : "Tool calls folded again")
        case "/todos":
            todosHidden.toggle()
            state.toast(todosHidden ? "Todo list hidden" : "Todo list shown")
        case "/usage":       actionsModel.showStats = true
        case "/permissions": actionsModel.showPermissions = true
        case "/theme":
            let order = ["system", "light", "dark"]
            theme = order[((order.firstIndex(of: theme) ?? 0) + 1) % order.count]
            state.toast("Theme: \(theme)")
        case "/fork":
            guard let last = state.messages.last(where: \.isUser) else {
                state.toast("Nothing to fork yet"); return true
            }
            Task { await state.fork(from: last) }
        case "/jump":        actionsModel.showJump = true
        case "/stats":       actionsModel.showStats = true
        case "/hidetools":
            hideTools.toggle()
            state.toast(hideTools ? "Finished tool rows hidden" : "Tool rows shown")
        case "/clear":
            // the screen only, until the chat is opened again: emptying `messages` was
            // undone by the next reload and could be cached as the whole chat
            cleared = (sid, state.messages.count)
        case "/help":        actionsModel.showHelp = true
        default: return false
        }
        return true
    }

    /// The whole conversation as one PDF page, for anyone without Orbit.
    @MainActor private func makePDF() {
        let title = state.openChat?.title ?? "Chat"
        let page = TranscriptPage(title: title, messages: state.messages)
        let renderer = ImageRenderer(content: page)
        renderer.proposedSize = .init(width: 612, height: nil)
        let safe = title.replacingOccurrences(of: "/", with: "-").prefix(60)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(safe).pdf")
        renderer.render { size, draw in
            var box = CGRect(origin: .zero, size: size)
            guard let consumer = CGDataConsumer(url: url as CFURL),
                  let pdf = CGContext(consumer: consumer, mediaBox: &box, nil) else { return }
            pdf.beginPDFPage(nil)
            draw(pdf)
            pdf.endPDFPage()
            pdf.closePDF()
        }
        pdfURL = url
    }

    /// Put a message into the composer as a quote, so a follow-up can point at it.
    private func quote(_ m: Message) {
        let quoted = m.text.split(separator: "\n", omittingEmptySubsequences: false)
            .map { "> " + $0 }.joined(separator: "\n")
        draft = (draft.isEmpty ? "" : draft + "\n") + quoted + "\n\n"
        typing = true
    }

    /// The answer being written: the steps it has finished, then the one in hand.
    /// It continues the block above when that is already this answer's.
    /// The step being written now (the finished steps are rows of their own above it).
    private var liveStepInHand: some View {
        let continues = state.messages.last.map { !$0.isUser } ?? false
        return VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 7) {
                if state.liveSteps.isEmpty && !continues {
                    Text(state.liveModel.isEmpty ? currentModelName : state.liveModel)
                        .font(.caption2.smallCaps())
                        .foregroundStyle(.secondary)
                }

                if !state.liveStatus.isEmpty && state.liveText.isEmpty && state.liveRuns.isEmpty {
                    HStack(spacing: 7) {
                        ProgressView().controlSize(.mini)
                        Text(state.liveStatus).font(.footnote).foregroundStyle(.secondary)
                    }
                }

                if !state.liveText.isEmpty { MarkdownText(state.liveText) }
                ForEach(state.liveTools, id: \.self) { ToolLine(text: $0) }
                if !state.liveRuns.isEmpty { ToolRunsView(runs: state.liveRuns) }
                LiveTurnExtras()

                if !state.liveThinking.isEmpty {
                    ThinkingBlock(text: state.liveThinking,
                                  live: state.liveThoughtSecs == nil && state.liveText.isEmpty && state.liveRuns.isEmpty,
                                  secs: state.liveThoughtSecs)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // ------------------------------------------------------------ composer

    private var composer: some View {
        VStack(spacing: 0) {
            // back to the newest message: sits on top of the box, where the scroll view's own
            // bottom edge (behind the box) would hide it
            if !atBottom && (newBelow || state.streaming) {
                Button {
                    scrollDownRequest += 1
                } label: {
                    Label(newBelow ? "New messages" : "Latest", systemImage: "arrow.down")
                        .font(.footnote.weight(.semibold))
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .background(.regularMaterial, in: Capsule())
                        .shadow(color: .black.opacity(0.12), radius: 6, y: 2)
                }
                .buttonStyle(.plain)
                .padding(.vertical, 6)
                .frame(maxWidth: .infinity)
                .background(Color(uiColor: .systemBackground).opacity(0.001))
                .transition(.opacity)
                .accessibilityHint("Scrolls to the newest message")
            }
            TodoDock(sid: sid)
            GitDock(sid: sid)
            AnswerStatusLine(sid: sid)
            Composer(draft: $draft, typing: $typing, modelName: currentModelName,
                     onPickModel: { showModels = true },
                     onCommand: { command($0) })
        }
        .background(.bar)       // one bar behind the todo list, status line and box
    }
}

/// A conversation laid out for paper. Plots are left out; the words are what travel.
struct TranscriptPage: View {
    let title: String
    let messages: [Message]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                Image("OrbitMark").resizable().scaledToFit().frame(width: 22, height: 22)
                Text(title).font(.title3.weight(.semibold))
            }
            ForEach(messages) { m in
                VStack(alignment: .leading, spacing: 4) {
                    Text(m.isUser ? "You" : (m.model ?? "Orbit"))
                        .font(.caption.smallCaps()).foregroundStyle(.secondary)
                    if m.isUser {
                        Text(m.text)
                    } else {
                        MarkdownText(m.text)
                    }
                }
            }
        }
        .padding(36)
        .frame(width: 612, alignment: .leading)
        .background(Color.white)
        .environment(\.colorScheme, .light)
    }
}

extension View {
    /// Hands the view to a function mid-chain, so a long chain can be split up.
    func apply<V: View>(@ViewBuilder _ transform: (Self) -> V) -> V { transform(self) }
}
