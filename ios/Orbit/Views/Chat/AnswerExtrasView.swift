import SwiftUI

/// Under an answer: the sources it used and claims they barely support, any
/// warnings, a skill that matches, hooks that ran, and progress lines — all
/// sent only while the answer streamed, and kept on the phone for that answer.
struct TurnExtras: View {
    let sid: String?
    let turn: Int
    let prompt: String
    @ObservedObject private var store = TranscriptExtras.shared

    var body: some View {
        if let e = store.extras(sid: sid, turn: turn, prompt: prompt) {
            AnswerExtrasView(extras: e, sid: sid, turn: turn)
        }
    }
}

/// The same, for the answer being written now.
struct LiveTurnExtras: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        let users = state.messages.filter { $0.isUser && $0.note != true }
        TurnExtras(sid: state.openChat?.sid, turn: max(users.count - 1, 0), prompt: users.last?.text ?? "")
    }
}

struct AnswerExtrasView: View {
    let extras: AnswerExtras
    let sid: String?
    let turn: Int
    @EnvironmentObject var state: AppState
    @State private var hooksOpen = false
    @State private var sourcesOpen = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(extras.warnings.enumerated()), id: \.offset) { _, w in
                warning(w)
            }
            if let r = extras.retry { warning(r) }
            ForEach(Array(extras.lines.enumerated()), id: \.offset) { _, l in
                sysline(l)
            }
            if let l = extras.longRunning { sysline(l) }
            if !extras.hooks.lines.isEmpty { hooks }
            if let skill = extras.skillHint { skillHint(skill) }
            if !extras.sources.isEmpty { sources }
            if !extras.weakClaims.isEmpty { weakClaims }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func warning(_ text: String) -> some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .font(.caption)
            .foregroundStyle(.orange)
            .padding(.vertical, 5).padding(.horizontal, 9)
            .background(.orange.opacity(0.10), in: .rect(cornerRadius: 7))
            .fixedSize(horizontal: false, vertical: true)
    }

    private func sysline(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// One line per answer however many hooks ran; tap to see each.
    private var hooks: some View {
        VStack(alignment: .leading, spacing: 3) {
            Button { withAnimation(.snappy) { hooksOpen.toggle() } } label: {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    Text("⎿").foregroundStyle(.tertiary)
                    Text(extras.hooks.summary)
                        .foregroundStyle(extras.hooks.bad > 0 ? .orange : .secondary)
                        .multilineTextAlignment(.leading)
                    Image(systemName: hooksOpen ? "chevron.up" : "chevron.down")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
                .font(.caption.monospaced())
            }
            .buttonStyle(.plain)
            if hooksOpen {
                ForEach(Array(extras.hooks.lines.enumerated()), id: \.offset) { _, l in
                    Text(l).font(.caption2.monospaced()).foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .padding(.leading, 16)
                }
            }
        }
    }

    private func skillHint(_ name: String) -> some View {
        Button {
            state.draftPrefill = "Use the \(name) skill for this."
            if let sid { TranscriptExtras.shared.dismissSkillHint(sid: sid, turn: turn) }
        } label: {
            Label("matches your skill “\(name)” — tap to make it follow that procedure",
                  systemImage: "wand.and.stars")
                .font(.caption)
                .multilineTextAlignment(.leading)
                .padding(.vertical, 6).padding(.horizontal, 9)
                .background(Color.accentColor.opacity(0.10), in: .rect(cornerRadius: 7))
        }
        .buttonStyle(.plain)
        .foregroundStyle(.tint)
    }

    private var sources: some View {
        VStack(alignment: .leading, spacing: 5) {
            Button { withAnimation(.snappy) { sourcesOpen.toggle() } } label: {
                Label("sources used (\(extras.sources.count))",
                      systemImage: sourcesOpen ? "chevron.down" : "chevron.right")
                    .font(.caption.weight(.medium))
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            if sourcesOpen {
                ForEach(extras.sources) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(s.doc).font(.caption.weight(.semibold))
                            Text("score \(s.score)").font(.caption2).foregroundStyle(.tertiary)
                        }
                        Text(s.snippet).font(.caption2).foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.leading, 18)
                }
            }
        }
    }

    private var weakClaims: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Claims with little support in the retrieved sources")
                .font(.caption.weight(.semibold))
            ForEach(extras.weakClaims) { c in
                Text("(\(Int((c.support * 100).rounded()))% overlap) \(c.sentence)")
                    .font(.caption2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .foregroundStyle(.orange)
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.08), in: .rect(cornerRadius: 8))
    }
}
