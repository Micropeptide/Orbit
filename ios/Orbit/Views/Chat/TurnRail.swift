import SwiftUI

/// A minimap of the conversation down the right edge: one bar per turn, as tall as that
/// turn is long, the one you are reading lit and the running one breathing.
///
/// The outline sheet lists what you asked, which is a different question from "how long
/// is this and where am I in it" — in a sixty-turn chat that one had no answer at all.
///
/// On a phone this is a scrub, not a row of tiny targets: 3pt bars are far below the
/// 44pt minimum, so the gesture takes the whole strip and the bars are only what it
/// draws. It also sits clear of the screen edge, where the back swipe lives.
struct TurnRail: View {
    let sid: String
    /// (row index, the words you sent, how tall that turn is)
    let turns: [(index: Int, text: String, height: CGFloat)]
    var live = false
    /// Whether it is on screen at all. An always-on strip down the trailing edge takes
    /// every touch that lands there — a link, a Copy button, the edge of a code block —
    /// so it appears while you scroll or while an answer is being written, and fades.
    var showing = false
    var onPick: (Int) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var at: Int?
    @State private var scrubbing = false
    @State private var visible = false
    @State private var hideToken = UUID()

    private var tallest: CGFloat { max(turns.map(\.height).max() ?? 1, 1) }

    var body: some View {
        if turns.count >= 4 {
            HStack(spacing: 6) {
                if scrubbing, let i = at, i < turns.count {
                    Text(turns[i].text.isEmpty ? "(image)" : turns[i].text)
                        .font(.caption2).lineLimit(2)
                        .padding(.horizontal, 9).padding(.vertical, 6)
                        .frame(maxWidth: 190, alignment: .leading)
                        .background(.regularMaterial, in: .rect(cornerRadius: 8))
                        .transition(.opacity)
                }
                bars
            }
            .padding(.trailing, 20)
            .opacity(visible ? 1 : 0)
            .allowsHitTesting(visible)       // invisible, it takes no touches from the chat
            .animation(.easeOut(duration: 0.18), value: visible)
            .animation(.easeOut(duration: 0.15), value: scrubbing)
            .onChange(of: showing) { _, on in
                if on { visible = true; hideToken = UUID(); return }
                let token = UUID(); hideToken = token
                Task { try? await Task.sleep(for: .milliseconds(1400))
                       if hideToken == token && !scrubbing { visible = false } }
            }
        }
    }

    private var bars: some View {
        VStack(spacing: 3) {
            ForEach(Array(turns.enumerated()), id: \.offset) { i, t in
                Capsule()
                    .fill(colour(i))
                    .frame(width: i == at ? 5 : 3,
                           height: max(6, (26 * t.height / tallest).rounded()))
                    .opacity(i == at ? 1 : 0.45)
            }
        }
        .frame(width: 24)                     // the target is the strip, not the bar
        .contentShape(.rect)
        .opacity(scrubbing ? 1 : 0.55)
        // a real drag, not a tap: a tap here used to jump the transcript to a turn you
        // had not chosen, and the strip sits over the right edge of the conversation
        .gesture(
            DragGesture(minimumDistance: 6)
                .onChanged { v in
                    scrubbing = true
                    let i = index(at: v.location.y)
                    if i != at { at = i; Haptics.tap() }
                }
                .onEnded { _ in
                    if let i = at, i < turns.count { onPick(turns[i].index) }
                    scrubbing = false
                    at = nil            // nothing is "where you are" once you let go
                }
        )
        .accessibilityLabel("Turn navigator")
        .accessibilityHint("Drag to move through the conversation")
    }

    private func colour(_ i: Int) -> Color {
        if i == at { return .accentColor }
        if live && i == turns.count - 1 { return .accentColor }
        return .secondary
    }

    /// Which bar the thumb is over, from the heights the bars were drawn at.
    private func index(at y: CGFloat) -> Int {
        var top: CGFloat = 0
        for (i, t) in turns.enumerated() {
            let h = max(6, (26 * t.height / tallest).rounded()) + 3
            if y < top + h { return i }
            top += h
        }
        return max(turns.count - 1, 0)
    }
}
