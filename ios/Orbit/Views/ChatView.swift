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
    @FocusState private var typing: Bool

    var body: some View {
        // The banner and composer are safe-area insets rather than VStack rows:
        // that keeps the transcript's own inset correct, so text scrolls under
        // the navigation bar instead of starting behind it.
        transcript
            .safeAreaInset(edge: .top, spacing: 0) { ConnectionBanner() }
            .safeAreaInset(edge: .bottom, spacing: 0) { composer }
            .navigationTitle(state.openChat?.title ?? "New chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(.hidden, for: .tabBar)     // inside a conversation the keyboard needs the room
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: state.markdown(for: sid),
                              preview: SharePreview(state.openChat?.title ?? "Chat")) {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showModels = true } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "cpu")
                            Text(currentModelName).lineLimit(1)
                        }
                        .font(.caption)
                    }
                }
            }
            .sheet(isPresented: $showModels) { ModelPickerView() }
            .task(id: sid) { await state.open(sid) }
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

    private var currentModelName: String {
        state.models.first { $0.id == state.currentModel }?.display ?? "model"
    }

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
                        MessageBubble(message: m)
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
            .onAppear { scroll(proxy, animated: false) }
            .onChange(of: state.messages.count) { _, count in
                guard let h = highlight, h < count, flashed == nil else { return }
                // wait for the rows to exist before asking to scroll to one
                Task {
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    withAnimation { proxy.scrollTo("row-\(h)", anchor: .center) }
                    withAnimation { flashed = h }
                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                    withAnimation { flashed = nil }
                }
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
        if animated { withAnimation(.easeOut(duration: 0.18)) { go() } } else { go() }
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
        Composer(draft: $draft, typing: $typing)
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
