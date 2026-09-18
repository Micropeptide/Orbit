import SwiftUI

/// A short tour, once, right after this phone first pairs — the phone's
/// version of the welcome the Mac's web page shows on its first run.
struct OnboardingTips: View {
    @EnvironmentObject var state: AppState
    @Environment(\.dismiss) private var dismiss
    var onDone: () -> Void = {}

    private struct Tip: Identifiable {
        let symbol: String
        let title: String
        let text: String
        var id: String { title }
    }

    private let tips: [Tip] = [
        Tip(symbol: "bubble.left.and.bubble.right", title: "Just ask",
            text: "Chats run on your Mac, with its tools, files and models. The phone shows the same "
                + "conversations as the Mac, and an answer keeps going if you lock the phone."),
        Tip(symbol: "square.and.pencil", title: "Pick how a chat runs",
            text: "Tap the pencil for a chat like your last one. Hold it for New chat with… — Orbit, "
                + "Claude Code or Codex, the model, the machine and folder — and save that as a preset."),
        Tip(symbol: "hand.draw", title: "Swipe and hold",
            text: "Swipe a chat to pin, archive or bin it; hold it for tags, projects and export. "
                + "Sessions you began in Claude Code, Codex or OpenCode have their own sections below your chats."),
        Tip(symbol: "clock", title: "What runs on its own",
            text: "Scheduled shows what is running now, messages set for later and tasks your Mac runs on a "
                + "timetable — with a way to open or stop each."),
        Tip(symbol: "hand.raised", title: "It asks before doing harm",
            text: "Approvals and questions come to the phone too. Destructive commands wait for you; "
                + "some are refused outright."),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Text("Paired with \(state.macDisplayName). A few things worth knowing:")
                        .font(.callout).foregroundStyle(.secondary)
                    ForEach(tips) { t in
                        HStack(alignment: .top, spacing: 14) {
                            Image(systemName: t.symbol)
                                .font(.title3)
                                .foregroundStyle(Color.accentColor)
                                .frame(width: 30)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(t.title).font(.headline)
                                Text(t.text).font(.callout).foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                    Text("Settings has everything else the Mac offers — models and keys, Claude Code, Codex, phone access.")
                        .font(.footnote).foregroundStyle(.tertiary)
                }
                .padding(22)
            }
            .safeAreaInset(edge: .bottom) {
                Button {
                    onDone()
                    dismiss()
                } label: {
                    Text("Get started").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.horizontal, 22).padding(.bottom, 12)
                .background(.bar)
            }
            .navigationTitle("Welcome to Orbit")
            .navigationBarTitleDisplayMode(.inline)
        }
        // swiped away counts as seen too
        .onDisappear(perform: onDone)
    }
}
