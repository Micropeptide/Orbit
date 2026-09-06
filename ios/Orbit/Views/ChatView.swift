import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

struct ChatView: View {
    let sid: String
    /// Index of the message a search hit pointed at, so the view can land there
    /// and flash it rather than dumping you at the end of a long conversation.
    var highlight: Int? = nil
    @State private var flashed: Int? = nil
    @EnvironmentObject var state: AppState
    @State private var draft = ""
    @State private var showModels = false
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

    var body: some View {
        // The banner and composer are safe-area insets rather than VStack rows:
        // that keeps the transcript's own inset correct, so text scrolls under
        // the navigation bar instead of starting behind it.
        transcript
            .safeAreaInset(edge: .top, spacing: 0) {
                VStack(spacing: 0) {
                    ConnectionBanner()
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
                        Button { renaming = true; newTitle = state.openChat?.title ?? "" } label: {
                            Label("Rename", systemImage: "pencil")
                        }
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
                        Button { finding = true; findFocused = true } label: {
                            Label("Find in chat", systemImage: "magnifyingglass")
                        }
                        .keyboardShortcut("f", modifiers: .command)
                        Button {
                            Task { await state.compactCurrent() }
                        } label: {
                            Label("Compact history", systemImage: "arrow.down.right.and.arrow.up.left")
                        }
                        Divider()
                        Button(role: .destructive) { confirmBin = true } label: {
                            Label("Move to bin", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .accessibilityLabel("Chat options")
                    .disabled(state.streaming)
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
            .sheet(item: $pdfURL) { ActivityView(items: [$0]).ignoresSafeArea() }
            .onChange(of: state.draftPrefill) { _, text in
                guard let text else { return }
                draft = text; typing = true; state.draftPrefill = nil
            }
            .onChange(of: draft) { _, text in Drafts.save(sid, text) }
            .alert("Approve this?", isPresented: approvalBinding) {
                Button("Allow", role: .destructive) {
                    Task { await state.answer(approval: true) }
                }
                Button("Refuse", role: .cancel) {
                    Task { await state.answer(approval: false) }
                }
            } message: {
                if let p = state.pendingApproval {
                    Text("\(p.name)\n\n\(p.reason)")
                }
            }
    }

    private var approvalBinding: Binding<Bool> {
        Binding(get: { state.pendingApproval != nil },
                set: { if !$0 { state.pendingApproval = nil } })
    }

    private var currentModelName: String { state.currentModelName }

    // ------------------------------------------------------------ transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if state.messages.isEmpty && !state.streaming {
                        VStack(spacing: 10) {
                            Image("OrbitMark").resizable().scaledToFit()
                                .frame(width: 56, height: 56).opacity(0.9)
                            Text("Ask anything").font(.headline)
                            Text("It will search the web, read your papers, run Python, "
                                 + "or query NCBI when it needs to — you don't name the tool.")
                                .font(.footnote).foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                            Text("Answering with \(currentModelName)")
                                .font(.caption2).foregroundStyle(.tertiary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 80).padding(.horizontal, 24)
                    }
                    ForEach(Array(state.messages.enumerated()), id: \.element.id) { i, m in
                        MessageBubble(message: m,
                                      isLast: i == state.messages.count - 1,
                                      onEdit: { msg in Task { await state.editAndResend(msg) } },
                                      onRegenerate: { Task { await state.regenerate() } },
                                      onQuote: { msg in quote(msg) })
                            .id(m.id)
                            .padding(.horizontal, flashed == i ? 8 : 0)
                            .padding(.vertical, flashed == i ? 6 : 0)
                            .background(flashed == i ? Color.yellow.opacity(0.18) : .clear,
                                        in: .rect(cornerRadius: 10))
                            .id("row-\(i)")
                    }
                    if state.streaming { liveBubble.id("live") }
                    if let e = state.lastError, !state.streaming { errorNote(e) }
                    Color.clear.frame(height: 8).id("bottom")
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
            }
            .defaultScrollAnchor(.bottom)          // open at the newest message
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: state.messages.count) { _, _ in scroll(proxy) }
            .onChange(of: state.liveText) { _, _ in scroll(proxy) }
            .onChange(of: jumpTo) { _, i in
                guard let i else { return }
                withAnimation(reduceMotion ? nil : .default) {
                    proxy.scrollTo("row-\(i)", anchor: .center)
                    flashed = i
                }
                jumpTo = nil
            }
            .onAppear { scroll(proxy, animated: false) }
            .modifier(AnswerTextSize())
            .task(id: sid) {
                // what you were typing here last time, unless something is being handed in
                draft = Drafts.load(sid)
                await state.open(sid)
                if let text = state.draftPrefill { draft = text; typing = true; state.draftPrefill = nil }
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

    private func scroll(_ proxy: ScrollViewProxy, animated: Bool = true) {
        let go = { proxy.scrollTo("bottom", anchor: .bottom) }
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

    /// `/new`, `/model`, `/compact`, `/find` — typed, or tapped from the strip.
    private func command(_ raw: String) -> Bool {
        switch raw.lowercased().split(separator: " ").first.map(String.init) ?? "" {
        case "/new":
            Task { if let sid = await state.newChat() { state.deepLink = sid } }
        case "/model":   showModels = true
        case "/compact": Task { await state.compactCurrent() }
        case "/find":
            finding = true; findFocused = true
            let rest = raw.split(separator: " ", maxSplits: 1).dropFirst().joined()
            if !rest.isEmpty { findText = rest }
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

    private var liveBubble: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(state.liveModel.isEmpty ? currentModelName : state.liveModel)
                .font(.caption2.smallCaps())
                .foregroundStyle(.secondary)

            ForEach(state.liveTools, id: \.self) { t in
                Text(t)
                    .font(.caption.monospaced())
                    .foregroundStyle(.orange)
                    .padding(.vertical, 5).padding(.horizontal, 9)
                    .background(.orange.opacity(0.10), in: .rect(cornerRadius: 7))
            }

            if !state.liveStatus.isEmpty && state.liveText.isEmpty {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.mini)
                    Text(state.liveStatus).font(.footnote).foregroundStyle(.secondary)
                }
            }

            if !state.liveText.isEmpty {
                MarkdownText(state.liveText)
            } else if state.liveStatus.isEmpty {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.mini)
                    Text("thinking").font(.footnote).foregroundStyle(.secondary)
                }
            }

            if !state.liveThinking.isEmpty {
                ThinkingBlock(text: state.liveThinking)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // ------------------------------------------------------------ composer

    private var composer: some View {
        Composer(draft: $draft, typing: $typing, modelName: currentModelName,
                 onPickModel: { showModels = true },
                 onCommand: { command($0) })
    }
}

/// Reasoning, folded away. Open it when you want to see how it got there.
struct ThinkingBlock: View {
    let text: String
    @State private var open = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) { open.toggle() }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: open ? "chevron.down" : "chevron.right")
                        .font(.caption2)
                    Text("thinking").font(.caption)
                }
                .foregroundStyle(.secondary)
            }
            if open {
                Text(text)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 9))
            }
        }
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
