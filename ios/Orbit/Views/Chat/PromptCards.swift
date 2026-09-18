import SwiftUI

/// Whatever the running answer is waiting on you for: a question, an approval,
/// or — once it stopped at its limit — whether to continue. Shown in the
/// transcript where the answer is, rather than as an alert that hides it.
struct ChatPromptCards: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(spacing: 12) {
            if let q = state.chatExtras.question {
                QuestionCard(question: q).id(q.id)
            }
            if let a = state.chatExtras.approval {
                ApprovalCard(prompt: a).id(a.id)
            } else if let p = state.pendingApproval, !p.id.isEmpty {
                // a Mac that sends only the short form still gets an answer
                ApprovalCard(prompt: ApprovalPrompt(["id": p.id, "name": p.name, "reason": p.reason])!)
                    .id(p.id)
            }
            if let why = state.chatExtras.roundLimit, !state.streaming {
                ContinueCard(reason: why)
            }
        }
    }
}

private struct CardChrome<Content: View>: View {
    var tint: Color = .accentColor
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10, content: content)
            .padding(13)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(tint.opacity(0.08), in: .rect(cornerRadius: 13))
            .overlay(RoundedRectangle(cornerRadius: 13).strokeBorder(tint.opacity(0.35)))
    }
}

/// `ask_user`: tap an option, tick several, or type your own answer.
struct QuestionCard: View {
    let question: AskQuestion
    @EnvironmentObject var state: AppState
    @State private var picked: Set<String> = []
    @State private var typed = ""
    @State private var sending = false

    var body: some View {
        CardChrome {
            Label {
                Text(question.question).font(.callout.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
            } icon: {
                Image(systemName: "questionmark.bubble").foregroundStyle(.tint)
            }
            if question.multiple && !question.options.isEmpty {
                ForEach(question.options, id: \.self) { o in
                    Button {
                        if picked.contains(o) { picked.remove(o) } else { picked.insert(o) }
                        Haptics.tap()
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: picked.contains(o) ? "checkmark.square.fill" : "square")
                                .foregroundStyle(picked.contains(o) ? Color.accentColor : .secondary)
                            Text(o).foregroundStyle(.primary).multilineTextAlignment(.leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
                Button("Send \(picked.count) selected") {
                    send(question.options.filter { picked.contains($0) })
                }
                .buttonStyle(.borderedProminent)
                .disabled(picked.isEmpty || sending)
            } else if !question.options.isEmpty {
                FlowButtons(options: question.options, disabled: sending) { send([$0]) }
            }
            HStack(spacing: 8) {
                TextField(question.options.isEmpty ? "Type your answer" : "Or type your own answer",
                          text: $typed, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.roundedBorder)
                    .submitLabel(.send)
                    .onSubmit { sendTyped() }
                Button("Send") { sendTyped() }
                    .disabled(typed.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || sending)
            }
        }
    }

    private func sendTyped() {
        let t = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        // a typed answer goes as one string, even to a multiple-choice question
        send([t], single: true)
    }

    private func send(_ answer: [String], single: Bool = false) {
        guard !sending else { return }
        sending = true
        Haptics.success()
        var q = question
        if single { q.multiple = false }
        Task {
            _ = await state.answerQuestion(q, with: answer)
            sending = false
        }
    }
}

/// Options as a wrapping row of buttons, the first one prominent.
private struct FlowButtons: View {
    let options: [String]
    var disabled: Bool
    var tap: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(options.enumerated()), id: \.offset) { i, o in
                if i == 0 {
                    Button(o) { tap(o) }.buttonStyle(.borderedProminent).disabled(disabled)
                } else {
                    Button(o) { tap(o) }.buttonStyle(.bordered).disabled(disabled)
                }
            }
        }
    }
}

/// An approval, with the arguments and any diff to judge it by. "Always" saves
/// a rule (a Claude Code permission rule for Claude Code); for Codex it allows
/// the rest of that session.
struct ApprovalCard: View {
    let prompt: ApprovalPrompt
    @EnvironmentObject var state: AppState
    @State private var mode: Mode = .buttons
    @State private var pattern = ""
    @State private var reason = ""
    @State private var sending = false
    @State private var showArgs = false

    enum Mode { case buttons, always, deny }

    private var engine: String? {
        prompt.claude ? "Claude Code" : prompt.codex ? "Codex" : nil
    }

    var body: some View {
        CardChrome(tint: .orange) {
            HStack(alignment: .firstTextBaseline) {
                Label(engine.map { "\($0) asks" } ?? "Needs your approval",
                      systemImage: "hand.raised.fill")
                    .font(.caption.weight(.semibold)).foregroundStyle(.orange)
                Spacer()
                Text(prompt.name).font(.caption.monospaced()).foregroundStyle(.secondary)
            }
            if !prompt.reason.isEmpty {
                Text(prompt.reason).font(.callout).fixedSize(horizontal: false, vertical: true)
            }
            if !prompt.args.isEmpty {
                DisclosureGroup(isExpanded: $showArgs) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(prompt.args, id: \.key) { kv in
                            Text("\(kv.key): \(prompt.diff != nil && kv.value.count > 300 ? String(kv.value.prefix(300)) + "…" : kv.value)")
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                                .lineLimit(showArgs ? 40 : 2)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                } label: {
                    Text("details").font(.caption)
                }
            }
            if let diff = prompt.diff, !diff.isEmpty {
                DiffView(diff: diff, path: prompt.diffPath)
            }
            switch mode {
            case .buttons: buttons
            case .always: alwaysRow
            case .deny: denyRow
            }
        }
        .disabled(sending)
    }

    private var buttons: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button("Allow once") { reply(ApprovalReply(allow: true)) }
                    .buttonStyle(.borderedProminent)
                Button("Deny", role: .destructive) { reply(ApprovalReply(allow: false)) }
                    .buttonStyle(.bordered)
            }
            HStack(spacing: 8) {
                if prompt.codex {
                    Button("Allow for this session") { reply(ApprovalReply(allow: true, always: true)) }
                        .buttonStyle(.bordered)
                } else {
                    Button(prompt.claude ? "Don't ask again…" : "Always allow…") {
                        pattern = prompt.suggestedPattern
                        mode = .always
                    }
                    .buttonStyle(.bordered)
                }
                Button("Deny with reason…") { mode = .deny }
                    .buttonStyle(.bordered)
            }
            .font(.callout)
        }
    }

    private var alwaysRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(prompt.claude ? "Permission rule, e.g. Bash(git diff:*)" : "Pattern", text: $pattern)
                .textFieldStyle(.roundedBorder)
                .font(.callout.monospaced())
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            if prompt.claude {
                Text("Saved as a Claude Code permission rule, so Claude stops asking about this.")
                    .font(.caption).foregroundStyle(.secondary)
                let others = prompt.suggestions.filter { $0 != pattern }
                if !others.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(others, id: \.self) { s in
                                Button(s) { pattern = s }
                                    .font(.caption.monospaced()).buttonStyle(.bordered)
                            }
                        }
                    }
                }
            }
            HStack {
                Button(prompt.claude ? "Don't ask again" : "Always allow this") {
                    reply(ApprovalReply(allow: true, always: true, pattern: pattern,
                                        note: "\(prompt.name): \(pattern)"))
                }
                .buttonStyle(.borderedProminent)
                Button("Cancel") { mode = .buttons }
            }
        }
    }

    private var denyRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Why not — it reads this and changes course", text: $reason, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.roundedBorder)
            HStack {
                Button("Deny", role: .destructive) {
                    reply(ApprovalReply(allow: false, message: reason.trimmingCharacters(in: .whitespacesAndNewlines)))
                }
                .buttonStyle(.borderedProminent)
                Button("Cancel") { mode = .buttons }
            }
        }
    }

    private func reply(_ r: ApprovalReply) {
        guard !sending else { return }
        sending = true
        Haptics.press()
        Task {
            await state.answerApproval(prompt, r)
            sending = false
        }
    }
}

/// A unified diff, added lines green and removed lines red.
struct DiffView: View {
    let diff: String
    var path: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let path {
                Text((path as NSString).lastPathComponent)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 9).padding(.vertical, 5)
            }
            ScrollView([.horizontal, .vertical]) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(diff.split(separator: "\n", omittingEmptySubsequences: false).prefix(400).enumerated()),
                            id: \.offset) { _, line in
                        Text(String(line))
                            .font(.caption2.monospaced())
                            .foregroundStyle(color(line))
                            .fixedSize(horizontal: true, vertical: false)
                    }
                }
                .padding(8)
            }
            .frame(maxHeight: 220)
        }
        .background(.quaternary.opacity(0.35), in: .rect(cornerRadius: 9))
    }

    private func color(_ l: Substring) -> Color {
        if l.hasPrefix("+") && !l.hasPrefix("+++") { return .green }
        if l.hasPrefix("-") && !l.hasPrefix("---") { return .red }
        return .primary
    }
}

/// The answer stopped at its round or time limit.
struct ContinueCard: View {
    let reason: String
    @EnvironmentObject var state: AppState
    @ObservedObject private var extras = TranscriptExtras.shared

    var body: some View {
        CardChrome(tint: .blue) {
            Label("The answer \(reason) without finishing", systemImage: "pause.circle")
                .font(.callout)
            // the plan steps it had not reached
            if let sid = state.openChat?.sid, let pending = extras.roundPending[sid], !pending.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("still outstanding:").font(.caption).foregroundStyle(.secondary)
                    ForEach(Array(pending.enumerated()), id: \.offset) { _, t in
                        Text("• " + t).font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            HStack {
                Button("Continue") { Task { await state.continueAnswer() } }
                    .buttonStyle(.borderedProminent)
                Button("Dismiss") { state.chatExtras.roundLimit = nil }
            }
        }
    }
}
