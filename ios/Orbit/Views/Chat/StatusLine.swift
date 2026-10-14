import SwiftUI

/// While an answer runs, one line says what is happening — a spinner, a word
/// for the work, how long, roughly how much has come back, what it is doing
/// now — and offers Stop. The shape Claude Code uses.
struct AnswerStatusLine: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let spin = ["·", "✢", "✳", "✶", "✻", "✽"]
    /// Forward, then back, without repeating the ends.
    private static let frames = spin + spin.dropFirst().dropLast().reversed()
    /// How thinking is described as it goes on, the way Claude Code escalates it.
    private static let thinkLadder: [(Double, String)] = [
        (45, "Deep in thought"), (30, "Thinking some more"), (20, "Thinking more"),
        (10, "Still thinking"), (0, "Thinking"),
    ]

    var body: some View {
        // another chat's answer does not own this line
        if state.streaming, state.liveSid == sid {
            TimelineView(.periodic(from: .now, by: reduceMotion ? 1 : 0.14)) { ctx in
                line(at: ctx.date)
            }
            .padding(.horizontal, 14).padding(.vertical, 5)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func line(at now: Date) -> some View {
        let tick = Int(now.timeIntervalSinceReferenceDate / 0.14)
        return HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(Self.frames[tick % Self.frames.count])
                .font(.footnote.monospaced().weight(.bold))
                .frame(width: 12)
            Text(verb(at: now) + "…").font(.footnote.weight(.semibold))
            Text("(" + meta(at: now) + ")")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.tail)
                .layoutPriority(-1)
            Spacer(minLength: 4)
            Button {
                Haptics.tap()
                Task { await state.stopGenerating() }
            } label: {
                Text("Stop").font(.caption.weight(.semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.red)
            .accessibilityLabel("Stop the answer")
        }
        .foregroundStyle(Color.orange)
        .accessibilityElement(children: .combine)
    }

    private func verb(at now: Date) -> String {
        guard let since = state.liveThinkingSince else { return state.liveVerb }
        let t = now.timeIntervalSince(since)
        return Self.thinkLadder.first { t >= $0.0 }?.1 ?? "Thinking"
    }

    private func meta(at now: Date) -> String {
        var parts = [ToolText.secs(now.timeIntervalSince(state.liveStartedAt))]
        let tokens = state.liveChars / 4
        if tokens >= 30 { parts.append("↓ ~\(Self.tokens(tokens)) tokens") }
        if let r = state.liveRuns.last(where: \.running) {
            parts.append(ToolText.verb(r.display) + " " + String(r.target.prefix(40)))
        } else if !state.liveStatus.isEmpty {
            parts.append(state.liveStatus)
        }
        return parts.joined(separator: " · ")
    }

    static func tokens(_ n: Int) -> String {
        guard n >= 1000 else { return String(n) }
        let s = String(format: "%.1f", Double(n) / 1000)
        return (s.hasSuffix(".0") ? String(s.dropLast(2)) : s) + "k"
    }
}

/// The plan tool's list above the composer: "todos 2/5 · ◼ current step",
/// opening to every step. `/todos` hides or shows it.
struct TodoDock: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @AppStorage("orbit.todosHidden") private var hidden = false
    @State private var open = false

    var body: some View {
        let steps = state.plans[sid] ?? []
        let remaining = steps.filter { !$0.done }
        // a finished plan is worth reading — it is the account of what it just did — so
        // the dock stays with every step ticked rather than vanishing at the last one
        if !hidden, !steps.isEmpty {
            let current = remaining.first(where: \.active) ?? remaining.first
            VStack(alignment: .leading, spacing: 6) {
                Button {
                    withAnimation(.easeInOut(duration: 0.15)) { open.toggle() }
                } label: {
                    HStack(spacing: 5) {
                        Text("todos \(steps.count - remaining.count)/\(steps.count)").fontWeight(.semibold)
                        Text(current.map { "· \u{25FC} " + $0.text } ?? "· all done")
                            .foregroundStyle(.secondary).lineLimit(1)
                        Spacer(minLength: 4)
                        Image(systemName: open ? "chevron.down" : "chevron.up").font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                    .font(.caption)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityHint(open ? "Hides the plan" : "Shows the whole plan")
                // A twenty-step plan is taller than the screen, and with the keyboard up
                // it pushed the message box — and the answer — out of sight entirely.
                // The header stays put and only the list scrolls.
                if open {
                    ScrollViewReader { sp in
                        ScrollView {
                            TodoList(steps: steps)
                                .id("todos")
                        }
                        .frame(maxHeight: min(CGFloat(steps.count) * 26 + 8, 200))
                        .scrollBounceBehavior(.basedOnSize)
                        .onAppear {
                            if let i = steps.firstIndex(where: { $0.active && !$0.done }) {
                                sp.scrollTo("todo-\(i)", anchor: .center)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(Divider(), alignment: .top)
        }
    }
}

/// What the folder this chat works in looks like right now. "What did it change while I
/// was away" is the question a phone gets asked most, and the branch name alone in the
/// bar above the transcript was not an answer to it.
struct GitDock: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @AppStorage("orbit.gitDockOpen") private var open = false
    @State private var git: GitState?
    @State private var at = Date.distantPast
    @State private var shown: (path: String, diff: String)?
    /// Comments on diff lines, for the model: (file, line, comment).
    @State private var notes: [(path: String, line: String, text: String)] = []
    @State private var commenting: (path: String, line: String)?
    @State private var comment = ""

    /// Read again when a turn lands or an answer starts or ends — not on every token.
    private var key: String { "\(sid)|\(state.messages.count)|\(state.streaming)" }

    var body: some View {
        Group {
            if let g = git, g.dirty > 0 || g.ahead > 0 || g.behind > 0 || g.op != nil {
                VStack(alignment: .leading, spacing: 5) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.15)) { open.toggle() }
                    } label: {
                        HStack(spacing: 5) {
                            Image(systemName: "arrow.trianglehead.branch").font(.caption2)
                            Text(g.short).lineLimit(1)
                                .foregroundStyle(g.dirty > 0 ? .orange : .secondary)
                            Spacer(minLength: 4)
                            Image(systemName: open ? "chevron.down" : "chevron.up")
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                        .font(.caption)
                        .contentShape(.rect)
                    }
                    .buttonStyle(.plain)
                    if open {
                        VStack(alignment: .leading, spacing: 2) {
                            if !g.diff.isEmpty { Text(g.diff) }
                            if g.untracked > 0 { Text("\(g.untracked) untracked") }
                            if !g.last.isEmpty { Text("last: " + g.last).lineLimit(2) }
                            // each changed file; a tap shows its diff
                            ScrollView {
                                VStack(alignment: .leading, spacing: 3) {
                                    ForEach(g.files.prefix(40)) { f in
                                        Button { Task { await show(f.path) } } label: {
                                            HStack(spacing: 6) {
                                                Text(f.status == "?" ? "new" : f.status == "U" ? "conflict" : f.status)
                                                    .font(.caption2.monospaced())
                                                    .foregroundStyle(f.status == "U" ? .red : f.status == "?" || f.status == "A" ? .green : .secondary)
                                                    .frame(minWidth: 30, alignment: .leading)
                                                Text(f.path).lineLimit(1).truncationMode(.middle)
                                                if let a = f.added {
                                                    Text("+\(a) −\(f.removed ?? 0)").font(.caption2.monospacedDigit())
                                                        .foregroundStyle(.secondary)
                                                }
                                            }
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                            }
                            .frame(maxHeight: 140)
                        }
                        .font(.caption2).foregroundStyle(.secondary)
                        .frame(maxHeight: 220, alignment: .top)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(Divider(), alignment: .top)
            }
        }
        .sheet(isPresented: Binding(get: { shown != nil }, set: { if !$0 { shown = nil } })) {
            if let s = shown {
                NavigationStack {
                    ScrollView {
                        DiffView(diff: s.diff, path: s.path) { line in
                            comment = ""; commenting = (s.path, line)
                        }
                        .padding()
                        Text("Tap a line to comment on it; the comments go into your message.")
                            .font(.caption2).foregroundStyle(.secondary).padding(.horizontal)
                    }
                    .navigationTitle((s.path as NSString).lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        if !notes.isEmpty {
                            ToolbarItem(placement: .bottomBar) {
                                Button("Add \(notes.count) comment\(notes.count == 1 ? "" : "s") to message") { sendNotes() }
                            }
                        }
                        ToolbarItem(placement: .confirmationAction) { Button("Done") { shown = nil } }
                    }
                    .alert("Comment on this line", isPresented: Binding(
                        get: { commenting != nil }, set: { if !$0 { commenting = nil } })) {
                        TextField("What should change here?", text: $comment)
                        Button("Add") {
                            if let c = commenting, !comment.trimmingCharacters(in: .whitespaces).isEmpty {
                                notes.append((c.path, c.line, comment.trimmingCharacters(in: .whitespaces)))
                            }
                            commenting = nil
                        }
                        Button("Cancel", role: .cancel) { commenting = nil }
                    } message: {
                        Text(commenting?.line.trimmingCharacters(in: .whitespaces) ?? "")
                    }
                }
            }
        }
        .task(id: key) {
            guard let server = state.server, Date().timeIntervalSince(at) > 10 else { return }
            do {
                // a chat that is not in a repository answers nil, and the strip is not
                // drawn. `try?` would turn the CANCELLATION that .task(id:) performs on
                // every key change into that same nil — the dock vanished and the stamp
                // below then blocked the replacement for ten seconds.
                let g = try await server.gitState(sid: sid)
                git = g
                at = Date()
            } catch {
                // cancelled, or one dropped request: keep what is on screen and let the
                // next key change try again straight away
            }
        }
    }
}

extension GitDock {
    /// The comments, into the message box as review notes for the model.
    fileprivate func sendNotes() {
        let lines = notes.map { n in
            "- \((n.path as NSString).lastPathComponent): `\(n.line.trimmingCharacters(in: .whitespaces).prefix(160))` — \(n.text)"
        }
        state.quoteInDraftPlain("Comments on your changes:\n" + lines.joined(separator: "\n"))
        notes = []
        shown = nil
    }

    fileprivate func show(_ path: String) async {
        guard let server = state.server else { return }
        do {
            let d = try await server.gitDiff(sid: sid, path: path)
            shown = (path, d.isEmpty ? "No changes to show (a binary file, or it matches the last commit)." : d)
        } catch {
            state.toast("Couldn't read that diff: " + error.localizedDescription)
        }
    }
}

/// Under the message box: the permission mode, the way Claude Code keeps it
/// in view ("⏵⏵ accept edits on"). Tap to cycle it.
struct PermissionModeLine: View {
    @EnvironmentObject var state: AppState
    @State private var work: ChatWork?
    @State private var busy = false

    private var sid: String? { state.openChat?.sid }

    /// Read again when the model changes, a turn lands, or the mode changed elsewhere.
    private var refreshKey: String {
        "\(sid ?? "")|\(state.currentModel ?? "")|\(state.streaming)|\(state.chatExtras.workRevision)"
    }

    private var mode: PermissionMode {
        if let work, work.engine { return work.mode }
        return state.chatExtras.planMode ? .plan : .ask
    }

    var body: some View {
        // Always laid out, so it moves with the box above it. Put in only once the chat's
        // id arrived, it was inserted mid-way through the chat opening and slid into place
        // on its own, across the box.
        Group {
            VStack(spacing: 0) {
                Button {
                    guard !busy else { return }
                    busy = true
                    Task {
                        if let next = await state.cycleMode(work: work) { work?.mode = next }
                        busy = false
                    }
                } label: {
                    HStack(spacing: 4) {
                        Text(Self.text(mode)).foregroundStyle(Self.tint(mode))
                        // always laid out, only shown: inserted, it was drawn mid-animation
                        // at its old place, over the message box
                        Text("· tap to cycle").foregroundStyle(.tertiary)
                            .opacity(mode != .ask ? 1 : 0).accessibilityHidden(mode == .ask)
                        Spacer(minLength: 0)
                    }
                    .font(.caption2.weight(.medium))
                    .padding(.horizontal, 16).padding(.bottom, 6)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .disabled(busy || sid == nil)
                .accessibilityLabel("Permission mode: \(mode.label)")
                .accessibilityHint("Changes to the next mode")
            }
        }
        .task(id: refreshKey) {
            guard let sid, let server = state.server else { return }
            if let w = try? await server.chatWork(sid: sid), state.openChat?.sid == sid { work = w }
        }
    }

    static func text(_ m: PermissionMode) -> String {
        switch m {
        case .ask: return "⏵ default mode · tap to cycle"
        case .acceptEdits: return "⏵⏵ accept edits on"
        case .plan: return "⏸ plan mode on"
        case .auto: return "⏵⏵ auto mode on"
        case .dontAsk: return "⏵⏵ don't ask on"
        case .bypass: return "⏵⏵ bypass permissions on"
        }
    }

    static func tint(_ m: PermissionMode) -> Color {
        switch m {
        case .ask: return .secondary.opacity(0.7)
        case .acceptEdits: return .accentColor
        case .plan: return Color(red: 0.55, green: 0.45, blue: 0.85)
        case .auto: return .orange
        case .dontAsk: return .secondary
        case .bypass: return .red
        }
    }
}
