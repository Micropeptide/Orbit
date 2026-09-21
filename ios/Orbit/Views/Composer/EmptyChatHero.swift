import SwiftUI

/// Under the greeting of an empty chat: what the box can do, as tappable tips,
/// and the chats you were last in — the way the Mac's web page opens a new chat.
struct EmptyChatHero: View {
    let sid: String
    @EnvironmentObject var state: AppState
    @State private var showShortcuts = false

    // ⇧Tab and ? need a keyboard, which a phone has not got: the two they replace are
    // things you can actually reach with a thumb.
    private static let tips: [(key: String, text: String)] = [
        ("/", "commands"), ("@", "mention a file"), ("!", "run a shell command"),
        ("#", "save to memory"),
    ]

    /// A few things this chat could be asked — for the case the recent list does not
    /// cover, which is the first one. They fill the box and stop there.
    private static let suggestions: [HarnessKind: [String]] = [
        .claude: ["Explain what this repository does and how it is laid out",
                  "Find the bug behind this failing test and fix it",
                  "Review my uncommitted changes",
                  "Add tests for the file I changed last"],
        .codex: ["Explain what this repository does and how it is laid out",
                 "Refactor this file and keep every test passing",
                 "Write the commit message for what is staged"],
        .orbit: ["Search my knowledge base and summarise what it says about…",
                 "Read this paper and tell me whether its method fits my data",
                 "Plot this CSV and say what stands out",
                 "Check whether this citation supports the claim"],
    ]

    private var suggested: some View {
        let list = Self.suggestions[state.harnessMode] ?? Self.suggestions[.orbit] ?? []
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(list, id: \.self) { t in
                    Button {
                        Haptics.tap()
                        state.draftPrefill = t
                    } label: {
                        Text(t)
                            .font(.footnote)
                            .lineLimit(1)
                            .padding(.vertical, 7).padding(.horizontal, 14)
                            .background(.quaternary.opacity(0.35), in: .capsule)
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
        }
        .scrollClipDisabled()
    }

    private var recent: [ChatSummary] {
        Array(state.chats.filter { $0.id != sid && $0.archived != true }.prefix(5))
    }

    var body: some View {
        VStack(spacing: 18) {
            FlowTips(tips: Self.tips) { key in
                Haptics.tap()
                switch key {
                case "?": showShortcuts = true
                case "⇧Tab":
                    Task { await state.cyclePermissionMode() }
                case "#": state.draftPrefill = "# "
                default: state.draftPrefill = key
                }
            }
            suggested
            HomeDashboard()
            if !recent.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    Text("PICK UP WHERE YOU LEFT OFF")
                        .font(.caption2.weight(.semibold)).tracking(0.6).foregroundStyle(.secondary)
                        .padding(.horizontal, 12).padding(.bottom, 6)
                    ForEach(recent) { chat in
                        Button {
                            state.deepLink = chat.id
                        } label: {
                            HStack(spacing: 8) {
                                Text(chat.displayTitle).font(.callout).lineLimit(1)
                                    .foregroundStyle(.primary)
                                Spacer(minLength: 8)
                                if chat.mtime > 0 {
                                    Text(MessageTimeText.relative(chat.mtime))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .padding(.horizontal, 12).padding(.vertical, 9)
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 8)
                .background(.quaternary.opacity(0.25), in: .rect(cornerRadius: 12))
                .frame(maxWidth: 520)
            }
        }
        .padding(.top, 10)
        .sheet(isPresented: $showShortcuts) { ShortcutsSheet() }
    }
}

/// The tips as small chips, wrapping onto as many lines as they need.
private struct FlowTips: View {
    let tips: [(key: String, text: String)]
    var tap: (String) -> Void

    var body: some View {
        WrapLayout(spacing: 6) {
            ForEach(tips, id: \.key) { tip in
                Button { tap(tip.key) } label: {
                    HStack(spacing: 4) {
                        Text(tip.key).font(.caption.monospaced().weight(.bold))
                        Text(tip.text).font(.caption)
                    }
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(.quaternary.opacity(0.35), in: .capsule)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// Lays children left to right, starting a new centred line when one is full.
private struct WrapLayout: Layout {
    var spacing: CGFloat

    private func lines(_ subviews: Subviews, width: CGFloat) -> [[(Int, CGSize)]] {
        var out: [[(Int, CGSize)]] = [[]]
        var x: CGFloat = 0
        for (i, v) in subviews.enumerated() {
            let s = v.sizeThatFits(.unspecified)
            if x > 0, x + s.width > width { out.append([]); x = 0 }
            out[out.count - 1].append((i, s))
            x += s.width + spacing
        }
        return out
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        let ls = lines(subviews, width: width)
        let h = ls.map { $0.map(\.1.height).max() ?? 0 }.reduce(0, +) + spacing * CGFloat(max(0, ls.count - 1))
        let w = ls.map { l in l.map(\.1.width).reduce(0, +) + spacing * CGFloat(max(0, l.count - 1)) }.max() ?? 0
        return CGSize(width: min(width, w), height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for line in lines(subviews, width: bounds.width) {
            let lw = line.map(\.1.width).reduce(0, +) + spacing * CGFloat(max(0, line.count - 1))
            var x = bounds.minX + max(0, (bounds.width - lw) / 2)
            let lh = line.map(\.1.height).max() ?? 0
            for (i, s) in line {
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
                x += s.width + spacing
            }
            y += lh + spacing
        }
    }
}

extension AppState {
    /// Shift+Tab: a Claude Code or Codex chat moves to its next permission mode;
    /// one of Orbit's own chats goes in or out of plan mode.
    func cyclePermissionMode() async {
        guard let server, let sid = openChat?.sid else { return }
        let work = try? await server.chatWork(sid: sid)
        _ = await cycleMode(work: work)
    }
}

/// When a message was sent or an answer finished, small under it.
struct MessageTime: View {
    let t: Double
    var trailing = false

    var body: some View {
        Text(MessageTimeText.describe(t))
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.tertiary)
            .frame(maxWidth: .infinity, alignment: trailing ? .trailing : .leading)
    }
}
