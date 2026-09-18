import SwiftUI

/// How full the open chat's context window is, always in view beside the model:
/// accent, then orange past 65%, red past 85%. Tap for the breakdown.
struct ContextGauge: View {
    @EnvironmentObject var state: AppState
    @State private var showing = false

    private var sid: String? { state.openChat?.sid }

    private var context: ContextState? {
        guard let sid, state.composerExtras.contextSid == sid else { return nil }
        return state.composerExtras.context
    }

    /// Read again when the chat changes, an answer starts or ends, or a message lands.
    private var refreshKey: String {
        "\(sid ?? "")|\(state.streaming)|\(state.messages.count)"
    }

    static func tint(_ pct: Double) -> Color {
        pct > 85 ? .red : pct > 65 ? .orange : .accentColor
    }

    var body: some View {
        Group {
            if let c = context {
                let pct = min(100, max(0, c.pct))
                Button { showing = true } label: {
                    HStack(spacing: 5) {
                        ZStack(alignment: .leading) {
                            Capsule().fill(.quaternary)
                            Capsule().fill(Self.tint(pct))
                                .frame(width: max(2, 28 * pct / 100))
                        }
                        .frame(width: 28, height: 5)
                        Text("\(Int(pct.rounded()))%")
                            .font(.caption.monospacedDigit().weight(.medium))
                    }
                    .foregroundStyle(pct > 65 ? Self.tint(pct) : .secondary)
                    .padding(.horizontal, 9).padding(.vertical, 4)
                    .background(.quaternary.opacity(0.35), in: .capsule)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Context \(Int(pct.rounded())) percent used, "
                                    + "\(c.used.formatted()) of \(c.max.formatted()) tokens")
                .accessibilityHint("Shows what fills it")
                .sheet(isPresented: $showing) {
                    if let sid { ContextSheet(sid: sid) }
                }
            }
        }
        .task(id: refreshKey) {
            await state.refreshContextGauge()
            // while it answers the window fills; keep the gauge moving
            while state.streaming, !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 10_000_000_000)
                guard !Task.isCancelled else { return }
                await state.refreshContextGauge()
            }
        }
    }
}

/// Claude Code's warning once the window is nearly full, with what to do about it.
/// Shown once per chat, until compacting frees the room again.
struct ContextLowLine: View {
    @EnvironmentObject var state: AppState
    /// Auto-compact starts at 80% by default; warn a little before.
    private static let warnAt = 75.0

    var body: some View {
        if let sid = state.openChat?.sid, state.composerExtras.contextSid == sid,
           let c = state.composerExtras.context, c.pct >= Self.warnAt,
           !state.composerExtras.contextWarned.contains(sid) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.circle").foregroundStyle(ContextGauge.tint(c.pct))
                Button {
                    state.composerExtras.contextWarned.insert(sid)
                    Task { await state.compactCurrent() }
                } label: {
                    Text("Context low (\(Int(max(0, 100 - c.pct).rounded()))% remaining) — ")
                        + Text("/compact").font(.caption.monospaced().weight(.semibold))
                        + Text(" to summarise and carry on")
                }
                .buttonStyle(.plain)
                .disabled(state.streaming)
                Spacer(minLength: 4)
                Button {
                    state.composerExtras.contextWarned.insert(sid)
                } label: { Image(systemName: "xmark").font(.caption2) }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
                    .accessibilityLabel("Dismiss")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 16).padding(.top, 6)
        }
    }
}
