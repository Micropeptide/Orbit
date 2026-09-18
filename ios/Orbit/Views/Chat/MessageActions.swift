import SwiftUI

/// The per-message actions a chat offers, and the sheets they open. One
/// `ChatActionsModel` per chat screen holds what is presented, so the chat
/// view only has to attach `ChatActionsHost` and pass `actions` to each bubble.
@MainActor
final class ChatActionsModel: ObservableObject {
    @Published var citations: CitationsRequest?
    @Published var undo: Message?
    @Published var askSkillName = false
    @Published var skillName = ""
    @Published var confirmRegenerate: Bool? = nil        // false = regenerate, true = deeper
    @Published var showJump = false
    @Published var showStats = false
    @Published var exportURL: URL?
    @Published var confirmBurn = false
    /// Row index to scroll to, picked in the jump sheet.
    @Published var jumpRequest: Int?
    // the Claude Code commands' sheets: /rewind, /context, /diff, /help, /permissions
    @Published var showRewind = false
    @Published var showContext = false
    @Published var showDiffs = false
    @Published var showHelp = false
    @Published var showPermissions = false
    /// A command picked in /help, for the message box.
    @Published var helpPick: String?
    /// Every file the chat names (/files).
    @Published var showFiles = false
    /// One of your messages to ask again from, or to rewind to, once confirmed.
    @Published var retryFrom: Message?
    @Published var rewindTo: Message?

    struct CitationsRequest: Identifiable {
        let id = UUID()
        let text: String
    }

    func actions(_ state: AppState) -> MessageActions {
        MessageActions(
            busy: state.streaming,
            fork: { m in Task { await state.fork(from: m) } },
            regenerate: { [weak self] in self?.confirmRegenerate = false },
            retryDeeper: { [weak self] in self?.confirmRegenerate = true },
            continueAnswer: { Task { await state.continueAnswer() } },
            checkDOIs: { [weak self] m in self?.citations = CitationsRequest(text: m.text) },
            saveSkill: { [weak self] in
                self?.skillName = "captured-\(Int(Date.now.timeIntervalSince1970) % 10000)"
                self?.askSkillName = true
            },
            undo: { [weak self] m in self?.undo = m },
            retryFrom: { [weak self] m in self?.retryFrom = m },
            rewindTo: { [weak self] m in self?.rewindTo = m },
            export: { [weak self] url in self?.exportURL = url },
            title: state.openChat?.title ?? "Answer")
    }
}

struct MessageActions {
    var busy: Bool
    var fork: (Message) -> Void
    var regenerate: () -> Void
    var retryDeeper: () -> Void
    var continueAnswer: () -> Void
    var checkDOIs: (Message) -> Void
    var saveSkill: () -> Void
    var undo: (Message) -> Void
    var retryFrom: (Message) -> Void = { _ in }
    var rewindTo: (Message) -> Void = { _ in }
    /// Hand a file to the share sheet.
    var export: (URL) -> Void = { _ in }
    var title = "Answer"

    /// Added to a user message's menu.
    @ViewBuilder
    func userItems(_ m: Message) -> some View {
        Button { retryFrom(m) } label: {
            Label("Retry from here", systemImage: "arrow.clockwise")
            if m.hasUnsendableAttachments {
                Text("Only its words could go again, not its attachments")
            }
        }
        .disabled(busy || m.hasUnsendableAttachments)
        Button { fork(m) } label: {
            Label("Fork from here", systemImage: "arrow.triangle.branch")
        }
        .disabled(busy)
        Button { rewindTo(m) } label: {
            Label("Rewind to here…", systemImage: "clock.arrow.circlepath")
        }
        .disabled(busy)
    }

    /// Added to an answer's menu.
    @ViewBuilder
    func answerItems(_ m: Message, isLast: Bool) -> some View {
        Menu {
            Button {
                UIPasteboard.general.string = m.text
                Haptics.success()
            } label: { Label("As Markdown", systemImage: "number") }
            Button {
                AnswerExport.copyRich(markdown: m.text, plain: m.plainText)
            } label: { Label("With formatting (Mail, Pages, Word)", systemImage: "textformat.alt") }
            Button {
                UIPasteboard.general.string = m.plainText
                Haptics.success()
            } label: { Label("As plain text", systemImage: "textformat") }
        } label: {
            Label("Copy as…", systemImage: "doc.on.clipboard")
        }
        Menu {
            Button {
                if let url = try? AnswerExport.write(m.text, name: title, ext: "md") { export(url) }
            } label: { Label("Save as Markdown…", systemImage: "number") }
            Button {
                let html = AnswerExport.document(title: title, body: AnswerExport.html(markdown: m.text))
                if let url = try? AnswerExport.write(html, name: title, ext: "html") { export(url) }
            } label: { Label("Save as HTML…", systemImage: "chevron.left.forwardslash.chevron.right") }
            Button {
                AnswerExport.print(title: title, markdown: m.text)
            } label: { Label("Print or save as PDF…", systemImage: "printer") }
        } label: {
            Label("Export answer", systemImage: "square.and.arrow.up.on.square")
        }
        Button { checkDOIs(m) } label: {
            Label("Check DOIs", systemImage: "checkmark.seal")
        }
        Button { saveSkill() } label: {
            Label("Save chat as a skill", systemImage: "wand.and.stars")
        }
        .disabled(busy)
        if isLast {
            Divider()
            Button { retryDeeper() } label: {
                Label("Retry with deeper reasoning", systemImage: "brain")
            }
            .disabled(busy)
            Button { continueAnswer() } label: {
                Label("Continue", systemImage: "arrow.right.circle")
            }
            .disabled(busy)
        }
        let n = m.undoableChanges.count
        if n > 0 {
            Divider()
            Button(role: .destructive) { undo(m) } label: {
                Label("Undo \(n) file change\(n == 1 ? "" : "s")…", systemImage: "arrow.uturn.backward")
            }
            .disabled(busy)
        }
    }
}

/// Under an answer: how long it took and what it cost, and the files it changed.
struct AnswerFooter: View {
    let message: Message
    var actions: MessageActions?

    var body: some View {
        let n = message.undoableChanges.count
        if message.statsLine != nil || (n > 0 && actions != nil) {
            HStack(spacing: 10) {
                if let s = message.statsLine {
                    let prompt = message.usage?.prompt_tokens ?? 0
                    Text(s + (prompt > 0 ? " · \(prompt.formatted()) prompt tok" : ""))
                        .font(.caption2.monospacedDigit()).foregroundStyle(.tertiary)
                }
                if n > 0, let actions {
                    Button { actions.undo(message) } label: {
                        Label("\(n) file change\(n == 1 ? "" : "s")", systemImage: "arrow.uturn.backward")
                            .font(.caption2)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.orange)
                    .disabled(actions.busy)
                }
            }
        }
    }
}

/// Sheets, dialogs and alerts for the chat actions, attached once to the chat view.
struct ChatActionsHost: ViewModifier {
    let sid: String
    @ObservedObject var model: ChatActionsModel
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var links = FileLinks.shared

    /// Later answers whose file changes can still be put back.
    private func laterChanges(after m: Message) -> Int {
        guard let i = state.messages.firstIndex(where: { $0.id == m.id }) else { return 0 }
        return state.messages[(i + 1)...].reduce(0) { $0 + $1.undoableChanges.count }
    }

    private func rewind(_ m: Message, files: Bool) {
        guard let index = state.userIndex(of: m) else { return }
        Task { _ = await state.rewind(toUserIndex: index, files: files) }
    }

    func body(content: Content) -> some View {
        content
            .sheet(item: $model.citations) { CitationsSheet(text: $0.text) }
            .sheet(item: $model.undo) { UndoChangesSheet(message: $0) }
            .sheet(isPresented: $model.showJump) {
                JumpSheet(messages: state.messages) { model.jumpRequest = $0 }
            }
            .sheet(isPresented: $model.showStats) { UsageStatsView(sid: sid) }
            .sheet(isPresented: $model.showRewind) { RewindSheet() }
            .sheet(isPresented: $model.showContext) { ContextSheet(sid: sid) }
            .sheet(isPresented: $model.showDiffs) { DiffsSheet(diffs: state.shownDiffs[sid] ?? []) }
            .sheet(isPresented: $model.showHelp) { CommandHelpSheet { model.helpPick = $0 } }
            .sheet(isPresented: $model.showPermissions) { PermissionsSheet(sid: sid) }
            .sheet(isPresented: $model.showFiles) { ChatFilesSheet(sid: sid) }
            .sheet(item: $links.missing) { MissingFileSheet(target: $0) }
            .confirmationDialog("Ask again from this message?",
                                isPresented: Binding(get: { model.retryFrom != nil },
                                                     set: { if !$0 { model.retryFrom = nil } }),
                                titleVisibility: .visible, presenting: model.retryFrom) { m in
                Button("Retry") { Task { await state.retry(from: m) } }
                Button("Cancel", role: .cancel) {}
            } message: { _ in
                Text("Everything after it is removed and it is sent again.")
            }
            .confirmationDialog("Rewind the chat to just before this message?",
                                isPresented: Binding(get: { model.rewindTo != nil },
                                                     set: { if !$0 { model.rewindTo = nil } }),
                                titleVisibility: .visible, presenting: model.rewindTo) { m in
                let later = laterChanges(after: m)
                Button("Rewind", role: .destructive) { rewind(m, files: false) }
                if later > 0 {
                    Button("Rewind and undo \(later) file change\(later == 1 ? "" : "s")", role: .destructive) {
                        rewind(m, files: true)
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: { _ in
                Text("Later messages are removed.")
            }
            .alert("Run this?", isPresented: Binding(get: { state.chatExtras.bangConfirm != nil },
                                                     set: { if !$0 { state.chatExtras.bangConfirm = nil } }),
                   presenting: state.chatExtras.bangConfirm) { c in
                Button("Run") {
                    state.chatExtras.bangConfirm = nil
                    Task { await state.runBang(c.cmd, confirmed: true) }
                }
                Button("Cancel", role: .cancel) {
                    state.chatExtras.bangConfirm = nil
                    model.helpPick = "! " + c.cmd       // back in the box to change
                }
            } message: { c in
                Text(c.cmd + "\n\n" + c.reason)
            }
            .sheet(item: $model.exportURL) { ActivityView(items: [$0]).ignoresSafeArea() }
            .alert("Save as a skill", isPresented: $model.askSkillName) {
                TextField("Skill name", text: $model.skillName)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Save") {
                    let n = model.skillName.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !n.isEmpty else { return }
                    Task { await state.captureSkill(named: n) }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Writes this chat's procedure up as a reusable skill on your Mac. It takes a little while.")
            }
            .confirmationDialog(model.confirmRegenerate == true ? "Retry with deeper reasoning?" : "Ask again?",
                                isPresented: Binding(get: { model.confirmRegenerate != nil },
                                                     set: { if !$0 { model.confirmRegenerate = nil } }),
                                titleVisibility: .visible) {
                Button(model.confirmRegenerate == true ? "Retry deeper" : "Ask again") {
                    let deeper = model.confirmRegenerate == true
                    model.confirmRegenerate = nil
                    Task { await state.regenerateLast(deeper: deeper) }
                }
                Button("Cancel", role: .cancel) { model.confirmRegenerate = nil }
            } message: {
                Text("The last answer is replaced by a new one.")
            }
            .confirmationDialog("Erase this conversation completely?", isPresented: $model.confirmBurn,
                                titleVisibility: .visible) {
                Button("Burn", role: .destructive) {
                    Task { if await state.burnTemporaryChat() { dismiss() } }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("A temporary chat is never written to disk. Burning it leaves no trace, and it cannot be recovered.")
            }
    }
}

/// Items for the chat's own menu (the toolbar's ellipsis).
struct ChatMenuItems: View {
    let sid: String
    @ObservedObject var model: ChatActionsModel
    @EnvironmentObject var state: AppState

    var body: some View {
        Button {
            Task { await state.setPlanMode(!state.chatExtras.planMode) }
        } label: {
            Label(state.chatExtras.planMode ? "Leave plan mode" : "Plan mode",
                  systemImage: state.chatExtras.planMode ? "hammer" : "list.bullet.clipboard")
        }
        Button { model.showJump = true } label: {
            Label("Jump to a message…", systemImage: "arrow.down.to.line")
        }
        Button { model.showRewind = true } label: {
            Label("Rewind…", systemImage: "clock.arrow.circlepath")
        }
        .disabled(!state.messages.contains(where: \.isUser))
        Button { model.showContext = true } label: {
            Label("Context window", systemImage: "square.grid.3x3")
        }
        Button { model.showFiles = true } label: {
            Label("Files in this chat", systemImage: "folder")
        }
        Button {
            Task {
                let title = state.openChat?.title ?? "Chat"
                let html = await AnswerExport.chatHTML(title: title, messages: state.messages, server: state.server)
                do { model.exportURL = try AnswerExport.write(html, name: title, ext: "html") }
                catch { state.lastError = error.localizedDescription }
            }
        } label: {
            Label("Export as HTML (with figures)", systemImage: "doc.richtext")
        }
        Button {
            Task {
                guard let server = state.server else { return }
                do {
                    model.exportURL = try await server.exportMarkdown(
                        sid, title: state.openChat?.title ?? "Chat")
                } catch { state.lastError = error.localizedDescription }
            }
        } label: {
            Label("Export from the Mac (.md)", systemImage: "square.and.arrow.down")
        }
        Button { model.showStats = true } label: {
            Label("Usage stats", systemImage: "chart.bar")
        }
        if state.chatExtras.tempSid == sid {
            Button(role: .destructive) { model.confirmBurn = true } label: {
                Label("Burn this chat", systemImage: "flame")
            }
            .disabled(state.streaming)
        }
    }
}

/// Chips above the transcript: plan mode, temporary chat.
struct ChatModeChips: View {
    let sid: String
    @ObservedObject var model: ChatActionsModel
    @EnvironmentObject var state: AppState

    var body: some View {
        let plan = state.chatExtras.planMode && state.openChat?.sid == sid
        let temp = state.chatExtras.tempSid == sid
        if plan || temp {
            HStack(spacing: 8) {
                if plan {
                    Button { Task { await state.setPlanMode(false) } } label: {
                        Label("plan mode · tap to leave", systemImage: "list.bullet.clipboard")
                            .font(.caption.weight(.medium))
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .background(Color.accentColor, in: .capsule)
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)
                    .accessibilityHint("It may read and propose, and change nothing")
                }
                if temp {
                    Button { model.confirmBurn = true } label: {
                        Label("temporary · burn", systemImage: "flame")
                            .font(.caption.weight(.medium))
                            .padding(.horizontal, 10).padding(.vertical, 4)
                            .background(Color.red.opacity(0.85), in: .capsule)
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
            }
            .padding(.horizontal, 14).padding(.vertical, 6)
            .background(.bar)
        }
    }
}

/// A short message floating at the bottom, and Undo after binning a chat.
struct ToastOverlay: ViewModifier {
    @EnvironmentObject var state: AppState

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            VStack(spacing: 8) {
                if let b = state.chatExtras.binned {
                    HStack(spacing: 12) {
                        Text("“\(b.title)” moved to the bin").font(.footnote).lineLimit(1)
                        Button("Undo") { Task { await state.undoBin() } }
                            .font(.footnote.weight(.semibold))
                    }
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(.thinMaterial, in: .capsule)
                }
                if let t = state.chatExtras.toast {
                    Text(t).font(.footnote.weight(.medium))
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(.thinMaterial, in: .capsule)
                        .transition(.opacity)
                }
            }
            .padding(.bottom, 70)
            .animation(.default, value: state.chatExtras.toast)
        }
    }
}
